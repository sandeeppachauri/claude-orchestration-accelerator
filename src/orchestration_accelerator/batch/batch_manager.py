"""
batch_manager.py

Split batch API -- submit_batch()/get_batch_status()/collect_batch()/
cancel_batch()/resubmit_failed() -- plus execute_batch() as a thin
backward-compatible wrapper over them. See .claude/rules/batch-registry.md.

submit_batch() renders each item via the same PromptManager used by the
text path, submits one (or more, if `max_requests_per_batch` is exceeded)
real Anthropic Message Batches API job, and returns immediately with a
JSON-serializable BatchHandle -- no polling inside this call, so a caller
that persists the handle can survive a process restart without losing a
paid batch. collect_batch() is idempotent: safe to call more than once
for the same handle, always calls the provider's own results endpoint
fresh.

Batches are messages_api only -- there is no agent_sdk batch surface.
Auth is resolved exactly like model_router_accelerator.backends:
lazy import, build_api_credential(environment).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from orchestration_accelerator.environment import resolve_environment
from orchestration_accelerator.errors import friendly_error
from orchestration_accelerator.prompting import PromptManager
from orchestration_accelerator.registry import (
    UnsupportedCapabilityError,
    get_process,
    get_process_by_id,
    validate_capabilities,
)

from .batch_handle import make_batch_handle, make_batch_result
from .batch_registry import DEFAULT_BATCH_REGISTRY_PATH, get_batch_job
from .batch_state_store import resolve_batch_state_store

_REQUIRED_PAYLOAD_KEYS = {"batch_id", "inputs"}
_OPTIONAL_PAYLOAD_KEYS = {"environment"}

_REQUIRED_SUBMIT_KEYS = {"batch_id"}
_OPTIONAL_SUBMIT_KEYS = {"items", "inputs", "correlation", "environment"}


class BatchJobError(Exception):
    """Raised on batch submission, polling timeout, or result-retrieval
    failure."""


def _resolve_project_config_path(filename: str, package_default: Path) -> Path:
    """Same cwd-first-else-shipped-default resolution as
    project_accelerator.core's helpers of the same shape -- duplicated
    (not imported) to avoid orchestration_accelerator (a lower layer)
    depending on project_accelerator (a higher one)."""
    cwd_path = Path.cwd() / "config" / filename
    if cwd_path.exists():
        return cwd_path
    return package_default


def _resolve_capability_registry_path() -> Path:
    from orchestration_accelerator.registry import DEFAULT_CAPABILITY_REGISTRY_PATH

    return _resolve_project_config_path("capability_registry.yaml", DEFAULT_CAPABILITY_REGISTRY_PATH)


def _resolve_prompt_guardrails_path() -> Path:
    from orchestration_accelerator.prompt_guardrails import DEFAULT_PROMPT_GUARDRAILS_CONFIG_PATH

    return _resolve_project_config_path(
        "prompt_guardrails.yaml", DEFAULT_PROMPT_GUARDRAILS_CONFIG_PATH
    )


def _validate_payload(payload: dict[str, Any]) -> None:
    missing = _REQUIRED_PAYLOAD_KEYS - payload.keys()
    if missing:
        raise BatchJobError(f"payload is missing required key(s): {sorted(missing)}")
    unknown = set(payload.keys()) - (_REQUIRED_PAYLOAD_KEYS | _OPTIONAL_PAYLOAD_KEYS)
    if unknown:
        raise BatchJobError(f"payload has unknown key(s): {sorted(unknown)}")
    if not isinstance(payload["inputs"], list) or not payload["inputs"]:
        raise BatchJobError("payload['inputs'] must be a non-empty list.")


def _validate_submit_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """submit_batch() accepts either `items` (list of
    {custom_id, input, attachments?}) or legacy `inputs` (bare list,
    custom_id auto-generated as f"{batch_id}-{i}") -- exactly one of the
    two. Returns a normalized list of {custom_id, input, attachments}."""
    missing = _REQUIRED_SUBMIT_KEYS - payload.keys()
    if missing:
        raise BatchJobError(f"payload is missing required key(s): {sorted(missing)}")
    unknown = set(payload.keys()) - (_REQUIRED_SUBMIT_KEYS | _OPTIONAL_SUBMIT_KEYS)
    if unknown:
        raise BatchJobError(f"payload has unknown key(s): {sorted(unknown)}")

    has_items = "items" in payload
    has_inputs = "inputs" in payload
    if has_items == has_inputs:
        raise BatchJobError(
            "payload must set exactly one of 'items' or 'inputs' (legacy), not both/neither."
        )

    batch_id = payload["batch_id"]
    if has_inputs:
        inputs = payload["inputs"]
        if not isinstance(inputs, list) or not inputs:
            raise BatchJobError("payload['inputs'] must be a non-empty list.")
        return [
            {"custom_id": f"{batch_id}-{i}", "input": item, "attachments": None}
            for i, item in enumerate(inputs)
        ]

    items = payload["items"]
    if not isinstance(items, list) or not items:
        raise BatchJobError("payload['items'] must be a non-empty list.")
    normalized = []
    for entry in items:
        if "custom_id" not in entry or "input" not in entry:
            raise BatchJobError(f"Each 'items' entry needs 'custom_id' and 'input', got {entry!r}.")
        normalized.append(
            {
                "custom_id": entry["custom_id"],
                "input": entry["input"],
                "attachments": entry.get("attachments"),
            }
        )
    return normalized


def _client(environment: str):
    try:
        import anthropic
    except ImportError as exc:
        raise BatchJobError(
            "The 'anthropic' package is required for batch processing."
        ) from exc
    from auth_accelerator import build_api_credential, build_base_url

    api_key = build_api_credential(environment)
    return anthropic.Anthropic(api_key=api_key, base_url=build_base_url(environment))


def _resolve_step(
    process_id: str, step_name: str | None, registry_path: Path | str | None
) -> tuple[str, str, dict[str, Any]]:
    kwargs = {"path": registry_path} if registry_path else {}
    process_name, block = get_process_by_id(process_id, **kwargs)
    process = get_process(process_name, **kwargs)
    steps = process["steps"]
    if step_name is None:
        if len(steps) != 1:
            raise BatchJobError(
                f"Process '{process_name}' has multiple steps {steps}; "
                f"batch_registry.yaml entry must set `step` to pick one."
            )
        step_name = steps[0]
    elif step_name not in steps:
        raise BatchJobError(
            f"Step '{step_name}' is not part of process '{process_name}''s steps {steps}."
        )
    return process_name, step_name, process["step_config"][step_name]


def _prompts_dir_for_registry(registry_path: Path | str | None) -> Path:
    if registry_path is None:
        from orchestration_accelerator.prompting import PROMPTS_DIR

        return PROMPTS_DIR
    registry_dir = Path(registry_path).parent
    # process_registry.yaml lives under config/, prompts/ stays a sibling
    # of config/ at the project root -- not a sibling of the registry file
    # itself.
    project_root = registry_dir.parent if registry_dir.name == "config" else registry_dir
    return project_root / "prompts"


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


def _build_requests(
    normalized_items: list[dict[str, Any]],
    pm: PromptManager,
    step_name: str,
    step_config: dict[str, Any],
    model: str,
    environment: str = "local",
    backend: str = "messages_api",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Returns (anthropic batch request dicts, {custom_id: cfg}) --
    `cfg` is the rendered PromptConfig used later by
    PromptManager.validate_output(), or None for a no-prompt-file step."""
    prompt_file = step_config.get("prompt")
    capabilities = {
        k: v
        for k, v in step_config.items()
        if k not in ("prompt", "model", "fallback", "system_prompt")
    }
    capabilities.pop("max_tokens", None)
    max_tokens = step_config.get("max_tokens", 1024)

    if capabilities:
        validate_capabilities(
            capabilities, backend, path=_resolve_capability_registry_path()
        )

    configs: dict[str, Any] = {}
    requests = []
    for entry in normalized_items:
        custom_id = entry["custom_id"]
        item = entry["input"]
        attachments = entry.get("attachments")
        assistant_prompt = None
        if prompt_file is not None:
            cfg, system_prompt, assistant_prompt, user_content = pm.render(
                step_name, item, filename=prompt_file
            )
            configs[custom_id] = cfg
        else:
            system_prompt = step_config.get("system_prompt", "You are a helpful assistant.")
            user_content = item
            configs[custom_id] = None

        user_message_content: str | list[dict[str, Any]] = user_content
        if attachments:
            from model_router_accelerator.attachments import build_messages_api_blocks

            attachment_blocks, _uploaded = build_messages_api_blocks(attachments, environment)
            user_message_content = [*attachment_blocks, {"type": "text", "text": user_content}]

        batch_messages: list[dict[str, Any]] = []
        if assistant_prompt is not None:
            batch_messages.append({"role": "assistant", "content": assistant_prompt})
        batch_messages.append({"role": "user", "content": user_message_content})
        requests.append(
            {
                "custom_id": custom_id,
                "params": {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": batch_messages,
                    **capabilities,
                },
            }
        )
    return requests, configs


def _submit_chunk_with_fallback(
    client: Any, requests: list[dict[str, Any]], chain: list[str]
) -> tuple[Any, str]:
    """Batches have no per-item fallback mid-flight -- if submission
    fails outright for one model, resubmit the whole chunk with the next
    model in the chain. Returns (provider batch object, model actually
    used)."""
    last_error: Exception | None = None
    for candidate_model in chain:
        retried_requests = [
            {**r, "params": {**r["params"], "model": candidate_model}} for r in requests
        ]
        try:
            return client.messages.batches.create(requests=retried_requests), candidate_model
        except Exception as exc:  # noqa: BLE001 - any submission failure triggers fallback
            last_error = exc
            continue
    raise BatchJobError(f"Batch submission failed for every model in {chain}: {last_error}")


def submit_batch(
    payload: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any]:
    """Renders every item and submits one (or more, chunked by
    `max_requests_per_batch`) real Anthropic Message Batches API job(s),
    then returns immediately -- no polling. Returns a JSON-serializable
    BatchHandle (see batch_handle.py); the caller persists it (directly,
    or via the batch_registry.yaml entry's `state_store`, see
    batch_state_store.py) and passes it to get_batch_status()/
    collect_batch()/cancel_batch()/resubmit_failed() later, even from a
    different process."""
    normalized_items = _validate_submit_payload(payload)
    batch_id = payload["batch_id"]

    batch_registry_path = (
        Path(registry_path).parent / "batch_registry.yaml"
        if registry_path
        else DEFAULT_BATCH_REGISTRY_PATH
    )
    job = get_batch_job(batch_id, path=batch_registry_path)
    environment = resolve_environment(payload.get("environment") or job["environment"])

    process_name, step_name, step_config = _resolve_step(
        job["process_id"], job["step"], registry_path
    )

    prompts_dir = _prompts_dir_for_registry(registry_path)
    pm = PromptManager(
        prompts_dir=prompts_dir, prompt_guardrails_path=_resolve_prompt_guardrails_path()
    )
    model = step_config["model"]
    fallback = list(step_config.get("fallback", []))

    requests, configs = _build_requests(
        normalized_items, pm, step_name, step_config, model, environment=environment
    )

    client = _client(environment)
    provider_batch_ids: list[str] = []
    model_used = model
    for chunk in _chunk(requests, job["max_requests_per_batch"]):
        if not chunk:
            continue
        batch, model_used = _submit_chunk_with_fallback(client, chunk, [model] + fallback)
        provider_batch_ids.append(batch.id)

    fallback_remaining = fallback[fallback.index(model_used) + 1 :] if model_used in fallback else fallback

    prompt_file = step_config.get("prompt")
    handle = make_batch_handle(
        batch_job=batch_id,
        provider_batch_ids=provider_batch_ids,
        process_id=job["process_id"],
        step=step_name,
        model=model_used,
        fallback_remaining=fallback_remaining,
        prompt_file=prompt_file,
        prompt_version=None,
        environment=environment,
        custom_ids=[entry["custom_id"] for entry in normalized_items],
        correlation=payload.get("correlation"),
    )
    # `_configs`/`_process_name`/`_items_by_custom_id` are carried
    # alongside the handle in memory only (never persisted -- a state
    # store round-trips plain JSON) so collect_batch()/resubmit_failed()
    # can re-render/validate output or retry within the *same*
    # submit_batch() call's return value, if the caller doesn't tear down
    # the process. A caller resuming from a persisted handle in a fresh
    # process loses these -- collect_batch() falls back to raw text only
    # (see its docstring), and resubmit_failed() requires the original
    # handle object (not a round-tripped dict) to retry.
    handle["_configs"] = configs
    handle["_process_name"] = process_name
    handle["_items_by_custom_id"] = {entry["custom_id"]: entry for entry in normalized_items}

    state_store = resolve_batch_state_store(job["state_store"])
    state_store.save({k: v for k, v in handle.items() if not k.startswith("_")})

    return handle


def get_batch_status(
    handle: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any]:
    """Non-blocking status check -- one `batches.retrieve(...)` call per
    provider_batch_id in the handle (a chunked submission has more than
    one). Returns {batch_job, provider_batch_ids, statuses: [str, ...],
    all_ended: bool}."""
    environment = handle["environment"]
    client = _client(environment)
    statuses = []
    for provider_batch_id in handle["provider_batch_ids"]:
        batch = client.messages.batches.retrieve(provider_batch_id)
        statuses.append(batch.processing_status)
    return {
        "batch_job": handle["batch_job"],
        "provider_batch_ids": handle["provider_batch_ids"],
        "statuses": statuses,
        "all_ended": all(s == "ended" for s in statuses),
    }


def _extract_text(message: Any) -> str:
    """Joins every type=="text" content block, same loop
    model_router_accelerator.backends.call_messages_api() already uses --
    NOT content[0].text, which silently returns the wrong (or no) text
    when `thinking` is enabled and block 0 is a thinking block instead."""
    text = ""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    return text


def _extract_usage(message: Any) -> dict[str, Any]:
    usage = getattr(message, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None),
    }


def collect_batch(
    handle: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any]:
    """Idempotent -- safe to call more than once for the same handle,
    always retrieves fresh from the provider. Retrieves results across
    every provider_batch_id in the handle (chunked submissions included),
    reads full usage/model/stop_reason per item (not just the output
    text), and returns a BatchResult with `totals` summed across every
    item for metering."""
    environment = handle["environment"]
    client = _client(environment)

    configs = handle.get("_configs")
    process_name = handle.get("_process_name")
    step_name = handle["step"]
    if configs is None:
        # Resumed from a persisted handle in a fresh process -- configs
        # were never persisted (see submit_batch()'s docstring), so
        # output validation is skipped for a resumed collect (raw text
        # only). A caller wanting validated output on a cross-process
        # resume should keep its own copy of the prompt config, or call
        # collect_batch() in the same process that submitted the batch.
        configs = {}
        process_name = None

    results_by_custom_id: dict[str, Any] = {}
    for provider_batch_id in handle["provider_batch_ids"]:
        batch = client.messages.batches.retrieve(provider_batch_id)
        if batch.processing_status != "ended":
            raise BatchJobError(
                f"Batch '{provider_batch_id}' has not finished yet "
                f"(status: {batch.processing_status}). Call get_batch_status() "
                f"first, or poll until all_ended is True."
            )
        try:
            for entry in client.messages.batches.results(provider_batch_id):
                results_by_custom_id[entry.custom_id] = entry
        except Exception as exc:  # noqa: BLE001
            raise BatchJobError(
                f"Failed to retrieve results for batch '{provider_batch_id}': {exc}"
            ) from exc

    prompts_dir = _prompts_dir_for_registry(registry_path)
    pm = PromptManager(
        prompts_dir=prompts_dir, prompt_guardrails_path=_resolve_prompt_guardrails_path()
    ) if process_name is not None else None

    results = []
    for custom_id in handle["custom_ids"]:
        entry = results_by_custom_id.get(custom_id)
        result_type = getattr(entry.result, "type", None) if entry is not None else None

        if entry is None:
            results.append({"custom_id": custom_id, "status": "errored", "input": None, "output": None,
                             "raw_output": None, "model_used": None, "stop_reason": None,
                             "request_id": None, "usage": {}, "error": "No result entry returned."})
            continue

        if result_type != "succeeded":
            status = result_type if result_type in ("errored", "expired", "canceled") else "errored"
            results.append({"custom_id": custom_id, "status": status, "input": None, "output": None,
                             "raw_output": None, "model_used": None, "stop_reason": None,
                             "request_id": None, "usage": {}, "error": str(entry.result)})
            continue

        message = entry.result.message
        raw_output = _extract_text(message)
        cfg = configs.get(custom_id)
        output = raw_output
        error = None
        if cfg is not None and pm is not None:
            try:
                output = pm.validate_output(step_name, cfg, raw_output)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

        results.append(
            {
                "custom_id": custom_id,
                "status": "succeeded",
                "input": None,
                "output": output,
                "raw_output": raw_output,
                "model_used": getattr(message, "model", handle["model"]),
                "stop_reason": getattr(message, "stop_reason", None),
                "request_id": getattr(entry, "id", None),
                "usage": _extract_usage(message),
                "error": error,
            }
        )

    batch_registry_path = (
        Path(registry_path).parent / "batch_registry.yaml"
        if registry_path
        else DEFAULT_BATCH_REGISTRY_PATH
    )
    job = get_batch_job(handle["batch_job"], path=batch_registry_path)
    state_store = resolve_batch_state_store(job["state_store"])
    state_store.mark_collected(handle["batch_job"], handle["provider_batch_ids"])

    return make_batch_result(
        batch_job=handle["batch_job"],
        provider_batch_ids=handle["provider_batch_ids"],
        status="ended",
        results=results,
    )


def cancel_batch(handle: dict[str, Any]) -> dict[str, Any]:
    """Cancels every provider_batch_id in the handle. Returns
    {batch_job, provider_batch_ids, canceled: [bool, ...]} -- a batch
    already past a cancelable state is not treated as an error, its
    entry is simply False."""
    environment = handle["environment"]
    client = _client(environment)
    canceled = []
    for provider_batch_id in handle["provider_batch_ids"]:
        try:
            client.messages.batches.cancel(provider_batch_id)
            canceled.append(True)
        except Exception:  # noqa: BLE001
            canceled.append(False)
    return {
        "batch_job": handle["batch_job"],
        "provider_batch_ids": handle["provider_batch_ids"],
        "canceled": canceled,
    }


def resubmit_failed(
    handle: dict[str, Any], batch_result: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any] | None:
    """Re-submits only the items whose result was 'errored', against the
    next model in `handle['fallback_remaining']`. Returns a new
    BatchHandle for the retry batch, or None if there is nothing to
    retry (no errored items) or no fallback model remains.

    Requires the *same handle object* submit_batch() returned (or one
    that still carries its in-memory `_items_by_custom_id` -- a handle
    round-tripped through a BatchStateStore/JSON loses this, since it is
    never persisted). A resumed-from-storage handle has no way to recover
    the original per-item inputs to retry with; re-call submit_batch()
    with just the failed items' original inputs in that case instead."""
    errored_custom_ids = {r["custom_id"] for r in batch_result["results"] if r["status"] == "errored"}
    if not errored_custom_ids:
        return None
    if not handle["fallback_remaining"]:
        raise BatchJobError(
            f"Batch '{handle['batch_job']}' has {len(errored_custom_ids)} errored item(s) "
            f"but no fallback model remains in fallback_remaining."
        )

    items_by_custom_id = handle.get("_items_by_custom_id")
    if items_by_custom_id is None:
        raise BatchJobError(
            "resubmit_failed() requires the original submit_batch() handle "
            "object (with its in-memory item inputs) -- a handle resumed from "
            "a BatchStateStore/JSON round-trip cannot retry, since original "
            "item inputs are never persisted. Re-call submit_batch() with "
            f"just the failed custom_id(s) {sorted(errored_custom_ids)}'s "
            f"original inputs instead."
        )

    next_model = handle["fallback_remaining"][0]
    remaining_after = handle["fallback_remaining"][1:]

    process_name, step_name, step_config = _resolve_step(
        handle["process_id"], handle["step"], registry_path
    )
    step_config = {**step_config, "model": next_model}

    retry_items = [items_by_custom_id[custom_id] for custom_id in sorted(errored_custom_ids)]

    prompts_dir = _prompts_dir_for_registry(registry_path)
    pm = PromptManager(
        prompts_dir=prompts_dir, prompt_guardrails_path=_resolve_prompt_guardrails_path()
    )
    requests, configs = _build_requests(
        retry_items, pm, step_name, step_config, next_model, environment=handle["environment"]
    )

    batch_registry_path = (
        Path(registry_path).parent / "batch_registry.yaml"
        if registry_path
        else DEFAULT_BATCH_REGISTRY_PATH
    )
    job = get_batch_job(handle["batch_job"], path=batch_registry_path)

    client = _client(handle["environment"])
    provider_batch_ids: list[str] = []
    for chunk in _chunk(requests, job["max_requests_per_batch"]):
        if not chunk:
            continue
        batch, _model_used = _submit_chunk_with_fallback(client, chunk, [next_model])
        provider_batch_ids.append(batch.id)

    retry_handle = make_batch_handle(
        batch_job=handle["batch_job"],
        provider_batch_ids=provider_batch_ids,
        process_id=handle["process_id"],
        step=step_name,
        model=next_model,
        fallback_remaining=remaining_after,
        prompt_file=handle["prompt_file"],
        prompt_version=handle["prompt_version"],
        environment=handle["environment"],
        custom_ids=sorted(errored_custom_ids),
        correlation=handle["correlation"],
    )
    retry_handle["_configs"] = configs
    retry_handle["_process_name"] = process_name
    retry_handle["_items_by_custom_id"] = {c: items_by_custom_id[c] for c in errored_custom_ids}

    state_store = resolve_batch_state_store(job["state_store"])
    state_store.save({k: v for k, v in retry_handle.items() if not k.startswith("_")})

    return retry_handle


def execute_batch(
    payload: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any]:
    """Backward-compatible thin wrapper: submit_batch() -> poll (same
    poll_interval_seconds/poll_timeout_seconds as before) -> collect_batch(),
    for callers who still want the old one-call blocking behavior. Returns
    the pre-split shape ({"batch_id": ..., "results": [{"input", "output",
    "error"}, ...]}) unchanged, so existing callers are unaffected."""
    _validate_payload(payload)
    batch_id = payload["batch_id"]
    inputs = payload["inputs"]

    batch_registry_path = (
        Path(registry_path).parent / "batch_registry.yaml"
        if registry_path
        else DEFAULT_BATCH_REGISTRY_PATH
    )
    job = get_batch_job(batch_id, path=batch_registry_path)

    handle = submit_batch(
        {"batch_id": batch_id, "inputs": inputs, "environment": payload.get("environment")},
        registry_path=registry_path,
    )

    deadline = time.monotonic() + job["poll_timeout_seconds"]
    while True:
        status = get_batch_status(handle, registry_path=registry_path)
        if status["all_ended"]:
            break
        if time.monotonic() >= deadline:
            raise BatchJobError(
                f"Batch '{batch_id}' did not finish within "
                f"{job['poll_timeout_seconds']}s (last statuses: {status['statuses']})."
            )
        time.sleep(job["poll_interval_seconds"])

    batch_result = collect_batch(handle, registry_path=registry_path)

    results_by_custom_id = {r["custom_id"]: r for r in batch_result["results"]}
    results = []
    for i, item in enumerate(inputs):
        custom_id = f"{batch_id}-{i}"
        r = results_by_custom_id.get(custom_id)
        if r is None or r["status"] != "succeeded":
            results.append({"input": item, "output": None, "error": r["error"] if r else "No result."})
            continue
        results.append({"input": item, "output": r["output"], "error": r["error"]})

    return {"batch_id": batch_id, "results": results}

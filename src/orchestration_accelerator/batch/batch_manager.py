"""
batch_manager.py

execute_batch(payload) -- the batch counterpart to
project_accelerator.core.execute(). Submits a *list* of inputs for one
process/step as a real Anthropic Message Batches API job (not a loop over
execute()): render each input via the same PromptManager used by the text
path, submit one Anthropic batch, poll until done, retrieve + validate
results.

Batches are messages_api only -- there is no agent_sdk batch surface.
Auth is resolved exactly like model_router_accelerator.backends:
lazy import, build_api_credential(environment).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from orchestration_accelerator.environment import resolve_environment
from orchestration_accelerator.prompting import PromptManager
from orchestration_accelerator.registry import get_process, get_process_by_id

from .batch_registry import DEFAULT_BATCH_REGISTRY_PATH, get_batch_job

_REQUIRED_PAYLOAD_KEYS = {"batch_id", "inputs"}
_OPTIONAL_PAYLOAD_KEYS = {"environment"}


class BatchJobError(Exception):
    """Raised on batch submission, polling timeout, or result-retrieval
    failure."""


def _validate_payload(payload: dict[str, Any]) -> None:
    missing = _REQUIRED_PAYLOAD_KEYS - payload.keys()
    if missing:
        raise BatchJobError(f"payload is missing required key(s): {sorted(missing)}")
    unknown = set(payload.keys()) - (_REQUIRED_PAYLOAD_KEYS | _OPTIONAL_PAYLOAD_KEYS)
    if unknown:
        raise BatchJobError(f"payload has unknown key(s): {sorted(unknown)}")
    if not isinstance(payload["inputs"], list) or not payload["inputs"]:
        raise BatchJobError("payload['inputs'] must be a non-empty list.")


def _client(environment: str):
    try:
        import anthropic
    except ImportError as exc:
        raise BatchJobError(
            "The 'anthropic' package is required for batch processing."
        ) from exc
    from auth_accelerator import build_api_credential

    api_key = build_api_credential(environment)
    return anthropic.Anthropic(api_key=api_key)


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
    return Path(registry_path).parent / "prompts"


def _submit_with_fallback(
    client: Any, requests: list[dict[str, Any]], chain: list[str]
) -> Any:
    """Batches have no per-item fallback mid-flight -- if submission or
    processing fails outright for one model, resubmit the whole batch
    with the next model in the chain."""
    last_error: Exception | None = None
    for candidate_model in chain:
        retried_requests = [
            {**r, "params": {**r["params"], "model": candidate_model}} for r in requests
        ]
        try:
            return client.messages.batches.create(requests=retried_requests)
        except Exception as exc:  # noqa: BLE001 - any submission failure triggers fallback
            last_error = exc
            continue
    raise BatchJobError(f"Batch submission failed for every model in {chain}: {last_error}")


def execute_batch(
    payload: dict[str, Any], registry_path: Path | str | None = None
) -> dict[str, Any]:
    _validate_payload(payload)
    batch_id = payload["batch_id"]
    inputs = payload["inputs"]

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
    pm = PromptManager(prompts_dir=prompts_dir)
    prompt_file = step_config.get("prompt")
    model = step_config["model"]
    fallback = step_config.get("fallback", [])
    capabilities = {
        k: v
        for k, v in step_config.items()
        if k not in ("prompt", "model", "fallback", "system_prompt")
    }
    capabilities.pop("max_tokens", None)
    max_tokens = step_config.get("max_tokens", 1024)

    configs: dict[str, Any] = {}
    requests = []
    for i, item in enumerate(inputs):
        custom_id = f"{batch_id}-{i}"
        if prompt_file is not None:
            cfg, system_prompt, user_content = pm.render(step_name, item, filename=prompt_file)
            configs[custom_id] = cfg
        else:
            system_prompt = step_config.get("system_prompt", "You are a helpful assistant.")
            user_content = item
            configs[custom_id] = None
        requests.append(
            {
                "custom_id": custom_id,
                "params": {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}],
                    **capabilities,
                },
            }
        )

    client = _client(environment)
    batch = _submit_with_fallback(client, requests, [model] + list(fallback))

    deadline = time.monotonic() + job["poll_timeout_seconds"]
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        if time.monotonic() >= deadline:
            raise BatchJobError(
                f"Batch '{batch.id}' did not finish within "
                f"{job['poll_timeout_seconds']}s (last status: {batch.processing_status})."
            )
        time.sleep(job["poll_interval_seconds"])

    results_by_custom_id: dict[str, Any] = {}
    try:
        for entry in client.messages.batches.results(batch.id):
            results_by_custom_id[entry.custom_id] = entry
    except Exception as exc:  # noqa: BLE001
        raise BatchJobError(f"Failed to retrieve results for batch '{batch.id}': {exc}") from exc

    results = []
    for i, item in enumerate(inputs):
        custom_id = f"{batch_id}-{i}"
        entry = results_by_custom_id.get(custom_id)
        if entry is None or getattr(entry.result, "type", None) != "succeeded":
            results.append({"input": item, "output": None, "error": str(entry)})
            continue
        raw_output = entry.result.message.content[0].text
        cfg = configs[custom_id]
        try:
            output = pm.validate_output(step_name, cfg, raw_output) if cfg is not None else raw_output
            results.append({"input": item, "output": output, "error": None})
        except Exception as exc:  # noqa: BLE001
            results.append({"input": item, "output": raw_output, "error": str(exc)})

    return {"batch_id": batch_id, "results": results}

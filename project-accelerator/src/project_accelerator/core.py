"""
core.py

The master accelerator's single library entry point: execute(payload).
Composes, in order:

  1. Resolve `environment` (payload value -> .env -> "local").
  2. Resolve the (process, step) block from process_registry.yaml, falling
     back to the built-in default configuration when undefined.
  3. Call the model with fallback via claude-model-router-accelerator.
  4. Validate output against the prompt's format contract (skipped for
     the generic default configuration, which has no format contract).
  5. Log MODEL_CALL_START before the model call, MODEL_CALL_END and
     FULL_TURN after it, via orchestration_accelerator's default logging
     wrapper.

Nothing about which process/step/model/backend runs is hardcoded here --
it is entirely driven by `payload` and by process_registry.yaml. Payload
validation is plain dict-key checks, no JSON Schema (per plan Section 6).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from pathlib import Path
from typing import Any

from orchestration_accelerator.environment import (
    resolve_environment,
    resolve_trimming_strategy,
)
from orchestration_accelerator.errors import friendly_error
from orchestration_accelerator.prompting import PromptManager
from orchestration_accelerator.registry import (
    ProcessNotFoundError,
    StepNotFoundError,
    UnsupportedCapabilityError,
    get_default_step_config,
    get_process,
    resolve_session_store,
    validate_capabilities,
)
from orchestration_accelerator.trimming import should_trim
from model_router_accelerator import execute_with_fallback
from model_router_accelerator.backends import open_agent_sdk_session, run_session_turn

REQUIRED_PAYLOAD_KEYS = {"process", "input", "backend"}
OPTIONAL_PAYLOAD_KEYS = {"step", "environment", "session_id", "on_chunk"}
KNOWN_PAYLOAD_KEYS = REQUIRED_PAYLOAD_KEYS | OPTIONAL_PAYLOAD_KEYS
VALID_BACKENDS = {"agent_sdk", "messages_api"}


class PayloadValidationError(Exception):
    """Raised when execute()'s payload dict is missing a required key or
    has an invalid value -- plain dict-key checks, no JSON Schema."""


def _validate_payload(payload: dict[str, Any]) -> None:
    missing = REQUIRED_PAYLOAD_KEYS - payload.keys()
    if missing:
        raise PayloadValidationError(
            friendly_error(
                f"This request is missing required information: {sorted(missing)}.",
                f"payload is missing required key(s): {sorted(missing)}",
            )
        )
    unknown = set(payload.keys()) - KNOWN_PAYLOAD_KEYS
    if unknown:
        raise PayloadValidationError(
            friendly_error(
                f"This request includes fields that aren't recognized: "
                f"{sorted(unknown)}. Remove them or check for typos.",
                f"payload has unknown key(s): {sorted(unknown)}",
            )
        )
    if payload["backend"] not in VALID_BACKENDS:
        raise PayloadValidationError(
            friendly_error(
                f"The requested execution backend isn't supported.",
                f"payload['backend'] must be one of {sorted(VALID_BACKENDS)}, "
                f"got {payload['backend']!r}",
            )
        )


_logging_configured_from_project = False


def _ensure_project_logging_configured() -> None:
    """A scaffolded project's own logger_config.json (written by `cpa new`,
    editable to turn scopes on/off) would otherwise sit unused --
    orchestration_accelerator's logging wrapper configures itself from its
    own bundled default the first time log() is called. Load the
    project's file into that same wrapper once per process, before the
    first log() call, so editing logger_config.json actually takes
    effect. Best-effort: falls back to the wrapper's own default on any
    read/parse error, same as having no project file at all."""
    global _logging_configured_from_project
    if _logging_configured_from_project:
        return
    _logging_configured_from_project = True
    project_config_path = Path.cwd() / "logger_config.json"
    if not project_config_path.exists():
        return
    try:
        from orchestration_accelerator.logging import configure_default_logging

        configure_default_logging(json.loads(project_config_path.read_text()))
    except Exception:
        pass


def _resolve_registry_and_prompts_dir() -> tuple[Path, Path]:
    """A scaffolded project has its own process_registry.yaml/prompts/ at
    its cwd; the accelerator repo itself (for its own dev/test use) falls
    back to orchestration_accelerator's shipped sample files."""
    cwd_registry = Path.cwd() / "config" / "process_registry.yaml"
    cwd_prompts = Path.cwd() / "prompts"
    if cwd_registry.exists():
        return cwd_registry, cwd_prompts

    from orchestration_accelerator.prompting import PROMPTS_DIR
    from orchestration_accelerator.registry import DEFAULT_REGISTRY_PATH

    return DEFAULT_REGISTRY_PATH, PROMPTS_DIR


def _resolve_capability_registry_path() -> Path:
    """Same cwd-first-else-shipped-default resolution as
    _resolve_registry_and_prompts_dir(), for capability_registry.yaml."""
    cwd_capabilities = Path.cwd() / "config" / "capability_registry.yaml"
    if cwd_capabilities.exists():
        return cwd_capabilities

    from orchestration_accelerator.registry import DEFAULT_CAPABILITY_REGISTRY_PATH

    return DEFAULT_CAPABILITY_REGISTRY_PATH


def _resolve_step_configs(
    process_name: str, only_step: str | None
) -> tuple[list[tuple[str, dict]], dict[str, Any]]:
    """Returns (ordered list of (step_name, step_config) to run,
    process-level context metadata {context_mode, trimming, session_store}),
    honoring process_registry.yaml's step order. `only_step` narrows to a
    single step -- it never reorders or subsets the process's `steps`
    list beyond that one selection."""
    registry_path, _ = _resolve_registry_and_prompts_dir()
    try:
        process = get_process(process_name, path=registry_path)
    except ProcessNotFoundError:
        # Unknown process entirely -- run the single built-in default step.
        step_name = only_step or process_name
        return [(step_name, get_default_step_config())], {
            "context_mode": "threaded",
            "trimming": None,
            "session_store": None,
        }

    steps = process["steps"]
    if only_step is not None:
        if only_step not in steps:
            raise StepNotFoundError(
                friendly_error(
                    f"The requested step '{only_step}' doesn't exist for process "
                    f"'{process_name}' -- check the step name for typos, or the "
                    f"available steps are: {steps}.",
                    f"Step '{only_step}' is not part of process '{process_name}''s "
                    f"steps {steps}.",
                )
            )
        steps = [only_step]

    step_configs = [(step, process["step_config"][step]) for step in steps]
    context = {
        "context_mode": process["context_mode"],
        "trimming": process["trimming"],
        "session_store": process["session_store"],
    }
    return step_configs, context


async def _log_best_effort(scope: str, session_id: str, turn_index: int, **fields: Any) -> None:
    """Logging must never take down the pipeline itself -- a tracing
    backend outage is not the caller's problem. Used for both success
    (FULL_TURN) and failure (ERROR) events, so a run's log trace always
    has an entry for every step attempted, not just the ones that
    happened to succeed."""
    try:
        _ensure_project_logging_configured()
        from orchestration_accelerator.logging import log

        await log(scope, session_id, turn_index, **fields)
    except Exception:
        pass


async def _run_one_step(
    step_name: str,
    step_config: dict[str, Any],
    input_data: str | dict[str, Any],
    backend: str,
    environment: str,
    session_id: str,
    turn_index: int,
    prompts_dir: Path,
    on_chunk: Any | None = None,
) -> Any:
    model = step_config.get("model", "<unresolved>")
    try:
        prompt_file = step_config.get("prompt")
        model = step_config["model"]
        fallback = step_config.get("fallback", [])
        # Any other key in the step's process_registry.yaml block
        # (max_turns, thinking, temperature, top_p, permission_mode, ...)
        # passes straight through to the model call -- lets a step's
        # capabilities be tuned from config alone, no accelerator code
        # change required.
        capabilities = {
            k: v
            for k, v in step_config.items()
            if k not in ("prompt", "model", "fallback", "system_prompt")
        }
        step_on_chunk = None
        if capabilities.get("stream") and on_chunk is not None:
            async def step_on_chunk(chunk: str, _step_name: str = step_name) -> None:
                maybe_awaitable = on_chunk(_step_name, chunk)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
        if capabilities:
            validate_capabilities(
                capabilities, backend, path=_resolve_capability_registry_path()
            )

        if prompt_file is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            cfg, system_prompt, assistant_prompt, user_content = pm.render(
                step_name, input_data, filename=prompt_file
            )
        else:
            cfg = None
            assistant_prompt = None
            system_prompt = step_config.get("system_prompt", "You are a helpful assistant.")
            if not isinstance(input_data, str):
                raise TypeError(
                    friendly_error(
                        f"Step '{step_name}' expects plain text input, not "
                        f"structured fields -- this is a config/call-site "
                        f"mismatch.",
                        f"Step '{step_name}' has no prompt file, so a dict "
                        f"input has nowhere to be rendered -- pass a plain "
                        f"string.",
                    )
                )
            user_content = input_data

        if assistant_prompt is not None and backend == "agent_sdk":
            raise UnsupportedCapabilityError(
                friendly_error(
                    f"Step '{step_name}' declares an assistant_prompt seed "
                    f"turn, which only works with backend: messages_api.",
                    f"assistant_prompt + backend='agent_sdk' is unsupported -- "
                    f"claude_agent_sdk's query() takes a single string prompt, "
                    f"not a message array, so there is no way to seed a prior "
                    f"assistant turn before the first real query call. Switch "
                    f"this step to backend: messages_api, or remove "
                    f"assistant_prompt from its prompt YAML.",
                )
            )

        await _log_best_effort(
            "MODEL_CALL_START",
            session_id,
            turn_index,
            model=model,
            payload={
                "step": step_name,
                "input": input_data,
                "system_prompt": system_prompt,
                "assistant_prompt": assistant_prompt,
                "user_content": user_content,
                "fallback": fallback,
                "capabilities": capabilities,
            },
        )

        call_result = await execute_with_fallback(
            model=model,
            fallback=fallback,
            system_prompt=system_prompt,
            assistant_prompt=assistant_prompt,
            user_content=user_content,
            backend=backend,
            environment=environment,
            session_id=session_id,
            on_chunk=step_on_chunk,
            **capabilities,
        )
        raw_output = call_result["text"]

        await _log_best_effort(
            "MODEL_CALL_END",
            session_id,
            turn_index,
            model=call_result["model_used"],
            latency_ms=call_result["latency_ms"],
            payload={"step": step_name, "output": raw_output},
            metadata={
                "usage": call_result["usage"],
                "stop_reason": call_result["stop_reason"],
                "request_id": call_result["request_id"],
                "tool_calls": call_result["tool_calls"],
                "session_id": call_result["session_id"],
            },
        )

        await _log_best_effort(
            "FULL_TURN",
            session_id,
            turn_index,
            model=call_result["model_used"],
            payload={"step": step_name, "input": input_data, "output": raw_output},
        )

        validated_output = raw_output
        if cfg is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            validated_output = pm.validate_output(step_name, cfg, raw_output)

        return {
            "output": validated_output,
            "model_used": call_result["model_used"],
            "stop_reason": call_result["stop_reason"],
            "usage": call_result["usage"],
            "tool_calls": call_result["tool_calls"],
            "request_id": call_result["request_id"],
            "latency_ms": call_result["latency_ms"],
            "session_id": call_result["session_id"],
        }
    except Exception as exc:
        # Every failure path (bad capability config, prompt render/
        # validation, the model call itself, or output-contract
        # validation) gets an ERROR-scope log entry, same as a
        # successful step gets a FULL_TURN entry -- a run's trace should
        # never go silent just because that particular turn failed.
        await _log_best_effort(
            "ERROR",
            session_id,
            turn_index,
            model=model,
            payload={
                "step": step_name,
                "input": input_data,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise


async def _run_session_step(
    client: Any,
    step_name: str,
    step_config: dict[str, Any],
    input_data: str | dict[str, Any],
    session_id: str,
    turn_index: int,
    prompts_dir: Path,
    claude_session_id: str | None = None,
) -> Any:
    """context_mode: session counterpart to _run_one_step() -- runs one
    step's turn on an already-open ClaudeSDKClient (see
    open_agent_sdk_session()/run_session_turn()) instead of a fresh
    stateless call. Returns the same structured-result shape as
    _run_one_step(), so results[step_name] is uniform regardless of
    context_mode."""
    model = step_config.get("model", "<unresolved>")
    try:
        prompt_file = step_config.get("prompt")
        model = step_config["model"]

        if prompt_file is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            cfg, system_prompt, _assistant_prompt, user_content = pm.render(
                step_name, input_data, filename=prompt_file
            )
        else:
            cfg = None
            system_prompt = step_config.get("system_prompt", "You are a helpful assistant.")
            if not isinstance(input_data, str):
                raise TypeError(
                    friendly_error(
                        f"Step '{step_name}' expects plain text input, not "
                        f"structured fields -- this is a config/call-site "
                        f"mismatch.",
                        f"Step '{step_name}' has no prompt file, so a dict "
                        f"input has nowhere to be rendered -- pass a plain "
                        f"string.",
                    )
                )
            user_content = input_data

        await _log_best_effort(
            "MODEL_CALL_START",
            session_id,
            turn_index,
            model=model,
            payload={"step": step_name, "input": input_data, "user_content": user_content},
            metadata={"claude_session_id": claude_session_id} if claude_session_id else {},
        )

        async def _on_mirror_error(error: str, key: Any) -> None:
            await _log_best_effort(
                "WARNING",
                session_id,
                turn_index,
                payload={"step": step_name, "mirror_error": error, "key": str(key)},
                metadata={"claude_session_id": claude_session_id} if claude_session_id else {},
            )

        call_result = await run_session_turn(client, user_content, model, _on_mirror_error)
        raw_output = call_result["text"]

        await _log_best_effort(
            "MODEL_CALL_END",
            session_id,
            turn_index,
            model=call_result["model_used"],
            latency_ms=call_result["latency_ms"],
            payload={"step": step_name, "output": raw_output},
            metadata={
                "usage": call_result["usage"],
                "stop_reason": call_result["stop_reason"],
                "request_id": call_result["request_id"],
                "tool_calls": call_result["tool_calls"],
                "session_id": call_result["session_id"],
                "claude_session_id": call_result["session_id"],
            },
        )

        await _log_best_effort(
            "FULL_TURN",
            session_id,
            turn_index,
            model=call_result["model_used"],
            payload={"step": step_name, "input": input_data, "output": raw_output},
            metadata={"claude_session_id": call_result["session_id"]},
        )

        validated_output = raw_output
        if cfg is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            validated_output = pm.validate_output(step_name, cfg, raw_output)

        return {
            "output": validated_output,
            "model_used": call_result["model_used"],
            "stop_reason": call_result["stop_reason"],
            "usage": call_result["usage"],
            "tool_calls": call_result["tool_calls"],
            "request_id": call_result["request_id"],
            "latency_ms": call_result["latency_ms"],
            "session_id": call_result["session_id"],
        }
    except Exception as exc:
        await _log_best_effort(
            "ERROR",
            session_id,
            turn_index,
            model=model,
            payload={
                "step": step_name,
                "input": input_data,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            metadata={"claude_session_id": claude_session_id} if claude_session_id else {},
        )
        raise


async def _execute_session_mode(
    payload: dict[str, Any],
    process_name: str,
    steps_to_run: list[tuple[str, dict[str, Any]]],
    context: dict[str, Any],
    backend: str,
    environment: str,
    input_data: str | dict[str, Any],
    session_id: str,
    prompts_dir: Path,
) -> dict[str, Any]:
    """context_mode: session execution path -- opens one ClaudeSDKClient
    for the whole call (or resumes one via payload["session_id"] for
    cross-call continuation), runs every step's turn on that same open
    client in order, applies trimming between turns, then closes the
    client and returns results with the client's own session_id attached
    to every step (decision 4/5/6 in the plan)."""
    if backend != "agent_sdk":
        raise UnsupportedCapabilityError(
            friendly_error(
                f"Process '{process_name}' uses context_mode: session, which "
                f"only works with the agent_sdk backend -- messages_api has "
                f"no native session concept.",
                f"context_mode: session + backend={backend!r} is unsupported. "
                f"Set backend to 'agent_sdk', or switch this process to "
                f"context_mode: threaded (the default) to use messages_api.",
            )
        )

    trimming_cfg = context.get("trimming") or {}
    trimming_strategy = trimming_cfg.get("strategy") or resolve_trimming_strategy()
    resolved_store = resolve_session_store(context.get("session_store"))
    resume = payload.get("session_id")

    first_step_name, first_step_config = steps_to_run[0]
    first_model = first_step_config.get("model", "claude-sonnet-5")
    first_system_prompt = first_step_config.get("system_prompt", "You are a helpful assistant.")
    if first_step_config.get("prompt") is not None:
        pm = PromptManager(prompts_dir=prompts_dir)
        _, first_system_prompt, _, _ = pm.render(
            first_step_name, input_data, filename=first_step_config["prompt"]
        )

    client = await open_agent_sdk_session(
        model=first_model,
        system_prompt=first_system_prompt,
        environment=environment,
        max_turns=first_step_config.get("max_turns", 1),
        resume=resume,
        session_store=resolved_store,
    )

    # Tracks the real claude_agent_sdk conversation id, distinct from
    # `session_id` above (a fresh trace-correlation id per execute() call,
    # see .claude/rules/context-mode.md). Seeded from `resume` when this
    # call is itself continuing an earlier conversation; otherwise known
    # only once the first turn's result comes back.
    claude_session_id: str | None = resume

    results: dict[str, Any] = {}
    try:
        for turn_index, (step_name, step_config) in enumerate(steps_to_run):
            decision = should_trim(trimming_strategy, turn_index, trimming_cfg)
            if decision.should_rotate:
                await client.disconnect()
                client = await open_agent_sdk_session(
                    model=step_config.get("model", first_model),
                    system_prompt=decision.summary,
                    environment=environment,
                    max_turns=step_config.get("max_turns", 1),
                    resume=None,
                    session_store=resolved_store,
                )
                claude_session_id = None

            results[step_name] = await _run_session_step(
                client,
                step_name,
                step_config,
                input_data,
                session_id,
                turn_index,
                prompts_dir,
                claude_session_id,
            )
            claude_session_id = results[step_name]["session_id"]
    finally:
        await client.disconnect()

    return results


async def _execute_async(payload: dict[str, Any]) -> dict[str, Any]:
    # A fresh session_id up front means even a failure before any step
    # runs (bad payload shape, unknown process/step) still gets one
    # ERROR-scope log entry -- the log trace is never silent just
    # because the run never made it as far as a model call.
    session_id = str(uuid.uuid4())
    try:
        _validate_payload(payload)

        process_name = payload["process"]
        only_step = payload.get("step")
        input_data = payload["input"]
        backend = payload["backend"]
        environment = resolve_environment(payload.get("environment"))

        _, prompts_dir = _resolve_registry_and_prompts_dir()
        steps_to_run, context = _resolve_step_configs(process_name, only_step)
    except Exception as exc:
        await _log_best_effort(
            "ERROR",
            session_id,
            0,
            payload={
                "payload": payload,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise

    if context["context_mode"] == "session":
        return await _execute_session_mode(
            payload,
            process_name,
            steps_to_run,
            context,
            backend,
            environment,
            input_data,
            session_id,
            prompts_dir,
        )

    results: dict[str, Any] = {}
    for turn_index, (step_name, step_config) in enumerate(steps_to_run):
        # Prior steps' outputs are made available to later steps as
        # `{{<step>_output}}` placeholders, alongside `{{input}}` -- a
        # step's prompt YAML opts in by declaring the placeholders it
        # needs (see PromptManager.render()). Steps with no placeholders
        # (the legacy plain-string path, e.g. onboarding's `verify`)
        # must keep receiving the raw input_data unchanged -- render()
        # rejects a dict input outright when a step declares zero
        # placeholders, so that check is mirrored here up front via
        # has_placeholders() rather than always building a dict.
        step_input: str | dict[str, Any] = input_data
        prompt_file = step_config.get("prompt")
        if results and prompt_file is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            if pm.has_placeholders(step_name, filename=prompt_file):
                # A dict input_data (templatingDemo-style, multi-field
                # placeholders) keeps its original named fields untouched --
                # collapsing them into a single "input" key would strand a
                # later step that also needs those original fields (e.g.
                # `escalate` needing the same dossier fields `triage` used).
                step_input = (
                    dict(input_data) if isinstance(input_data, dict) else {"input": input_data}
                )
                step_input.update(
                    {f"{name}_output": out["output"] for name, out in results.items()}
                )

        results[step_name] = await _run_one_step(
            step_name,
            step_config,
            step_input,
            backend,
            environment,
            session_id,
            turn_index,
            prompts_dir,
            payload.get("on_chunk"),
        )

    return results


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """The master accelerator's single entry point. Returns
    {step_name: {output, model_used, stop_reason, usage, tool_calls,
    request_id, latency_ms, session_id}, ...} for every step run -- one
    entry when payload['step'] narrows to a single step, otherwise one
    entry per step in process_registry.yaml's `steps` order.

    `output` carries what earlier versions of this function returned
    directly as `results[step_name]` (a bare string) -- callers written
    against that older contract must switch to
    `results[step_name]["output"]`. `tool_calls`/`session_id` are
    agent_sdk-only (empty list / `None` on messages_api); `request_id`
    is messages_api-only (`None` on agent_sdk).

    Optional payload keys: `step` (narrow to one step), `environment`,
    `session_id` (cross-call resume for a context_mode: session process
    -- see .claude/rules/context-mode.md), `on_chunk` (sync or async
    `(step_name: str, chunk: str) -> None` callback invoked per chunk
    for any step with `stream: true` -- see .claude/rules/streaming.md;
    ignored for steps without `stream: true`, and safe to omit even when
    a step does have it)."""
    return asyncio.run(_execute_async(payload))

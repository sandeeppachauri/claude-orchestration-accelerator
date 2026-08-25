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
import json
import uuid
from pathlib import Path
from typing import Any

from orchestration_accelerator.environment import resolve_environment
from orchestration_accelerator.errors import friendly_error
from orchestration_accelerator.prompting import PromptManager
from orchestration_accelerator.registry import (
    ProcessNotFoundError,
    StepNotFoundError,
    get_default_step_config,
    get_process,
    validate_capabilities,
)
from model_router_accelerator import execute_with_fallback

REQUIRED_PAYLOAD_KEYS = {"process", "input", "backend"}
OPTIONAL_PAYLOAD_KEYS = {"step", "environment"}
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


def _resolve_step_configs(process_name: str, only_step: str | None) -> list[tuple[str, dict]]:
    """Returns an ordered list of (step_name, step_config) to run, honoring
    process_registry.yaml's step order. `only_step` narrows to a single
    step -- it never reorders or subsets the process's `steps` list beyond
    that one selection."""
    registry_path, _ = _resolve_registry_and_prompts_dir()
    try:
        process = get_process(process_name, path=registry_path)
    except ProcessNotFoundError:
        # Unknown process entirely -- run the single built-in default step.
        step_name = only_step or process_name
        return [(step_name, get_default_step_config())]

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

    return [(step, process["step_config"][step]) for step in steps]


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
        if capabilities:
            validate_capabilities(
                capabilities, backend, path=_resolve_capability_registry_path()
            )

        if prompt_file is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            cfg, system_prompt, user_content = pm.render(
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
            payload={
                "step": step_name,
                "input": input_data,
                "system_prompt": system_prompt,
                "user_content": user_content,
                "fallback": fallback,
                "capabilities": capabilities,
            },
        )

        raw_output = await execute_with_fallback(
            model=model,
            fallback=fallback,
            system_prompt=system_prompt,
            user_content=user_content,
            backend=backend,
            environment=environment,
            **capabilities,
        )

        await _log_best_effort(
            "MODEL_CALL_END",
            session_id,
            turn_index,
            model=model,
            payload={"step": step_name, "output": raw_output},
        )

        await _log_best_effort(
            "FULL_TURN",
            session_id,
            turn_index,
            model=model,
            payload={"step": step_name, "input": input_data, "output": raw_output},
        )

        if cfg is not None:
            pm = PromptManager(prompts_dir=prompts_dir)
            return pm.validate_output(step_name, cfg, raw_output)
        return raw_output
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
        steps_to_run = _resolve_step_configs(process_name, only_step)
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
                step_input = {"input": input_data}
                step_input.update({f"{name}_output": out for name, out in results.items()})

        results[step_name] = await _run_one_step(
            step_name,
            step_config,
            step_input,
            backend,
            environment,
            session_id,
            turn_index,
            prompts_dir,
        )

    return results


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """The master accelerator's single entry point. Returns
    {step_name: validated_output, ...} for every step run -- one entry
    when payload['step'] narrows to a single step, otherwise one entry
    per step in process_registry.yaml's `steps` order."""
    return asyncio.run(_execute_async(payload))

"""
registry.py

Loads process_registry.yaml and resolves (process, step) lookups. This is
the single source of truth for a process's step order and each step's
{prompt, model, fallback} configuration -- see Master_Accelerator_Plan.md
Section 4.1.

Nothing here assumes a fixed step count or fixed step names: `steps` is
read as a plain list and iterated as-is, for however many entries it has.

If a (process, step) pair is looked up but not defined, callers fall back
to `get_default_step_config()` -- one model (from the environment's
DEFAULT_MODEL) and one generic, non-process-specific system prompt, with
no fallback chain. This is a safety net, not a substitute for actually
defining a process in process_registry.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from orchestration_accelerator.errors import friendly_error

# Ships at the orchestration_accelerator package root -- also the default
# file every scaffolded project starts with (claude-project-accelerator's
# scaffold command copies this same file).
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "process_registry.yaml"
)

# Same tier/shipping story as DEFAULT_REGISTRY_PATH above -- see
# capability_registry.yaml's own header comment for why this lives here
# rather than in .env.
DEFAULT_CAPABILITY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "capability_registry.yaml"
)

_RESERVED_KEYS = {"id", "description", "steps", "context_mode", "trimming", "session_store"}

VALID_CONTEXT_MODES = {"threaded", "session"}

_GENERIC_DEFAULT_SYSTEM_PROMPT = (
    "You are a general-purpose assistant step running inside the "
    "claude-orchestration-accelerator stack. No specific prompt "
    "configuration was found for this (process, step) pair in "
    "process_registry.yaml, so you are running on the accelerator's "
    "built-in default configuration: respond helpfully and concisely to "
    "the input you are given, with no process-specific scope, format, or "
    "constraints in force."
)


class ProcessNotFoundError(Exception):
    """Raised when a requested process name has no block in process_registry.yaml."""


class StepNotFoundError(Exception):
    """Raised when a requested step name isn't in a process's `steps` list."""


class UnsupportedCapabilityError(Exception):
    """Raised when a step's process_registry.yaml block passes a
    capability key not whitelisted for the chosen backend in
    capability_registry.yaml -- raised before the model call, instead of
    a TypeError several layers deep inside the SDK/API client."""


class InvalidContextModeError(Exception):
    """Raised at process-load time when a process's `context_mode` key
    is present but not one of VALID_CONTEXT_MODES."""


class SessionStoreResolutionError(Exception):
    """Raised when a process's `session_store.backend` can't be resolved
    -- an unknown backend name, a `custom` backend with no/bad `factory`,
    or one of the documented copy-in-yourself backends (s3/redis/postgres)
    with no adapter actually installed."""


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def get_process(
    process: str, path: Path | str = DEFAULT_REGISTRY_PATH
) -> dict[str, Any]:
    """Returns {id, description, steps, step_config} for a process, where
    step_config is {step_name: {prompt, model, fallback}, ...} for every
    name in `steps`."""
    registry = load_registry(path)
    if process not in registry:
        raise ProcessNotFoundError(
            friendly_error(
                f"The process '{process}' doesn't exist -- check the process "
                f"name in your request for typos, or add it to process_registry.yaml.",
                f"No process '{process}' defined in {path}. Known processes: "
                f"{sorted(registry.keys())}",
            )
        )

    block = registry[process]
    context_mode = block.get("context_mode", "threaded")
    if context_mode not in VALID_CONTEXT_MODES:
        raise InvalidContextModeError(
            friendly_error(
                f"Process '{process}' has an invalid context_mode setting -- "
                f"this needs a config fix.",
                f"Process '{process}' has context_mode={context_mode!r}, must "
                f"be one of {sorted(VALID_CONTEXT_MODES)}.",
            )
        )

    steps: list[str] = list(block.get("steps", []))
    step_config: dict[str, Any] = {}
    for step_name in steps:
        if step_name not in block:
            raise StepNotFoundError(
                friendly_error(
                    f"Process '{process}' is misconfigured -- step '{step_name}' is "
                    f"listed as part of the workflow but has no settings defined "
                    f"for it. This needs a config fix, not a retry.",
                    f"Process '{process}' lists step '{step_name}' in `steps` "
                    f"but has no matching config block for it.",
                )
            )
        step_config[step_name] = block[step_name]

    return {
        "id": block.get("id"),
        "description": block.get("description"),
        "steps": steps,
        "step_config": step_config,
        "context_mode": context_mode,
        "trimming": block.get("trimming"),
        "session_store": block.get("session_store"),
    }


def get_process_by_id(
    process_id: str, path: Path | str = DEFAULT_REGISTRY_PATH
) -> tuple[str, dict[str, Any]]:
    """Reverse lookup: batch_registry.yaml references a process's `id`
    field, not its top-level key name, so batch job resolution needs to
    go id -> (process_name, block). Returns (process_name, block) for the
    first process whose `id` matches."""
    registry = load_registry(path)
    for process_name, block in registry.items():
        if isinstance(block, dict) and block.get("id") == process_id:
            return process_name, block
    raise ProcessNotFoundError(
        friendly_error(
            f"No process is registered with id '{process_id}' -- check the "
            f"batch job's `process` value against each process's `id` field "
            f"in process_registry.yaml (not its top-level key name).",
            f"No process with id '{process_id}' defined in {path}. Known ids: "
            f"{sorted(b.get('id') for b in registry.values() if isinstance(b, dict))}",
        )
    )


def get_allowed_capabilities(
    backend: str, path: Path | str = DEFAULT_CAPABILITY_REGISTRY_PATH
) -> set[str]:
    """Returns the set of capability keys whitelisted for `backend` in
    capability_registry.yaml. An unlisted/missing backend section yields
    an empty set (i.e. no capability passthrough allowed), not an error
    -- a process_registry.yaml step that sets any capability key against
    a backend absent from this file will always fail validation, making
    the missing whitelist entry immediately visible rather than silently
    permissive."""
    registry = load_registry(path)
    section = registry.get(backend) or {}
    return set(section.get("allowed", []))


def validate_capabilities(
    capabilities: dict[str, Any],
    backend: str,
    path: Path | str = DEFAULT_CAPABILITY_REGISTRY_PATH,
) -> None:
    """Raises UnsupportedCapabilityError if `capabilities` contains any
    key not whitelisted for `backend` in capability_registry.yaml."""
    allowed = get_allowed_capabilities(backend, path=path)
    unsupported = capabilities.keys() - allowed
    if unsupported:
        raise UnsupportedCapabilityError(
            friendly_error(
                f"This step's config uses a setting that isn't supported for "
                f"how it's being run ({backend}) -- either remove that "
                f"setting from process_registry.yaml, or switch to a backend "
                f"that supports it.",
                f"Capability key(s) {sorted(unsupported)} are not whitelisted "
                f"for backend '{backend}' in {path}. Allowed for '{backend}': "
                f"{sorted(allowed)}. Add the key to capability_registry.yaml's "
                f"'{backend}' section once that backend actually supports it.",
            )
        )


_COPY_IN_YOURSELF_BACKENDS = {"s3", "redis", "postgres"}


def resolve_session_store(session_store_config: dict[str, Any] | None) -> Any | None:
    """Resolves a process's `session_store` block (see
    .claude/rules/context-mode.md) to a claude_agent_sdk SessionStore-
    conforming object, or None if the process has no session_store
    configured (context_mode: session then behaves exactly like today --
    local-disk-only transcript, no cross-host resume).

    - backend: "memory" -> claude_agent_sdk's built-in InMemorySessionStore.
    - backend: "custom" -> imports and calls the zero-arg callable named
      by `factory` ("dotted.path:callable_name").
    - backend: "s3" | "redis" | "postgres" -> these are NOT vendored into
      this repo (avoids forcing aws-sdk/ioredis/pg as dependencies on
      every user) -- raises SessionStoreResolutionError pointing at
      .claude/rules/context-mode.md's copy-in-yourself workflow, not an
      ImportError deep in a missing dependency.
    - any other backend name -> SessionStoreResolutionError.
    """
    if session_store_config is None:
        return None

    backend = session_store_config.get("backend")
    if backend == "memory":
        from claude_agent_sdk import InMemorySessionStore

        return InMemorySessionStore()

    if backend == "custom":
        factory = session_store_config.get("factory")
        if not factory or ":" not in factory:
            raise SessionStoreResolutionError(
                friendly_error(
                    "This process's session_store config is missing a valid "
                    "factory setting.",
                    f"session_store.backend == 'custom' requires a "
                    f"'factory' value shaped 'dotted.module.path:callable_name', "
                    f"got {factory!r}.",
                )
            )
        module_path, _, callable_name = factory.partition(":")
        import importlib

        module = importlib.import_module(module_path)
        try:
            build = getattr(module, callable_name)
        except AttributeError as exc:
            raise SessionStoreResolutionError(
                friendly_error(
                    "This process's session_store factory couldn't be found.",
                    f"No callable {callable_name!r} in module {module_path!r} "
                    f"(session_store.factory={factory!r}).",
                )
            ) from exc
        return build()

    if backend in _COPY_IN_YOURSELF_BACKENDS:
        raise SessionStoreResolutionError(
            friendly_error(
                f"This process wants a '{backend}' session store, but that "
                f"isn't built into this accelerator -- it needs a one-time "
                f"setup step.",
                f"session_store.backend == {backend!r} has no adapter shipped "
                f"in this repo (avoids forcing aws-sdk/ioredis/pg as "
                f"dependencies on every user). Copy the matching reference "
                f"adapter from "
                f"https://github.com/anthropics/claude-agent-sdk-typescript/"
                f"tree/main/examples/session-stores/ into this project, then "
                f"wire it via session_store: {{backend: custom, factory: "
                f"'your.module:build_store'}}. See "
                f".claude/rules/context-mode.md.",
            )
        )

    raise SessionStoreResolutionError(
        friendly_error(
            f"This process's session_store config uses an unrecognized "
            f"backend.",
            f"Unknown session_store.backend {backend!r}. Must be one of "
            f"'memory', 'custom', {sorted(_COPY_IN_YOURSELF_BACKENDS)}.",
        )
    )


def get_default_step_config(environment: str | None = None) -> dict[str, Any]:
    """The built-in default configuration fallback (plan 4.1): one model
    from DEFAULT_MODEL in .env (or 'claude-sonnet-5' if unset), one
    generic system prompt, no fallback chain. Used when a (process, step)
    pair isn't defined in process_registry.yaml."""
    default_model = os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")
    return {
        "prompt": None,
        "system_prompt": _GENERIC_DEFAULT_SYSTEM_PROMPT,
        "model": default_model,
        "fallback": [],
    }

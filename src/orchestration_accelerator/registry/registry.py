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

# Ships at the orchestration_accelerator package root -- also the default
# file every scaffolded project starts with (claude-project-accelerator's
# scaffold command copies this same file).
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "process_registry.yaml"

_RESERVED_KEYS = {"id", "description", "steps"}

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
            f"No process '{process}' defined in {path}. Known processes: "
            f"{sorted(registry.keys())}"
        )

    block = registry[process]
    steps: list[str] = list(block.get("steps", []))
    step_config: dict[str, Any] = {}
    for step_name in steps:
        if step_name not in block:
            raise StepNotFoundError(
                f"Process '{process}' lists step '{step_name}' in `steps` "
                f"but has no matching config block for it."
            )
        step_config[step_name] = block[step_name]

    return {
        "id": block.get("id"),
        "description": block.get("description"),
        "steps": steps,
        "step_config": step_config,
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
        f"No process with id '{process_id}' defined in {path}. Known ids: "
        f"{sorted(b.get('id') for b in registry.values() if isinstance(b, dict))}"
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

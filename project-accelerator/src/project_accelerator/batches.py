"""
batches.py

Thin project-level wrapper over orchestration_accelerator.batch,
mirroring execute()'s cwd-first registry resolution (core.py's
_resolve_registry_and_prompts_dir): a scaffolded project has its own
process_registry.yaml/batch_registry.yaml/prompts/ at its cwd; the
accelerator repo itself falls back to the shipped sample files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration_accelerator.batch import cancel_batch as _cancel_batch
from orchestration_accelerator.batch import collect_batch as _collect_batch
from orchestration_accelerator.batch import execute_batch as _execute_batch
from orchestration_accelerator.batch import get_batch_status as _get_batch_status
from orchestration_accelerator.batch import resubmit_failed as _resubmit_failed
from orchestration_accelerator.batch import submit_batch as _submit_batch

__all__ = [
    "cancel_batch",
    "collect_batch",
    "execute_batch",
    "get_batch_status",
    "resubmit_failed",
    "submit_batch",
]


def _resolve_registry_path() -> Path:
    """cwd-first resolution for process_registry.yaml, same as
    core.py's _resolve_project_config_path() -- always returns a real
    path (never None), so orchestration_accelerator.batch's downstream
    `Path(registry_path).parent / "batch_registry.yaml"` derivation
    never falls through to DEFAULT_BATCH_REGISTRY_PATH's fragile
    install-location-relative default."""
    cwd_registry = Path.cwd() / "config" / "process_registry.yaml"
    if cwd_registry.exists():
        return cwd_registry

    from orchestration_accelerator.registry import DEFAULT_REGISTRY_PATH

    return DEFAULT_REGISTRY_PATH


def execute_batch(payload: dict[str, Any]) -> dict[str, Any]:
    return _execute_batch(payload, registry_path=_resolve_registry_path())


def submit_batch(payload: dict[str, Any]) -> dict[str, Any]:
    return _submit_batch(payload, registry_path=_resolve_registry_path())


def get_batch_status(handle: dict[str, Any]) -> dict[str, Any]:
    return _get_batch_status(handle, registry_path=_resolve_registry_path())


def collect_batch(handle: dict[str, Any]) -> dict[str, Any]:
    return _collect_batch(handle, registry_path=_resolve_registry_path())


def cancel_batch(handle: dict[str, Any]) -> dict[str, Any]:
    return _cancel_batch(handle)


def resubmit_failed(handle: dict[str, Any], batch_result: dict[str, Any]) -> dict[str, Any] | None:
    return _resubmit_failed(handle, batch_result, registry_path=_resolve_registry_path())

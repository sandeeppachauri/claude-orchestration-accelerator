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

from orchestration_accelerator.batch import execute_batch as _execute_batch

__all__ = ["execute_batch"]


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

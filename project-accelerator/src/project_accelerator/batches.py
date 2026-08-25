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


def _resolve_registry_path() -> Path | None:
    cwd_registry = Path.cwd() / "config" / "process_registry.yaml"
    if cwd_registry.exists():
        return cwd_registry
    return None


def execute_batch(payload: dict[str, Any]) -> dict[str, Any]:
    return _execute_batch(payload, registry_path=_resolve_registry_path())

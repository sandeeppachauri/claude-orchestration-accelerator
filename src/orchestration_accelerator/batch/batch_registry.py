"""
batch_registry.py

Loads batch_registry.yaml -- the batch-processing counterpart to
registry.py. Each entry is keyed by a friendly name and carries a
`batch_id`, a foreign key `process` pointing at a process_registry.yaml
`id` field (not the process's top-level key), an optional `step` to
narrow to (same rule as execute()'s payload: never reorders/subsets
beyond one selection), and batch-specific settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_BATCH_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "batch_registry.yaml"
)

_DEFAULT_POLL_INTERVAL_SECONDS = 5
_DEFAULT_POLL_TIMEOUT_SECONDS = 3600


class BatchJobNotFoundError(Exception):
    """Raised when a requested batch_id has no block in batch_registry.yaml."""


def load_batch_registry(path: Path | str = DEFAULT_BATCH_REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def get_batch_job(
    batch_id: str, path: Path | str = DEFAULT_BATCH_REGISTRY_PATH
) -> dict[str, Any]:
    """Returns {id, process_id, step, environment, poll_interval_seconds,
    poll_timeout_seconds} for the entry whose `batch_id` matches."""
    registry = load_batch_registry(path)
    for block in registry.values():
        if isinstance(block, dict) and block.get("batch_id") == batch_id:
            return {
                "id": block["batch_id"],
                "process_id": block["process"],
                "step": block.get("step"),
                "environment": block.get("environment"),
                "poll_interval_seconds": block.get(
                    "poll_interval_seconds", _DEFAULT_POLL_INTERVAL_SECONDS
                ),
                "poll_timeout_seconds": block.get(
                    "poll_timeout_seconds", _DEFAULT_POLL_TIMEOUT_SECONDS
                ),
            }
    raise BatchJobNotFoundError(
        f"No batch job with batch_id '{batch_id}' defined in {path}. Known "
        f"batch_ids: {sorted(b.get('batch_id') for b in registry.values() if isinstance(b, dict))}"
    )

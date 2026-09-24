"""
batch_handle.py

BatchHandle/BatchResult shapes -- plain dicts, JSON-serializable, no
dataclass/pydantic dependency, matching the rest of this accelerator's
config-driven, no-schema-library style. Helper constructors only; callers
treat both as plain dicts.
"""

from __future__ import annotations

import time
from typing import Any

HANDLE_VERSION = 1


def make_batch_handle(
    *,
    batch_job: str,
    provider_batch_ids: list[str],
    process_id: str,
    step: str,
    model: str,
    fallback_remaining: list[str],
    prompt_file: str | None,
    prompt_version: str | None,
    environment: str,
    custom_ids: list[str],
    correlation: dict[str, Any] | None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Builds the JSON-serializable dict submit_batch() returns. The
    caller persists this (directly, or via a BatchStateStore -- see
    batch_state_store.py) and passes it back into get_batch_status()/
    collect_batch()/cancel_batch()/resubmit_failed()."""
    return {
        "handle_version": HANDLE_VERSION,
        "batch_job": batch_job,
        "provider_batch_ids": provider_batch_ids,
        "process_id": process_id,
        "step": step,
        "model": model,
        "fallback_remaining": fallback_remaining,
        "prompt_file": prompt_file,
        "prompt_version": prompt_version,
        "environment": environment,
        "custom_ids": custom_ids,
        "correlation": correlation or {},
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expires_at": expires_at,
    }


def make_batch_result(
    *,
    batch_job: str,
    provider_batch_ids: list[str],
    status: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Builds the BatchResult dict collect_batch() returns. `totals` is
    computed here from `results`' per-item `usage`/`status` -- the single
    place this rollup happens, so submit/collect/resubmit all see the
    same aggregation logic."""
    totals = {
        "succeeded": 0,
        "errored": 0,
        "expired": 0,
        "canceled": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    for item in results:
        item_status = item.get("status")
        if item_status in totals:
            totals[item_status] += 1
        usage = item.get("usage") or {}
        for key in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"):
            totals[key] += usage.get(key) or 0

    return {
        "batch_job": batch_job,
        "provider_batch_ids": provider_batch_ids,
        "status": status,
        "totals": totals,
        "results": results,
    }

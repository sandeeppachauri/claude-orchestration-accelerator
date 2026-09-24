"""
batch_state_store.py

BatchStateStore protocol + built-in resolvers -- the batch counterpart to
orchestration_accelerator.registry.resolve_session_store() (see
.claude/rules/context-mode.md's session_store section for the mirrored
pattern). A batch_registry.yaml entry opts in via a `state_store` block:

    state_store:
      backend: file            # "none" (default) | "file" | "custom"
      path: .batch_state       # only meaningful for backend: file
      # factory: "myproject.stores:build_batch_state_store"  # backend: custom

"none" (the default, including when `state_store` is omitted entirely)
means the caller is responsible for persisting the BatchHandle
submit_batch() returns themselves -- this accelerator does nothing extra.
"file" is a JSON-on-disk store, mostly useful for local dev/single-host
setups. "custom" imports and calls a zero-arg factory callable, the exact
same escape hatch shape as session_store's `custom` backend -- this is
how a project plugs in a durable, cross-host store (e.g. CMN's MySQL
table) without this accelerator vendoring a database driver.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class BatchStateStoreResolutionError(Exception):
    """Raised when a batch_registry.yaml `state_store` block names an
    unknown backend, or `backend: custom` is missing/has an invalid
    `factory`."""


class BatchStateStore(Protocol):
    """Minimal persistence surface a batch handle store must provide.
    `handle` is always the JSON-serializable dict submit_batch() returns
    (see batch_handle.py's BatchHandle) -- this protocol never assumes an
    ORM/dataclass shape, only plain dict I/O, so a project's own adapter
    (e.g. a MySQL-backed one) can stay a thin dict<->row mapping."""

    def save(self, handle: dict[str, Any]) -> None:
        """Persists `handle`, keyed by its own `batch_job`+`provider_batch_ids`
        (the caller looks it up again by round-tripping the same handle
        dict, not by a separate id -- see load())."""
        ...

    def load(self, batch_job: str, provider_batch_ids: list[str]) -> dict[str, Any] | None:
        """Returns the previously-saved handle dict for this
        (batch_job, provider_batch_ids) pair, or None if not found."""
        ...

    def mark_collected(self, batch_job: str, provider_batch_ids: list[str]) -> None:
        """Records that collect_batch() has already retrieved this
        handle's results -- lets a caller's own polling loop check
        list_open() without re-collecting an already-finished batch."""
        ...

    def list_open(self) -> list[dict[str, Any]]:
        """Returns every saved handle not yet marked collected -- lets a
        caller recover after a process restart without tracking handles
        itself."""
        ...


class _NoneStateStore:
    """Default: this accelerator does not persist anything. The caller
    owns the BatchHandle dict submit_batch() returns."""

    def save(self, handle: dict[str, Any]) -> None:
        pass

    def load(self, batch_job: str, provider_batch_ids: list[str]) -> dict[str, Any] | None:
        return None

    def mark_collected(self, batch_job: str, provider_batch_ids: list[str]) -> None:
        pass

    def list_open(self) -> list[dict[str, Any]]:
        return []


def _handle_key(batch_job: str, provider_batch_ids: list[str]) -> str:
    return f"{batch_job}:{','.join(sorted(provider_batch_ids))}"


class _FileStateStore:
    """JSON-on-disk store -- one file, a dict keyed by
    `_handle_key(batch_job, provider_batch_ids)`. Mostly useful for local
    dev/testing or a single-host deployment; not safe for concurrent
    writers across processes (no file locking)."""

    def __init__(self, path: Path | str = ".batch_state/handles.json"):
        self.path = Path(path)

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text()) or {}

    def _write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def save(self, handle: dict[str, Any]) -> None:
        data = self._read_all()
        key = _handle_key(handle["batch_job"], handle["provider_batch_ids"])
        data[key] = {**handle, "_collected": False}
        self._write_all(data)

    def load(self, batch_job: str, provider_batch_ids: list[str]) -> dict[str, Any] | None:
        data = self._read_all()
        entry = data.get(_handle_key(batch_job, provider_batch_ids))
        if entry is None:
            return None
        return {k: v for k, v in entry.items() if k != "_collected"}

    def mark_collected(self, batch_job: str, provider_batch_ids: list[str]) -> None:
        data = self._read_all()
        key = _handle_key(batch_job, provider_batch_ids)
        if key in data:
            data[key]["_collected"] = True
            self._write_all(data)

    def list_open(self) -> list[dict[str, Any]]:
        data = self._read_all()
        return [
            {k: v for k, v in entry.items() if k != "_collected"}
            for entry in data.values()
            if not entry.get("_collected")
        ]


def resolve_batch_state_store(state_store_config: dict[str, Any] | None) -> BatchStateStore:
    """Resolves a batch_registry.yaml entry's `state_store` block to a
    BatchStateStore-conforming object. None/omitted, or an explicit
    `backend: "none"`, both resolve to _NoneStateStore -- the caller
    persists the BatchHandle dict themselves.

    - backend: "file" -> JSON-on-disk store at `path` (default
      ".batch_state/handles.json").
    - backend: "custom" -> imports and calls the zero-arg callable named
      by `factory` ("dotted.path:callable_name"), same shape as
      resolve_session_store()'s custom backend. This is how a project
      plugs in a durable, cross-host store (e.g. CMN's MySQL table)."""
    if not state_store_config or state_store_config.get("backend", "none") == "none":
        return _NoneStateStore()

    backend = state_store_config["backend"]
    if backend == "file":
        return _FileStateStore(state_store_config.get("path", ".batch_state/handles.json"))

    if backend == "custom":
        factory = state_store_config.get("factory")
        if not factory or ":" not in factory:
            raise BatchStateStoreResolutionError(
                "batch_registry.yaml state_store.backend == 'custom' requires a "
                f"'factory' value shaped 'dotted.module.path:callable_name', got {factory!r}."
            )
        module_path, _, callable_name = factory.partition(":")
        import importlib

        module = importlib.import_module(module_path)
        try:
            build = getattr(module, callable_name)
        except AttributeError as exc:
            raise BatchStateStoreResolutionError(
                f"No callable {callable_name!r} in module {module_path!r} "
                f"(state_store.factory={factory!r})."
            ) from exc
        return build()

    raise BatchStateStoreResolutionError(
        f"Unknown batch state_store backend {backend!r}. Must be one of "
        f"'none', 'file', 'custom'."
    )

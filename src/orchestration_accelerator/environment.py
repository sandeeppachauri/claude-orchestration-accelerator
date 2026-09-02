"""
environment.py

Resolves the "environment" value used everywhere it's needed --
build_options()/build_api_credential() calls, default backend selection,
etc. -- per Master_Accelerator_Plan.md 4.1's "Environment source" section.

Precedence: payload value (if present) -> .env value -> hardcoded
fallback ("local") only if neither is set.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_loaded_dotenv_dirs: set[str] = set()


def _ensure_dotenv_loaded(dotenv_path: Path | str | None = None) -> None:
    """Loads a project's .env file (if present) into os.environ, once per
    directory per process. Safe to call repeatedly."""
    search_dir = str(Path(dotenv_path).parent) if dotenv_path else str(Path.cwd())
    if search_dir in _loaded_dotenv_dirs:
        return
    _loaded_dotenv_dirs.add(search_dir)
    path = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)


def resolve_environment(
    payload_value: str | None = None, dotenv_path: Path | str | None = None
) -> str:
    """payload_value -> .env's ENVIRONMENT -> 'local'."""
    if payload_value:
        return payload_value
    _ensure_dotenv_loaded(dotenv_path)
    return os.environ.get("ENVIRONMENT", "local")


def resolve_default_model(dotenv_path: Path | str | None = None) -> str:
    """.env's DEFAULT_MODEL -> 'claude-sonnet-5'. Used by the registry's
    default configuration fallback."""
    _ensure_dotenv_loaded(dotenv_path)
    return os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")


def resolve_trimming_strategy(dotenv_path: Path | str | None = None) -> str:
    """.env's DEFAULT_TRIMMING_STRATEGY -> 'none'. Fallback used by a
    context_mode: session process that omits its own `trimming` block."""
    _ensure_dotenv_loaded(dotenv_path)
    return os.environ.get("DEFAULT_TRIMMING_STRATEGY", "none")

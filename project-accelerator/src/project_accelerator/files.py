"""
files.py

Thin project-level wrapper over orchestration_accelerator.file, mirroring
execute() being a one-liner entry point. No registry needed -- just
environment resolution, same precedence as execute().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration_accelerator.environment import resolve_environment
from orchestration_accelerator.file import FileManager, FileUploadError

__all__ = ["FileUploadError", "upload_file"]


def upload_file(
    path: str | Path,
    environment: str | None = None,
    backend: str = "messages_api",
    **extra: Any,
) -> str:
    resolved_environment = resolve_environment(environment)
    return FileManager(environment=resolved_environment).upload(path, backend=backend, **extra)

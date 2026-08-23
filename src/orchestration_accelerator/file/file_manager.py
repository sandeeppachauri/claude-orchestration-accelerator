"""
file_manager.py

File-upload wrapper alongside the text-interaction path in core.py. Reuses
claude-auth-accelerator exactly as model_router_accelerator.backends does:
lazy import, build_api_credential(environment) for raw API-key calls.

Two backends, same as execute()'s payload['backend']:
  - "messages_api": real upload via Anthropic's Files API. Returns a
    server-side file_id that can be referenced in a later messages.create
    content block.
  - "agent_sdk": there is no Files API surface for the agent SDK -- the
    file is passed straight through as a local path via
    build_options(**extra), the same passthrough call_agent_sdk already
    uses for every other capability key. upload() just validates the path
    exists and returns a reference token; no network call is made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FileUploadError(Exception):
    """Raised on upload/list/retrieve/delete failures, or an unsupported
    backend/path."""


class FileManager:
    def __init__(self, environment: str = "local"):
        self.environment = environment

    def _client(self):
        try:
            import anthropic
        except ImportError as exc:
            raise FileUploadError(
                "The 'anthropic' package is required for messages_api file "
                "operations."
            ) from exc
        from auth_accelerator import build_api_credential

        api_key = build_api_credential(self.environment)
        return anthropic.Anthropic(api_key=api_key)

    def upload(self, path: str | Path, backend: str = "messages_api", **extra: Any) -> str:
        file_path = Path(path)
        if not file_path.exists():
            raise FileUploadError(f"No such file: {file_path}")

        if backend == "messages_api":
            try:
                with open(file_path, "rb") as f:
                    result = self._client().files.create(
                        file=f, purpose=extra.pop("purpose", "user_data")
                    )
                return result.id
            except FileUploadError:
                raise
            except Exception as exc:
                raise FileUploadError(f"Upload failed for {file_path}: {exc}") from exc

        if backend == "agent_sdk":
            # No upload endpoint -- the local path is the reference; it
            # flows through build_options(**extra) at call time, same as
            # every other agent_sdk capability passthrough key.
            return str(file_path.resolve())

        raise FileUploadError(f"Unsupported backend '{backend}' for file upload.")

    def list(self) -> list[Any]:
        try:
            return list(self._client().files.list())
        except FileUploadError:
            raise
        except Exception as exc:
            raise FileUploadError(f"List failed: {exc}") from exc

    def retrieve(self, file_id: str) -> Any:
        try:
            return self._client().files.retrieve(file_id)
        except FileUploadError:
            raise
        except Exception as exc:
            raise FileUploadError(f"Retrieve failed for {file_id}: {exc}") from exc

    def delete(self, file_id: str) -> Any:
        try:
            return self._client().files.delete(file_id)
        except FileUploadError:
            raise
        except Exception as exc:
            raise FileUploadError(f"Delete failed for {file_id}: {exc}") from exc


def upload_file(
    path: str | Path, environment: str = "local", backend: str = "messages_api", **extra: Any
) -> str:
    """Module-level convenience wrapper, mirrors execute() being the
    one-liner entry point for text interactions."""
    return FileManager(environment=environment).upload(path, backend=backend, **extra)

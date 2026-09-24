"""
attachments.py

Shared attachment-block construction for call_messages_api()/
call_agent_sdk() -- see .claude/rules/attachments.md.

An `attachments` entry is `{file_id|path|text, kind, title?, mime_type?,
cache?}`, exactly one of `file_id`/`path`/`text`. `attachments` is a
per-call payload key (execute()'s OPTIONAL_PAYLOAD_KEYS), never a
process_registry.yaml capability -- it is passed as its own explicit
keyword argument through execute_with_fallback()/call_messages_api()/
call_agent_sdk(), bypassing validate_capabilities() entirely (see
core.py's `attachments` handling and .claude/rules/attachments.md for why).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration_accelerator.errors import friendly_error


class AttachmentError(Exception):
    """Raised for a malformed attachment entry (not exactly one of
    file_id/path/text, or an unreadable `path`)."""


_TEXT_EXTENSIONS_AS_PLAIN = {
    ".txt", ".md", ".py", ".java", ".js", ".ts", ".json", ".yaml", ".yml",
    ".xml", ".csv", ".log", ".sql", ".sh", ".c", ".cpp", ".h", ".go", ".rs",
}


def _validate_entry(entry: dict[str, Any]) -> None:
    sources = [k for k in ("file_id", "path", "text") if entry.get(k) is not None]
    if len(sources) != 1:
        raise AttachmentError(
            friendly_error(
                "Each attachment must specify exactly one source.",
                f"Attachment entry {entry!r} must set exactly one of "
                f"'file_id'/'path'/'text', got {sources}.",
            )
        )


def _inline_source_for_path(file_path: Path) -> dict[str, Any]:
    """Reads a local text-like file and returns a `text`-type document
    source block -- used for a `path` attachment under agent_sdk (no
    Files API there) and as the messages_api inline fallback when a
    caller doesn't want an upload."""
    suffix = file_path.suffix.lower()
    media_type = "text/plain" if suffix in _TEXT_EXTENSIONS_AS_PLAIN or suffix == "" else "text/plain"
    return {
        "type": "text",
        "media_type": media_type,
        "data": file_path.read_text(encoding="utf-8"),
    }


def build_messages_api_blocks(
    attachments: list[dict[str, Any]], environment: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (content_blocks, uploaded_file_ids). `path` entries are
    auto-uploaded via FileManager first (real anthropic 1.8.0 GA document/
    image blocks only accept a `file_id` or inline base64/text source, not
    a local path directly)."""
    from orchestration_accelerator.file import FileManager

    blocks: list[dict[str, Any]] = []
    uploaded_file_ids: list[str] = []
    manager: FileManager | None = None

    for entry in attachments:
        _validate_entry(entry)
        kind = entry.get("kind", "document")
        cache_control = {"type": "ephemeral"} if entry.get("cache") else None

        if entry.get("file_id") is not None:
            source = {"type": "file", "file_id": entry["file_id"]}
        elif entry.get("path") is not None:
            file_path = Path(entry["path"])
            if not file_path.exists():
                raise AttachmentError(f"No such file: {file_path}")
            if manager is None:
                manager = FileManager(environment=environment)
            file_id = manager.upload(file_path, backend="messages_api")
            uploaded_file_ids.append(file_id)
            source = {"type": "file", "file_id": file_id}
        else:  # entry["text"] is not None
            if kind == "image":
                raise AttachmentError("An inline 'text' attachment cannot have kind='image'.")
            block: dict[str, Any] = {
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": "text/plain",
                    "data": entry["text"],
                },
            }
            if entry.get("title"):
                block["title"] = entry["title"]
            if cache_control:
                block["cache_control"] = cache_control
            blocks.append(block)
            continue

        block = {"type": "image" if kind == "image" else "document", "source": source}
        if kind != "image" and entry.get("title"):
            block["title"] = entry["title"]
        if cache_control:
            block["cache_control"] = cache_control
        blocks.append(block)

    return blocks, uploaded_file_ids


def build_agent_sdk_content(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """agent_sdk has no Files API surface -- a `file_id` attachment is
    rejected by the caller before this ever runs (see
    call_agent_sdk()). `path`/`text` attachments are inlined as text
    content blocks for the streaming-input prompt message (see
    .claude/rules/attachments.md)."""
    blocks: list[dict[str, Any]] = []
    for entry in attachments:
        _validate_entry(entry)
        if entry.get("file_id") is not None:
            raise AttachmentError(
                friendly_error(
                    "This step's backend (agent_sdk) can't use a file_id "
                    "attachment -- there is no Files API surface for the "
                    "agent SDK.",
                    "agent_sdk has no Files API concept; pass 'path' or "
                    "'text' instead, or switch this step to backend: "
                    "messages_api to use a file_id attachment.",
                )
            )
        if entry.get("path") is not None:
            file_path = Path(entry["path"])
            if not file_path.exists():
                raise AttachmentError(f"No such file: {file_path}")
            text = file_path.read_text(encoding="utf-8")
        else:
            text = entry["text"]
        title = entry.get("title")
        prefix = f"[{title}]\n" if title else ""
        blocks.append({"type": "text", "text": f"{prefix}{text}"})
    return blocks

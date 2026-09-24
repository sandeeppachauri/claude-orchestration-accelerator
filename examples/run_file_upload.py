"""
run_file_upload.py

Runnable example of execute()'s `attachments` payload key (see
.claude/rules/attachments.md) -- attaches a real file to a model call as
a document content block, instead of the broken pattern of pasting a
`file_id` string into plain text (which the model can't act on).

Deliberately messages_api, not agent_sdk: a `file_id` attachment has no
Files API surface on agent_sdk (AttachmentError is raised before any
call). A `path`/`text` attachment works on agent_sdk too (inlined as
extra text via query()'s streaming-input form), but this example
exercises the real upload -> file_id -> document-block path, which is
messages_api-only.

Needs a credential (ANTHROPIC_API_KEY env var) resolved via
claude-auth-accelerator -- messages_api has no ambient-OAuth path.

Run from the repo root:
    python examples/run_file_upload.py [path-to-file]
"""

from __future__ import annotations

import sys

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute, upload_file


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "README.md"

    try:
        file_id = upload_file(path, environment="local", backend="messages_api")
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY.")
        return

    print(f"Uploaded {path!r} -> file_id={file_id}")

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "Summarize the attached document, then classify this ticket.",
            "attachments": [{"file_id": file_id, "kind": "document", "title": path}],
            "backend": "messages_api",
            "environment": "local",
        }
    )

    step_result = result["classify"]
    print(f"[classify] {step_result['output']}")
    print(f"    uploaded_file_ids={step_result['uploaded_file_ids']}")


if __name__ == "__main__":
    main()

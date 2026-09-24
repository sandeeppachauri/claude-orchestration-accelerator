"""
run_batch_processing.py

Runnable example of the split batch API -- submit_batch()/
get_batch_status()/collect_batch() -- wired to the repo's own
ticketClassificationBatch entry in config/batch_registry.yaml (see
.claude/rules/batch-registry.md). Demonstrates the resumable pattern:
submit_batch() returns a JSON-serializable handle immediately (no
polling inside the call), so a real caller can persist it and survive a
process restart -- shown here as a plain print + json.dumps roundtrip,
not by actually killing the process.

execute_batch({"batch_id": ..., "inputs": [...]}) still works as a
one-call blocking wrapper (submit -> poll -> collect) if you don't need
resumability -- see the commented-out call at the bottom.

Batches are messages_api only. Needs a credential (ANTHROPIC_API_KEY env
var) resolved via claude-auth-accelerator -- no ambient-OAuth path.

Run from the repo root:
    python examples/run_batch_processing.py
"""

from __future__ import annotations

import json
import time

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import collect_batch, get_batch_status, submit_batch


def main() -> None:
    try:
        handle = submit_batch(
            {
                "batch_id": "ticketClassificationBatch_01",
                "inputs": [
                    "I was double charged for my subscription.",
                    "The app crashes every time I try to log in.",
                ],
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY.")
        return

    print("Submitted. Handle (persist this -- it's plain JSON):")
    print(json.dumps({k: v for k, v in handle.items() if not k.startswith("_")}, indent=2))

    while True:
        status = get_batch_status(handle)
        print(f"status: {status['statuses']}")
        if status["all_ended"]:
            break
        time.sleep(5)

    result = collect_batch(handle)
    print(f"\ntotals: {result['totals']}")
    for item in result["results"]:
        print(f"[{item['custom_id']}] status={item['status']} output={item['output']!r}")

    # One-call blocking alternative, no resumability:
    # from project_accelerator import execute_batch
    # result = execute_batch({"batch_id": "ticketClassificationBatch_01", "inputs": [...]})


if __name__ == "__main__":
    main()

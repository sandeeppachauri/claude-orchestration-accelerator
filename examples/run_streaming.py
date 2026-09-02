"""
run_streaming.py

Runnable example of `stream: true` (see .claude/rules/streaming.md) --
chunks emitted to execute()'s payload["on_chunk"] callback in real time
as the model produces them, instead of only returning the fully-buffered
text after the whole turn completes. Demonstrates agent_sdk's streaming
path (the SDK's own include_partial_messages mechanism); the same
on_chunk callback works unchanged on messages_api (its own
messages.stream() context manager instead).

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run from the repo root:
    python examples/run_streaming.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def print_chunk(step_name: str, chunk: str) -> None:
    print(chunk, end="", flush=True)


def main() -> None:
    print("Streaming chunks as they arrive:\n")
    try:
        result = execute(
            {
                "process": "streamingDemo",
                "step": "narrate",
                "input": {"scenario": "a customer's login keeps failing on WiFi only"},
                "backend": "agent_sdk",
                "environment": "local",
                "on_chunk": print_chunk,
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    print("\n\n--- full accumulated output (identical whether streamed or not) ---")
    print(result["narrate"]["output"])


if __name__ == "__main__":
    main()

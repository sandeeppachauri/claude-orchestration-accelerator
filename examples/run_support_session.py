"""
run_support_session.py

Runnable example of context_mode: session (see .claude/rules/context-mode.md)
-- a real, accumulating agent_sdk conversation across steps and across
execute() calls, instead of the default context_mode: threaded's
{{<stepName>_output}} text-templating.

Demonstrates:
  1. Opening the supportSession process -- intake and diagnose share one
     open ClaudeSDKClient for the whole call; diagnose sees intake's turn
     as real conversation history.
  2. Cross-call resume -- a second, later execute() call passes back the
     first call's returned session_id to continue the same conversation
     from a brand-new call.
  3. session_store: {backend: memory} -- supportSession's process config
     mirrors the transcript to an in-memory SessionStore, which is what
     makes cross-host/cross-container resume possible in production
     (this example only demonstrates the wiring; a single local process
     doesn't need it since local disk already has the transcript).

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run from the repo root:
    python examples/run_support_session.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        first = execute(
            {
                "process": "supportSession",
                "input": "My app crashes every time I try to log in.",
                "backend": "agent_sdk",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    for step, step_result in first.items():
        print(f"[{step}] {step_result['output']}")

    session_id = first["diagnose"]["session_id"]
    print(f"\nsession_id from call 1: {session_id}")

    print("\n--- resuming the same conversation in a new execute() call ---")
    second = execute(
        {
            "process": "supportSession",
            "step": "diagnose",
            "input": "It only happens on WiFi, not on cellular data.",
            "backend": "agent_sdk",
            "environment": "local",
            "session_id": session_id,
        }
    )
    print(f"[diagnose] {second['diagnose']['output']}")


if __name__ == "__main__":
    main()

"""
run_assistant_seed.py

Runnable example of `assistant_prompt` (see .claude/rules/process-registry.md's
"Runtime input & {{key}}" section) -- a canned prior assistant turn seeded
before the real user turn, for few-shot priming or "continue from this
canned response" patterns.

Deliberately messages_api, not agent_sdk (unlike every other example in
this directory, which default to agent_sdk): claude_agent_sdk's query()
takes a single string prompt, not a message array, so there is no SDK
surface to seed a prior assistant turn on agent_sdk. A step with
assistant_prompt set raises UnsupportedCapabilityError before any model
call if run with backend: agent_sdk -- this is not a config choice, it
is a hard backend limitation, so this example cannot be switched to
agent_sdk without breaking every run.

Needs a credential (ANTHROPIC_API_KEY env var) resolved via
claude-auth-accelerator -- messages_api has no ambient-OAuth path.

Run from the repo root:
    python examples/run_assistant_seed.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        result = execute(
            {
                "process": "fewshotLabeling",
                "step": "label",
                "input": {"ticket_text": "The app crashes every time I try to log in."},
                "backend": "messages_api",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY.")
        return

    print(f"[label] {result['label']['output']}")


if __name__ == "__main__":
    main()

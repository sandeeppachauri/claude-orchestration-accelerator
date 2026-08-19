"""
run_ticket_classification.py

Runnable example of the full stack: project_accelerator's execute() driving
orchestration_accelerator (registry + prompting) and model-router against
the repo's dummy process_registry.yaml + prompts/. Makes real model calls
via the agent_sdk backend -- needs a credential (ANTHROPIC_API_KEY env var,
or an ambient `claude login` OAuth session) resolved via
claude-auth-accelerator.

Run from the repo root:
    python examples/run_ticket_classification.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        result = execute(
            {
                "process": "ticketClassification",
                "input": "The app crashes every time I try to log in.",
                "backend": "agent_sdk",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    for step, output in result.items():
        print(f"[{step}] {output}")


if __name__ == "__main__":
    main()

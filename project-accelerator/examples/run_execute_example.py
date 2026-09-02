"""
run_execute_example.py

Runnable example of project_accelerator's single entry point,
execute(payload), including the `step` narrowing option and the
unknown-process default-configuration fallback. Uses this repo's dummy
process_registry.yaml + prompts/ at the repo root. Makes real model calls
-- needs a credential (ANTHROPIC_API_KEY env var, or an ambient
`claude login` OAuth session for the agent_sdk backend) resolved via
claude-auth-accelerator.

Run from the repo root:
    python project-accelerator/examples/run_execute_example.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        print("--- full onboarding pipeline (messages_api backend) ---")
        result = execute(
            {
                "process": "onboarding",
                "input": "New user Jane Doe, ID docs uploaded.",
                "backend": "messages_api",
            }
        )
        for step, step_result in result.items():
            print(f"[{step}] {step_result['output']}")

        print("\n--- single-step narrowing (only 'welcome' runs) ---")
        result = execute(
            {
                "process": "onboarding",
                "step": "welcome",
                "input": "New user Jane Doe.",
                "backend": "agent_sdk",
            }
        )
        print(result)

        print("\n--- unknown process falls back to built-in default config ---")
        result = execute(
            {
                "process": "adHocSummary",
                "input": "Summarize this in one sentence: the sky is blue.",
                "backend": "agent_sdk",
            }
        )
        print(result)
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")


if __name__ == "__main__":
    main()

"""
run_parallel_processing.py

Runnable example of parallel_processing: true (see
.claude/rules/parallel-processing.md) -- every step but the last in a
process's `steps` list runs concurrently against the same input, then the
mandatory trailing synthesis_step (or reconcile_step) reconciles every
branch's output into one result, via the same {{<stepName>_output}}
templating threaded-mode steps already use.

Demonstrates parallelAnalysisDemo: parallel_sentiment and parallel_risk
run concurrently (each blind to the other's result), then synthesis_step
combines both into one JSON recommendation.

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run from the repo root:
    python examples/run_parallel_processing.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        result = execute(
            {
                "process": "parallelAnalysisDemo",
                "input": "The product works great, thanks!",
                "backend": "agent_sdk",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    print(f"[parallel_sentiment] {result['parallel_sentiment']['output']}")
    print(f"[parallel_risk] {result['parallel_risk']['output']}")
    print(f"[synthesis_step] {result['synthesis_step']['output']}")


if __name__ == "__main__":
    main()

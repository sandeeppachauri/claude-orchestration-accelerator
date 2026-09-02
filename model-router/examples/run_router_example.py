"""
run_router_example.py

Runnable example of execute_with_fallback(): the ordered model/fallback
chain execution model-router-accelerator provides, backend-agnostic
(agent_sdk | messages_api). Makes a real model call -- needs a credential
(ANTHROPIC_API_KEY env var, or an ambient `claude login` OAuth session for
the agent_sdk backend) resolved via claude-auth-accelerator.

Run from the repo root:
    python model-router/examples/run_router_example.py
"""

from __future__ import annotations

import asyncio

from auth_accelerator.exceptions import AuthResolutionError
from model_router_accelerator import execute_with_fallback


async def main() -> None:
    try:
        result = await execute_with_fallback(
            model="claude-haiku-4-5-20251001",
            fallback=["claude-sonnet-5"],
            system_prompt="You are a helpful assistant.",
            user_content="Summarize in one sentence: the server keeps timing out.",
            backend="agent_sdk",
            environment="local",
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return
    print(result["text"])
    print(f"model_used={result['model_used']} usage={result['usage']}")


if __name__ == "__main__":
    asyncio.run(main())

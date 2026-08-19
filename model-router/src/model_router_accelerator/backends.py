"""
backends.py

The two pluggable execution backends. claude_agent_sdk and anthropic are
imported lazily (inside each function), so importing this package -- or
even model_router_accelerator itself -- never hard-requires either SDK
unless that specific backend is actually invoked.

Both backends resolve auth via claude-auth-accelerator, never by
themselves reading environment variables or mounted sessions directly --
build_options() for agent_sdk, build_api_credential() for messages_api.
"""

from __future__ import annotations

from typing import Any

from .exceptions import RateLimitOrOverloadError

_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "overloaded", "429", "529")


def _looks_like_rate_limit_or_overload(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


async def call_agent_sdk(
    *, model: str, system_prompt: str, user_content: str, environment: str, max_turns: int = 1
) -> str:
    """Runs one query via claude_agent_sdk, resolving auth through
    claude-auth-accelerator's build_options()."""
    from claude_agent_sdk import AssistantMessage, TextBlock, query

    from auth_accelerator import build_options

    options = build_options(
        environment=environment,
        model=model,
        max_turns=max_turns,
        system_prompt=system_prompt,
    )

    text = ""
    try:
        async for message in query(prompt=user_content, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text += block.text
    except Exception as exc:  # noqa: BLE001 - re-tag rate-limit/overload errors uniformly
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise
    return text


async def call_messages_api(
    *, model: str, system_prompt: str, user_content: str, environment: str, max_tokens: int = 1024
) -> str:
    """Calls anthropic's Messages API directly, resolving auth through
    claude-auth-accelerator's build_api_credential()."""
    import anthropic

    from auth_accelerator import build_api_credential

    api_key = build_api_credential(environment)
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # noqa: BLE001
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise

    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    return text


BACKENDS: dict[str, Any] = {
    "agent_sdk": call_agent_sdk,
    "messages_api": call_messages_api,
}

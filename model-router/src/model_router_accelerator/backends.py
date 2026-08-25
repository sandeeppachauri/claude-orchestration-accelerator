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

from .exceptions import AgentProducedNoTextError, RateLimitOrOverloadError

_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "overloaded", "429", "529")


def _looks_like_rate_limit_or_overload(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


def _merge_hooks(*hook_dicts: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    for hooks in hook_dicts:
        for event_name, matchers in hooks.items():
            merged.setdefault(event_name, []).extend(matchers)
    return merged


async def call_agent_sdk(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    environment: str,
    max_turns: int = 1,
    mcp_servers: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    guardrails: list[str] | None = None,
    **extra: Any,
) -> str:
    """Runs one query via claude_agent_sdk, resolving auth through
    claude-auth-accelerator's build_options(). Any extra keyword (e.g.
    `thinking`, `permission_mode`) passes straight through to
    build_options()/ClaudeAgentOptions -- this is what lets
    process_registry.yaml set per-step capabilities without touching
    accelerator code.

    `mcp_servers`/`allowed_tools` (MCP access scoping -- see
    orchestration_accelerator.mcp_scope) and `guardrails` (general
    enforcement -- see orchestration_accelerator.guardrails) are not real
    ClaudeAgentOptions fields, so they're consumed here as their own
    hook-attaching mechanisms rather than forwarded via `**extra`. Both
    are optional and fail-open when omitted -- no hook is attached, and
    the SDK's own default .mcp.json/global-settings MCP discovery is
    left untouched (ClaudeAgentOptions.mcp_servers itself is never set
    here)."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, query

    from auth_accelerator import build_options
    from orchestration_accelerator.logging import get_default_hooks
    from orchestration_accelerator.mcp_scope import make_mcp_scope_hook

    hook_groups = [get_default_hooks()]
    if mcp_servers is not None or allowed_tools is not None:
        hook_groups.append(
            {"PreToolUse": [{"hooks": [make_mcp_scope_hook(mcp_servers, allowed_tools)]}]}
        )
    if guardrails:
        from orchestration_accelerator.guardrails import get_guardrail

        hook_groups.append(
            {"PreToolUse": [{"hooks": [get_guardrail(name) for name in guardrails]}]}
        )

    options = build_options(
        environment=environment,
        model=model,
        max_turns=max_turns,
        system_prompt=system_prompt,
        hooks=_merge_hooks(*hook_groups),
        **extra,
    )

    text = ""
    tool_call_count = 0
    try:
        async for message in query(prompt=user_content, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text += block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
    except Exception as exc:  # noqa: BLE001 - re-tag rate-limit/overload errors uniformly
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise

    if not text:
        raise AgentProducedNoTextError(
            f"agent_sdk query for model {model!r} completed with max_turns={max_turns} "
            f"but produced no text output ({tool_call_count} tool call(s) made instead). "
            "The model likely spent its whole turn budget on tool use rather than "
            "replying -- check this step's `tools`/`permission_mode` in "
            "process_registry.yaml (set `tools: []` if the step should never need a "
            "tool), or raise max_turns if tool use is actually required."
        )
    return text


async def call_messages_api(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    environment: str,
    max_tokens: int = 1024,
    skills: list[str] | None = None,
    **extra: Any,
) -> str:
    """Calls anthropic's Messages API directly, resolving auth through
    claude-auth-accelerator's build_api_credential(). Any extra keyword
    (e.g. `temperature`, `top_p`, `thinking`) passes straight through to
    `messages.create()` -- this is what lets process_registry.yaml set
    per-step capabilities without touching accelerator code.

    `skills` is a simple flat list of skill names on process_registry.yaml
    (same shape as ClaudeAgentOptions.skills), but the raw Messages API
    only supports Skills on the beta client, nested as
    `container.skills: [{skill_id, type, version}]` -- not a flat kwarg.
    When set, this switches to `client.beta.messages.create()` and builds
    that container shape (defaulting `type` to "custom" -- project-managed
    skills). Steps without `skills` keep using the stable, non-beta
    client, unaffected."""
    import anthropic

    from auth_accelerator import build_api_credential

    api_key = build_api_credential(environment)
    client = anthropic.Anthropic(api_key=api_key)

    try:
        if skills:
            container = {
                "skills": [
                    entry if isinstance(entry, dict) else {"skill_id": entry, "type": "custom"}
                    for entry in skills
                ]
            }
            response = client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                container=container,
                **extra,
            )
        else:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                **extra,
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

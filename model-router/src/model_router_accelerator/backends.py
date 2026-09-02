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

import inspect
import time
from typing import Any

from orchestration_accelerator.errors import friendly_error

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
    assistant_prompt: str | None = None,
    stream: bool = False,
    on_chunk: Any | None = None,
    **extra: Any,
) -> dict[str, Any]:
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
    here).

    Returns a structured dict (`text`, `model_used`, `usage`,
    `stop_reason`, `request_id`, `latency_ms`, `session_id`,
    `tool_calls`) rather than a bare string -- `usage`/`stop_reason`/
    `session_id` are read off the terminal `ResultMessage` when the SDK
    emits one (it carries the SDK's own end-of-turn summary, including
    `model_usage` -- a per-model token/cost breakdown), falling back to
    the last `AssistantMessage` seen if no `ResultMessage` arrives.
    `request_id` is always `None` here -- messages_api-only concept.

    `assistant_prompt` is accepted but must always be `None` here --
    `query()` takes a single string prompt, not a message array, so
    there is no SDK surface to seed a prior assistant turn.
    core.py's `_run_one_step()` raises `UnsupportedCapabilityError`
    before ever calling this function with a non-`None` value; this
    parameter exists purely so `execute_with_fallback(**capabilities)`'s
    uniform kwarg-forwarding doesn't need a backend-specific branch.

    `stream`, when `True`, sets `ClaudeAgentOptions.include_partial_messages
    = True` and invokes `on_chunk(chunk_text)` (sync or async) per
    `StreamEvent` text-delta payload as they arrive, interleaved with the
    normal `AssistantMessage`/`ResultMessage` stream -- `on_chunk` is
    optional even with `stream: True`. The final accumulated `text`/
    `usage`/etc. are identical whether or not streaming was used."""
    from claude_agent_sdk import (
        AssistantMessage,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ToolUseBlock,
        query,
    )

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
        include_partial_messages=stream,
        **extra,
    )

    text = ""
    tool_call_count = 0
    stop_reason: str | None = None
    session_id: str | None = None
    usage: dict[str, Any] | None = None
    model_used = model
    start = time.monotonic()
    try:
        async for message in query(prompt=user_content, options=options):
            if isinstance(message, StreamEvent):
                delta = message.event.get("delta") if isinstance(message.event, dict) else None
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    if on_chunk is not None:
                        maybe_awaitable = on_chunk(delta.get("text", ""))
                        if inspect.isawaitable(maybe_awaitable):
                            await maybe_awaitable
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text += block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
                stop_reason = message.stop_reason
                session_id = message.session_id
                usage = message.usage
            elif isinstance(message, ResultMessage):
                stop_reason = message.stop_reason
                session_id = message.session_id
                usage = message.usage
    except Exception as exc:  # noqa: BLE001 - re-tag rate-limit/overload errors uniformly
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise
    latency_ms = (time.monotonic() - start) * 1000

    if not text:
        raise AgentProducedNoTextError(
            friendly_error(
                "The AI didn't produce an answer for this step -- it spent its "
                "whole turn budget doing other actions instead of replying, so "
                "there's no output to show. This is a config problem, not "
                "something a retry alone will fix.",
                f"agent_sdk query for model {model!r} completed with "
                f"max_turns={max_turns} but produced no text output "
                f"({tool_call_count} tool call(s) made instead). Check this "
                f"step's `tools`/`permission_mode` in process_registry.yaml "
                f"(set `tools: []` if the step should never need a tool), or "
                f"raise max_turns if tool use is actually required.",
            )
        )
    return {
        "text": text,
        "model_used": model_used,
        "usage": usage or {},
        "stop_reason": stop_reason,
        "request_id": None,
        "latency_ms": latency_ms,
        "session_id": session_id,
        "tool_calls": [{"name": "tool", "count": tool_call_count}] if tool_call_count else [],
    }


async def open_agent_sdk_session(
    *,
    model: str,
    system_prompt: str,
    environment: str,
    max_turns: int = 1,
    resume: str | None = None,
    session_store: Any | None = None,
    mcp_servers: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    guardrails: list[str] | None = None,
    on_mirror_error: Any | None = None,
    **extra: Any,
) -> Any:
    """Opens (does not close) a claude_agent_sdk.ClaudeSDKClient for a
    context_mode: session process -- see .claude/rules/context-mode.md.
    Used once per execute() call, not once per step: core.py's step loop
    keeps this client open across every step, calling run_session_turn()
    per step, then closes it after the last step.

    `system_prompt`/`model`/`max_turns` are fixed for the whole client's
    lifetime (ClaudeAgentOptions is set once at construction -- the SDK
    has no per-turn override) -- callers should build this from the
    *first* step's config; later steps' prompt YAML system_prompt is
    still rendered and used as that step's *query text* context, but the
    client-level system_prompt/model/max_turns stay fixed for the whole
    session.

    `resume` seeds the client from a prior, now-closed execute() call's
    session_id (cross-call continuation). `session_store`, when
    resolved via orchestration_accelerator.registry.resolve_session_store(),
    mirrors the transcript to durable storage -- combines with `resume`
    at construction time per the installed SDK's documented behavior.
    `on_mirror_error(error, key)` is invoked (best-effort, from
    core.py's step loop) whenever the client yields a MirrorErrorMessage."""
    from claude_agent_sdk import ClaudeSDKClient

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
        resume=resume,
        session_store=session_store,
        **extra,
    )
    client = ClaudeSDKClient(options=options)
    await client.connect()
    return client


async def run_session_turn(
    client: Any, user_content: str, model: str, on_mirror_error: Any | None = None
) -> dict[str, Any]:
    """Runs one query()/receive_response() turn on an already-open
    ClaudeSDKClient (see open_agent_sdk_session()), returning the same
    structured result shape call_agent_sdk() returns -- so core.py can
    treat a session-mode step's result identically to a threaded-mode
    step's result."""
    from claude_agent_sdk import AssistantMessage, MirrorErrorMessage, ResultMessage, TextBlock, ToolUseBlock

    text = ""
    tool_call_count = 0
    stop_reason: str | None = None
    session_id: str | None = None
    usage: dict[str, Any] | None = None
    start = time.monotonic()
    try:
        await client.query(user_content)
        async for message in client.receive_response():
            if isinstance(message, MirrorErrorMessage):
                if on_mirror_error is not None:
                    await on_mirror_error(message.error, message.key)
                continue
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text += block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
                stop_reason = message.stop_reason
                session_id = message.session_id
                usage = message.usage
            elif isinstance(message, ResultMessage):
                stop_reason = message.stop_reason
                session_id = message.session_id
                usage = message.usage
    except Exception as exc:  # noqa: BLE001 - re-tag rate-limit/overload errors uniformly
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise
    latency_ms = (time.monotonic() - start) * 1000

    if not text:
        raise AgentProducedNoTextError(
            friendly_error(
                "The AI didn't produce an answer for this step -- it spent its "
                "whole turn budget doing other actions instead of replying, so "
                "there's no output to show. This is a config problem, not "
                "something a retry alone will fix.",
                f"agent_sdk session turn completed but produced no text output "
                f"({tool_call_count} tool call(s) made instead). Check this "
                f"step's `tools`/`permission_mode` in process_registry.yaml "
                f"(set `tools: []` if the step should never need a tool), or "
                f"raise max_turns if tool use is actually required.",
            )
        )
    return {
        "text": text,
        "model_used": model,
        "usage": usage or {},
        "stop_reason": stop_reason,
        "request_id": None,
        "latency_ms": latency_ms,
        "session_id": session_id,
        "tool_calls": [{"name": "tool", "count": tool_call_count}] if tool_call_count else [],
    }


async def call_messages_api(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    environment: str,
    max_tokens: int = 1024,
    skills: list[str] | None = None,
    assistant_prompt: str | None = None,
    stream: bool = False,
    on_chunk: Any | None = None,
    **extra: Any,
) -> dict[str, Any]:
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
    client, unaffected.

    `cache_control` (e.g. `{"type": "ephemeral", "ttl": "5m"}`) is popped
    out of `extra` and applied to the system prompt as an Anthropic
    prompt-cache breakpoint -- `system` becomes a one-block content-array
    instead of a plain string. The value is process-specific (supplied by
    a process_registry.yaml step, not hardcoded here) and passed straight
    through to the block's `cache_control` field.

    `assistant_prompt`, when set, is prepended as a canned prior
    assistant turn before the user turn --
    `messages: [{"role": "assistant", ...}, {"role": "user", ...}]` --
    for few-shot priming or "continue from this canned response"
    patterns. Absent (the default) -> unchanged single-turn array.

    `stream`, when `True`, switches to `client.messages.stream(...)` and
    invokes `on_chunk(chunk_text)` (sync or async) per text delta event
    as they arrive, instead of a single blocking `messages.create()`
    call -- `on_chunk` is optional even with `stream: True` (chunks are
    simply accumulated with no side-channel emission if omitted). The
    final `text`/`usage`/`stop_reason`/etc. returned are identical
    whether or not streaming was used -- streaming only adds a
    side-channel emission during the call, it never changes what is
    returned after it. `skills`/beta-client container mode is
    incompatible with `stream` in this accelerator (not attempted) --
    only the stable, non-beta client streams.

    Returns a structured dict (`text`, `model_used`, `usage`,
    `stop_reason`, `request_id`, `latency_ms`, `session_id`,
    `tool_calls`) rather than a bare string -- `session_id`/`tool_calls`
    are agent_sdk-only concepts, always `None`/`[]` here."""
    import anthropic

    from auth_accelerator import build_api_credential

    api_key = build_api_credential(environment)
    client = anthropic.Anthropic(api_key=api_key)

    cache_control = extra.pop("cache_control", None)
    system: str | list[dict[str, Any]] = system_prompt
    if cache_control is not None:
        system = [{"type": "text", "text": system_prompt, "cache_control": cache_control}]

    messages: list[dict[str, Any]] = []
    if assistant_prompt is not None:
        messages.append({"role": "assistant", "content": assistant_prompt})
    messages.append({"role": "user", "content": user_content})

    start = time.monotonic()
    try:
        if stream:
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                **extra,
            ) as message_stream:
                for event in message_stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        if on_chunk is not None:
                            maybe_awaitable = on_chunk(event.delta.text)
                            if inspect.isawaitable(maybe_awaitable):
                                await maybe_awaitable
                response = message_stream.get_final_message()
        elif skills:
            container = {
                "skills": [
                    entry if isinstance(entry, dict) else {"skill_id": entry, "type": "custom"}
                    for entry in skills
                ]
            }
            response = client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                container=container,
                **extra,
            )
        else:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                **extra,
            )
    except Exception as exc:  # noqa: BLE001
        if _looks_like_rate_limit_or_overload(exc):
            raise RateLimitOrOverloadError(str(exc)) from exc
        raise
    latency_ms = (time.monotonic() - start) * 1000

    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text

    usage = getattr(response, "usage", None)
    return {
        "text": text,
        "model_used": getattr(response, "model", model),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None),
        }
        if usage is not None
        else {},
        "stop_reason": getattr(response, "stop_reason", None),
        "request_id": getattr(response, "id", None),
        "latency_ms": latency_ms,
        "session_id": None,
        "tool_calls": [],
    }


BACKENDS: dict[str, Any] = {
    "agent_sdk": call_agent_sdk,
    "messages_api": call_messages_api,
}

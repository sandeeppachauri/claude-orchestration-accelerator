"""
mcp_scope.py

Enforces a process_registry.yaml step's optional `mcp_servers`/
`allowed_tools` keys -- narrows which already-configured MCP servers/tools
(from .mcp.json / global Claude settings, loaded by claude_agent_sdk
itself) a step's model call may reach. Never grants a new server; only
denies tools outside what's listed. Independent of guardrails.py -- see
.claude/rules/mcp-scope.md.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

_MCP_TOOL_PREFIX = "mcp__"


def _parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    """Returns (server, tool) for a `mcp__<server>__<tool>` name, or None
    for a non-MCP tool name (which this hook never touches)."""
    if not tool_name.startswith(_MCP_TOOL_PREFIX):
        return None
    rest = tool_name[len(_MCP_TOOL_PREFIX):]
    server, sep, tool = rest.partition("__")
    if not sep:
        return None
    return server, tool


def make_mcp_scope_hook(
    mcp_servers: list[str] | None, allowed_tools: list[str] | None
) -> Callable[[dict[str, Any], Any, Any], Awaitable[dict[str, Any]]]:
    """Builds a PreToolUse hook denying MCP tool calls outside the given
    scope. Non-MCP tool names always pass through untouched. Both `None`
    means no restriction at all (fail-open) -- callers should skip
    attaching this hook entirely in that case."""

    servers = set(mcp_servers) if mcp_servers is not None else None
    tools = set(allowed_tools) if allowed_tools is not None else None

    async def _hook(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        parsed = _parse_mcp_tool_name(tool_name)
        if parsed is None:
            return {}

        server, _tool = parsed
        if servers is not None and server not in servers:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"MCP server '{server}' is not in this step's mcp_servers "
                        f"scope {sorted(servers)}."
                    ),
                }
            }
        if tools is not None and tool_name not in tools:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Tool '{tool_name}' is not in this step's allowed_tools "
                        f"scope {sorted(tools)}."
                    ),
                }
            }
        return {}

    return _hook

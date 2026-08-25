"""
guardrails.py

General-purpose enforcement unrelated to MCP access (see mcp_scope.py for
that). Guardrail *logic* (a type) is project-level Python registered here;
guardrail *parameters* (thresholds, patterns) live in config/guardrails.yaml
as named instances -- tuning a guardrail is a config edit, not a code
change. See .claude/rules/guardrails-registry.md.

A Guardrail is any callable with the same PreToolUse-hook shape used by
mcp_scope.py's hooks and ClaudeSDKLoggerAccelerator's own hooks:
`async (input_data: dict, tool_use_id, context) -> dict`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

Guardrail = Callable[[dict[str, Any], Any, Any], Awaitable[dict[str, Any]]]

DEFAULT_GUARDRAILS_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "guardrails.yaml"
)


class UnknownGuardrailError(Exception):
    """Raised when a step's `guardrails` list names an entry not defined
    in config/guardrails.yaml, or an entry whose `type` isn't registered
    in GUARDRAIL_TYPES."""


def _build_redaction_guardrail(params: dict[str, Any]) -> Guardrail:
    patterns = [re.compile(p) for p in params.get("patterns", [])]

    async def _hook(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        text = str(input_data.get("tool_input", ""))
        for pattern in patterns:
            if pattern.search(text):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Blocked by redaction guardrail: input matched "
                            f"pattern '{pattern.pattern}'."
                        ),
                    }
                }
        return {}

    return _hook


def _build_rate_limit_guardrail(params: dict[str, Any]) -> Guardrail:
    max_calls = int(params["max_calls"])
    window_seconds = float(params["window_seconds"])
    _call_times: list[float] = []

    async def _hook(input_data: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        import time

        now = time.monotonic()
        cutoff = now - window_seconds
        while _call_times and _call_times[0] < cutoff:
            _call_times.pop(0)
        if len(_call_times) >= max_calls:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked by rate_limit guardrail: {max_calls} calls "
                        f"already made within {window_seconds}s."
                    ),
                }
            }
        _call_times.append(now)
        return {}

    return _hook


GUARDRAIL_TYPES: dict[str, Callable[[dict[str, Any]], Guardrail]] = {
    "redaction": _build_redaction_guardrail,
    "rate_limit": _build_rate_limit_guardrail,
}


def register_guardrail_type(type_name: str, factory: Callable[[dict[str, Any]], Guardrail]) -> None:
    """Lets a project register its own guardrail type (e.g. a custom
    schema-validation check) alongside the built-ins above."""
    GUARDRAIL_TYPES[type_name] = factory


def load_guardrails(path: Path | str | None = None) -> dict[str, Guardrail]:
    """Reads config/guardrails.yaml, builds a name -> Guardrail instance
    map by looking up each entry's `type` in GUARDRAIL_TYPES and calling
    the factory with that entry's `params`. Missing file -> empty map
    (fail-open)."""
    resolved_path = Path(path) if path is not None else DEFAULT_GUARDRAILS_CONFIG_PATH
    if not resolved_path.exists():
        return {}
    with open(resolved_path, "r") as f:
        config = yaml.safe_load(f) or {}

    guardrails: dict[str, Guardrail] = {}
    for name, entry in config.items():
        type_name = entry.get("type")
        if type_name not in GUARDRAIL_TYPES:
            raise UnknownGuardrailError(
                f"Guardrail '{name}' in {resolved_path} has type '{type_name}', "
                f"which is not registered. Known types: {sorted(GUARDRAIL_TYPES)}"
            )
        guardrails[name] = GUARDRAIL_TYPES[type_name](entry.get("params", {}))
    return guardrails


def get_guardrail(name: str, path: Path | str | None = None) -> Guardrail:
    """Raises UnknownGuardrailError if `name` isn't defined in
    config/guardrails.yaml."""
    guardrails = load_guardrails(path)
    if name not in guardrails:
        resolved_path = Path(path) if path is not None else DEFAULT_GUARDRAILS_CONFIG_PATH
        raise UnknownGuardrailError(
            f"No guardrail named '{name}' defined in {resolved_path}. "
            f"Known guardrails: {sorted(guardrails)}"
        )
    return guardrails[name]

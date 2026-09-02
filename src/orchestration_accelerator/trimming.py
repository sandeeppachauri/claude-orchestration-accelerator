"""
trimming.py

Trimming strategy dispatcher for context_mode: session processes (see
.claude/rules/context-mode.md). claude_agent_sdk's ClaudeSDKClient
exposes no API to inspect or mutate its own turn history mid-session --
confirmed against the installed SDK source (client.py's
get_context_usage() is read-only; ConversationResetMessage starts an
entirely fresh conversation, it does not selectively drop old turns).

Because no partial-truncate primitive exists, trimming here is
session-rotation: when a strategy's threshold is crossed, the caller
(core.py's step loop) closes the current ClaudeSDKClient and opens a new
one, seeded with a synthesized system-prompt-level summary of the turns
being dropped, rather than raw resume. This module only decides *when*
to rotate and *what* the summary line says -- it never touches a
ClaudeSDKClient directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_TRIMMING_STRATEGIES = {"turn_count", "token_budget", "none"}


@dataclass
class TrimDecision:
    """Returned by should_trim(). `should_rotate` tells the caller
    whether to close/reopen the ClaudeSDKClient before the next turn;
    `summary` is the system-prompt-level text to seed the new session
    with when should_rotate is True (empty string otherwise)."""

    should_rotate: bool
    summary: str = ""


def _turn_count_strategy(turn_index: int, config: dict[str, Any], **_: Any) -> TrimDecision:
    max_turns = config.get("max_turns", 20)
    if turn_index > 0 and turn_index % max_turns == 0:
        return TrimDecision(
            should_rotate=True,
            summary=(
                f"[Context rotated after {max_turns} turns. Prior conversation "
                f"summary is not available in detail -- continue assisting "
                f"based on the most recent step's input.]"
            ),
        )
    return TrimDecision(should_rotate=False)


def _token_budget_strategy(
    turn_index: int, config: dict[str, Any], current_tokens: int = 0, **_: Any
) -> TrimDecision:
    max_tokens = config.get("max_tokens", 100_000)
    if current_tokens >= max_tokens:
        return TrimDecision(
            should_rotate=True,
            summary=(
                f"[Context rotated after reaching ~{current_tokens} tokens "
                f"(budget: {max_tokens}). Prior conversation summary is not "
                f"available in detail -- continue assisting based on the "
                f"most recent step's input.]"
            ),
        )
    return TrimDecision(should_rotate=False)


def _none_strategy(**_: Any) -> TrimDecision:
    return TrimDecision(should_rotate=False)


_STRATEGIES = {
    "turn_count": _turn_count_strategy,
    "token_budget": _token_budget_strategy,
    "none": _none_strategy,
}


def validate_strategy(strategy: str) -> None:
    if strategy not in VALID_TRIMMING_STRATEGIES:
        raise ValueError(
            f"Unknown trimming strategy {strategy!r}. Must be one of "
            f"{sorted(VALID_TRIMMING_STRATEGIES)}."
        )


def should_trim(
    strategy: str,
    turn_index: int,
    config: dict[str, Any] | None = None,
    current_tokens: int = 0,
) -> TrimDecision:
    """Dispatches to the named strategy's check function. `config` is the
    process's `trimming` block (minus `strategy` itself) -- e.g.
    {"max_turns": 20} for turn_count, {"max_tokens": 100000} for
    token_budget. `current_tokens` is only consulted by token_budget,
    typically sourced from ClaudeSDKClient.get_context_usage()."""
    validate_strategy(strategy)
    return _STRATEGIES[strategy](
        turn_index=turn_index, config=config or {}, current_tokens=current_tokens
    )

from __future__ import annotations


class RateLimitOrOverloadError(Exception):
    """Raised (or caught, when raised by an underlying SDK/client) to signal
    that the current model should be abandoned in favor of the next entry
    in the fallback chain."""


class FallbackChainExhaustedError(Exception):
    """Raised when `model` and every entry in `fallback` have all failed
    with a rate-limit/overload error."""


class AgentProducedNoTextError(Exception):
    """Raised by call_agent_sdk() when a query() run completes without
    ever emitting a TextBlock -- e.g. the model spent its whole max_turns
    budget on tool-call round-trips instead of replying. Surfaced here,
    at the point the empty string is produced, instead of several frames
    later as an opaque json.loads("") "Expecting value" error out of
    PromptManager.validate_output()."""

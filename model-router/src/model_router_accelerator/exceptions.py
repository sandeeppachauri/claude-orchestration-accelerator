from __future__ import annotations


class RateLimitOrOverloadError(Exception):
    """Raised (or caught, when raised by an underlying SDK/client) to signal
    that the current model should be abandoned in favor of the next entry
    in the fallback chain."""


class FallbackChainExhaustedError(Exception):
    """Raised when `model` and every entry in `fallback` have all failed
    with a rate-limit/overload error."""

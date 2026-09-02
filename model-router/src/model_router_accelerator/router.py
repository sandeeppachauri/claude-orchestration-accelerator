"""
router.py

Ordered fallback chain execution: try `model` first, then each entry in
`fallback` in order, on a rate-limit/overload error, with basic backoff.
Backend selection (agent_sdk | messages_api) is purely mechanical --
the caller decides, this module just routes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from orchestration_accelerator.errors import friendly_error

from .backends import BACKENDS
from .exceptions import FallbackChainExhaustedError, RateLimitOrOverloadError

VALID_BACKENDS = frozenset(BACKENDS.keys())


async def _log_fallback_transition(
    session_id: str, fallback_from: str, fallback_to: str, reason: str
) -> None:
    """Logs a WARNING-scope event when the chain falls back from one model
    to the next, before the eventual successful call's own MODEL_CALL_END
    entry -- otherwise a fallback mid-chain is invisible even once the
    final model succeeds. Best-effort, mirrors core.py's
    _log_best_effort() -- a tracing backend outage must never take down
    the fallback chain itself."""
    try:
        from orchestration_accelerator.logging import log

        await log(
            "WARNING",
            session_id,
            0,
            payload={
                "fallback_from": fallback_from,
                "fallback_to": fallback_to,
                "reason": reason,
            },
        )
    except Exception:
        pass


async def execute_with_fallback(
    *,
    model: str,
    fallback: list[str] | None,
    system_prompt: str,
    user_content: str,
    backend: str,
    environment: str = "local",
    base_backoff_seconds: float = 0.1,
    session_id: str = "",
    **backend_kwargs: Any,
) -> dict[str, Any]:
    """Tries `model`, then each entry in `fallback` in order, on a
    RateLimitOrOverloadError. Returns the first successful backend
    call's structured result dict (`text`, `model_used`, `usage`,
    `stop_reason`, `request_id`, `latency_ms`, `session_id`,
    `tool_calls`) unchanged -- this function is a pure pass-through of
    whatever the backend call returns, it does not itself build the
    result shape. Raises FallbackChainExhaustedError if every entry
    fails that way, or propagates any other exception immediately
    (non-rate-limit errors are not retried across the chain)."""
    if backend not in VALID_BACKENDS:
        raise ValueError(
            friendly_error(
                f"The requested execution backend isn't supported -- check "
                f"the `backend` value in your request.",
                f"Unknown backend '{backend}'. Must be one of {sorted(VALID_BACKENDS)}.",
            )
        )
    call = BACKENDS[backend]

    chain = [model] + list(fallback or [])
    last_error: Exception | None = None

    for position, candidate_model in enumerate(chain):
        try:
            return await call(
                model=candidate_model,
                system_prompt=system_prompt,
                user_content=user_content,
                environment=environment,
                **backend_kwargs,
            )
        except RateLimitOrOverloadError as exc:
            last_error = exc
            if position < len(chain) - 1:
                next_model = chain[position + 1]
                await _log_fallback_transition(session_id, candidate_model, next_model, str(exc))
                await asyncio.sleep(base_backoff_seconds * (2**position))
            continue

    raise FallbackChainExhaustedError(
        friendly_error(
            f"The AI service is temporarily overloaded and every configured "
            f"backup model also failed -- this is a transient availability "
            f"issue, not a data or config problem. Wait a moment and retry.",
            f"All {len(chain)} model(s) in the fallback chain {chain} failed "
            f"with rate-limit/overload errors. Last error: {last_error}",
        )
    )

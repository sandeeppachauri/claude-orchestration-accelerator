import pytest

from model_router_accelerator import FallbackChainExhaustedError, execute_with_fallback
from model_router_accelerator.exceptions import RateLimitOrOverloadError
import model_router_accelerator.router as router_module


def make_flaky_call(fail_models: set[str], calls: list[str]):
    """A fake backend call that raises RateLimitOrOverloadError for any
    model in fail_models, else returns a success string."""

    async def _call(*, model, system_prompt, user_content, environment, **kwargs):
        calls.append(model)
        if model in fail_models:
            raise RateLimitOrOverloadError(f"{model} is overloaded (529)")
        return f"ok:{model}"

    return _call


@pytest.mark.parametrize("backend", ["agent_sdk", "messages_api"])
async def test_primary_model_succeeds_no_fallback_needed(monkeypatch, backend):
    calls: list[str] = []
    monkeypatch.setitem(
        router_module.BACKENDS, backend, make_flaky_call(fail_models=set(), calls=calls)
    )
    result = await execute_with_fallback(
        model="claude-haiku-4-5-20251001",
        fallback=["claude-sonnet-5"],
        system_prompt="sys",
        user_content="hi",
        backend=backend,
        base_backoff_seconds=0,
    )
    assert result == "ok:claude-haiku-4-5-20251001"
    assert calls == ["claude-haiku-4-5-20251001"]


@pytest.mark.parametrize("backend", ["agent_sdk", "messages_api"])
async def test_fallback_at_first_position(monkeypatch, backend):
    calls: list[str] = []
    monkeypatch.setitem(
        router_module.BACKENDS,
        backend,
        make_flaky_call(fail_models={"claude-haiku-4-5-20251001"}, calls=calls),
    )
    result = await execute_with_fallback(
        model="claude-haiku-4-5-20251001",
        fallback=["claude-sonnet-5", "claude-opus-4-8"],
        system_prompt="sys",
        user_content="hi",
        backend=backend,
        base_backoff_seconds=0,
    )
    assert result == "ok:claude-sonnet-5"
    assert calls == ["claude-haiku-4-5-20251001", "claude-sonnet-5"]


@pytest.mark.parametrize("backend", ["agent_sdk", "messages_api"])
async def test_fallback_at_last_position(monkeypatch, backend):
    calls: list[str] = []
    monkeypatch.setitem(
        router_module.BACKENDS,
        backend,
        make_flaky_call(
            fail_models={"claude-haiku-4-5-20251001", "claude-sonnet-5"}, calls=calls
        ),
    )
    result = await execute_with_fallback(
        model="claude-haiku-4-5-20251001",
        fallback=["claude-sonnet-5", "claude-opus-4-8"],
        system_prompt="sys",
        user_content="hi",
        backend=backend,
        base_backoff_seconds=0,
    )
    assert result == "ok:claude-opus-4-8"
    assert calls == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-opus-4-8",
    ]


@pytest.mark.parametrize("backend", ["agent_sdk", "messages_api"])
async def test_entire_chain_exhausted_raises(monkeypatch, backend):
    calls: list[str] = []
    monkeypatch.setitem(
        router_module.BACKENDS,
        backend,
        make_flaky_call(
            fail_models={
                "claude-haiku-4-5-20251001",
                "claude-sonnet-5",
                "claude-opus-4-8",
            },
            calls=calls,
        ),
    )
    with pytest.raises(FallbackChainExhaustedError):
        await execute_with_fallback(
            model="claude-haiku-4-5-20251001",
            fallback=["claude-sonnet-5", "claude-opus-4-8"],
            system_prompt="sys",
            user_content="hi",
            backend=backend,
            base_backoff_seconds=0,
        )
    assert len(calls) == 3


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(
            execute_with_fallback(
                model="m",
                fallback=[],
                system_prompt="sys",
                user_content="hi",
                backend="not-a-real-backend",
            )
        )


async def test_non_rate_limit_error_propagates_without_fallback(monkeypatch):
    calls: list[str] = []

    async def _call(*, model, system_prompt, user_content, environment, **kwargs):
        calls.append(model)
        raise ValueError("some unrelated bug")

    monkeypatch.setitem(router_module.BACKENDS, "agent_sdk", _call)

    with pytest.raises(ValueError):
        await execute_with_fallback(
            model="claude-haiku-4-5-20251001",
            fallback=["claude-sonnet-5"],
            system_prompt="sys",
            user_content="hi",
            backend="agent_sdk",
            base_backoff_seconds=0,
        )
    assert calls == ["claude-haiku-4-5-20251001"]

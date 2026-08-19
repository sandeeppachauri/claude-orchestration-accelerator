"""
test_integration.py

End-to-end suite exercising all four accelerators together (auth,
logging, orchestration/prompting+registry, model-router) via execute(),
analogous to ClaudeSDKLoggerAcceleratorTester. Network calls are mocked
by patching the model router's fallback executor -- this suite verifies
composition/wiring, not live model behavior.
"""

import pytest

import project_accelerator.core as core_module
from project_accelerator import execute


@pytest.fixture(autouse=True)
def _patch_logging(monkeypatch):
    async def _fake_log(*args, **kwargs):
        return None

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)


def test_full_ticket_classification_pipeline(monkeypatch):
    calls = []

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        calls.append((model, backend, environment))
        responses = {
            "claude-haiku-4-5-20251001": "technical",
            "claude-sonnet-5": '{"summary": "app crashes on login", "urgency": "medium"}',
            "claude-opus-4-8": "Thanks for reporting -- we are investigating the login crash.",
        }
        return responses[model]

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "input": "The app crashes every time I try to log in.",
            "backend": "agent_sdk",
            "environment": "local",
        }
    )

    assert result["classify"] == "technical"
    assert result["extract"]["urgency"] == "medium"
    assert "login crash" in result["respond"]
    assert len(calls) == 3
    assert all(env == "local" for _, _, env in calls)


def test_onboarding_pipeline_messages_api_backend(monkeypatch):
    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        assert backend == "messages_api"
        responses = {
            "claude-haiku-4-5-20251001": "Welcome aboard!",
            "claude-sonnet-5": "complete",
            "claude-opus-4-8": "Your onboarding is now complete.",
        }
        return responses[model]

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "onboarding",
            "input": "New user Jane Doe, ID docs uploaded.",
            "backend": "messages_api",
        }
    )

    assert result["welcome"] == "Welcome aboard!"
    assert result["verify"] == "complete"
    assert result["finalize"] == "Your onboarding is now complete."


def test_single_step_narrowing_does_not_run_other_steps(monkeypatch):
    calls = []

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        calls.append(model)
        return "billing"

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "double charge",
            "backend": "agent_sdk",
        }
    )
    assert list(result.keys()) == ["classify"]
    assert calls == ["claude-haiku-4-5-20251001"]

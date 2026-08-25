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
    # Keyed by call order (classify, extract, respond -- the registry's
    # `steps` order), not by model: every step in this process is
    # configured to the same claude-haiku-4-5-20251001 model, so a
    # model-keyed fixture couldn't tell the steps apart.
    responses = [
        "technical",
        '{"summary": "app crashes on login", "urgency": "medium"}',
        "Thanks for reporting -- we are investigating the login crash.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        calls.append((model, backend, environment))
        return responses[len(calls) - 1]

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
    calls = []
    # Keyed by call order (welcome, verify, finalize) -- see the
    # ticket-classification test above for why this can't be keyed by
    # model name.
    responses = [
        "Welcome aboard!",
        "complete",
        "Your onboarding is now complete.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        assert backend == "messages_api"
        calls.append(model)
        return responses[len(calls) - 1]

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

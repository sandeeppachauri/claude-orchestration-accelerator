import pytest

import project_accelerator.core as core_module
from project_accelerator import PayloadValidationError, execute


def _patch_router(monkeypatch, response="billing"):
    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        return response

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)


def _patch_logging(monkeypatch):
    async def _fake_log(*args, **kwargs):
        return None

    # patch the module-level lazy import target used inside _run_one_step
    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)


def test_missing_required_key_raises():
    with pytest.raises(PayloadValidationError):
        execute({"process": "ticketClassification", "input": "x"})


def test_invalid_backend_raises():
    with pytest.raises(PayloadValidationError):
        execute(
            {
                "process": "ticketClassification",
                "input": "x",
                "backend": "not-a-backend",
            }
        )


def test_unknown_key_raises():
    with pytest.raises(PayloadValidationError):
        execute(
            {
                "process": "ticketClassification",
                "input": "x",
                "backend": "agent_sdk",
                "unexpected": True,
            }
        )


def test_execute_single_step(monkeypatch):
    _patch_router(monkeypatch, response="billing")
    _patch_logging(monkeypatch)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )
    assert result == {"classify": "billing"}


def test_execute_full_process_runs_all_steps_in_registry_order(monkeypatch):
    _patch_logging(monkeypatch)

    seen_steps = []

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        # Return a value appropriate to whichever step's contract is in force,
        # inferred from the model (keeps this fake simple and step-order-agnostic).
        if model == "claude-haiku-4-5-20251001" and "categor" not in system_prompt.lower():
            pass
        return _RESPONSES_BY_MODEL.get(model, "billing")

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )
    assert list(result.keys()) == ["classify", "extract", "respond"]


_RESPONSES_BY_MODEL = {
    "claude-haiku-4-5-20251001": "billing",
    "claude-sonnet-5": '{"summary": "double charge", "urgency": "high"}',
    "claude-opus-4-8": "We're sorry for the double charge and are looking into it.",
}


def test_default_configuration_fallback_for_undefined_process(monkeypatch):
    _patch_router(monkeypatch, response="anything goes")
    _patch_logging(monkeypatch)

    result = execute(
        {
            "process": "someUndefinedProcess",
            "input": "hello",
            "backend": "agent_sdk",
        }
    )
    assert result == {"someUndefinedProcess": "anything goes"}

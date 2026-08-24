import pytest

import project_accelerator.core as core_module
from orchestration_accelerator.registry import UnsupportedCapabilityError
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


def test_execute_dict_input_renders_placeholders(monkeypatch):
    _patch_logging(monkeypatch)

    seen = {}

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        seen["system_prompt"] = system_prompt
        seen["user_content"] = user_content
        return "ok"

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "templatingDemo",
            "step": "triage",
            "input": {
                "ticket_id": "T-1",
                "customer_name": "Ada",
                "customer_tier": "gold",
                "body": "My invoice is wrong",
            },
            "backend": "agent_sdk",
        }
    )
    assert result == {"triage": "ok"}
    assert "gold-tier" in seen["system_prompt"]
    assert "T-1" in seen["user_content"]
    assert "Ada" in seen["user_content"]


def test_execute_dict_input_missing_key_raises(monkeypatch):
    _patch_logging(monkeypatch)
    _patch_router(monkeypatch)

    with pytest.raises(Exception):
        execute(
            {
                "process": "templatingDemo",
                "step": "triage",
                "input": {"ticket_id": "T-1"},
                "backend": "agent_sdk",
            }
        )


def test_escalate_step_capabilities_are_agent_sdk_whitelisted(monkeypatch):
    """templatingDemo.escalate's live capability keys (max_turns,
    permission_mode, thinking) must all be agent_sdk-whitelisted, since
    sample_usage.py's TicketEscalator calls it with backend="agent_sdk"."""
    _patch_logging(monkeypatch)
    _patch_router(
        monkeypatch,
        response='{"escalate": true, "urgency": "high", "reason": "SLA breach imminent"}',
    )

    result = execute(
        {
            "process": "templatingDemo",
            "step": "escalate",
            "input": {
                "ticket_id": "T-9",
                "customer_name": "Grace",
                "customer_tier": "free",
                "account_history": "2 prior tickets",
                "sla_minutes_remaining": "15",
                "body": "Site is down",
            },
            "backend": "agent_sdk",
        }
    )
    assert result == {
        "escalate": {"escalate": True, "urgency": "high", "reason": "SLA breach imminent"}
    }


def test_unwhitelisted_capability_key_raises_before_model_call(monkeypatch):
    """A capability key not in capability_registry.yaml's allowed set for
    the chosen backend must fail fast, before execute_with_fallback is
    ever called -- not surface as a TypeError deep inside the SDK."""
    called = False

    async def _fake_execute_with_fallback(**kwargs):
        nonlocal called
        called = True
        return "should not run"

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)
    _patch_logging(monkeypatch)

    with pytest.raises(UnsupportedCapabilityError):
        execute(
            {
                "process": "templatingDemo",
                "step": "escalate",
                "input": {
                    "ticket_id": "T-9",
                    "customer_name": "Grace",
                    "customer_tier": "free",
                    "account_history": "2 prior tickets",
                    "sla_minutes_remaining": "15",
                    "body": "Site is down",
                },
                # escalate's live keys (max_turns, permission_mode) are
                # agent_sdk-only -- running it as messages_api must fail.
                "backend": "messages_api",
            }
        )
    assert called is False


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

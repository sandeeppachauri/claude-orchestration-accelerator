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


def _patch_logging_capture(monkeypatch):
    """Like _patch_logging, but records every call so a test can assert
    on scope/fields instead of just swallowing them."""
    calls = []

    async def _fake_log(scope, session_id, turn_index=0, **fields):
        calls.append({"scope": scope, "turn_index": turn_index, **fields})

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)
    return calls


def test_missing_required_key_raises():
    with pytest.raises(PayloadValidationError):
        execute({"process": "ticketClassification", "input": "x"})


def test_missing_required_key_error_is_friendly_and_technical():
    with pytest.raises(PayloadValidationError) as excinfo:
        execute({"process": "ticketClassification", "input": "x"})
    message = str(excinfo.value)
    # Every accelerator exception carries a plain-English summary AND the
    # exact technical detail (see orchestration_accelerator.errors) --
    # a functional user and an engineer can both act on the same message.
    assert "Technical detail:" in message
    assert "missing required key" in message


def test_missing_required_key_logs_error_scope(monkeypatch):
    calls = _patch_logging_capture(monkeypatch)
    with pytest.raises(PayloadValidationError):
        execute({"process": "ticketClassification", "input": "x"})
    error_calls = [c for c in calls if c["scope"] == "ERROR"]
    assert len(error_calls) == 1
    assert error_calls[0]["payload"]["error_type"] == "PayloadValidationError"


def test_step_failure_logs_error_scope_not_full_turn(monkeypatch):
    calls = _patch_logging_capture(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    with pytest.raises(ValueError):
        execute(
            {
                "process": "ticketClassification",
                "step": "classify",
                "input": "x",
                "backend": "agent_sdk",
            }
        )

    assert [c["scope"] for c in calls] == ["MODEL_CALL_START", "ERROR"]
    assert calls[1]["payload"]["step"] == "classify"
    assert calls[1]["payload"]["error_type"] == "ValueError"


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

    calls = []
    # Keyed by call order (classify, extract, respond) -- every step in
    # this process is configured to the same claude-haiku-4-5-20251001
    # model, so a model-keyed fixture couldn't tell the steps apart.
    responses = [
        "billing",
        '{"summary": "double charge", "urgency": "high"}',
        "We're sorry for the double charge and are looking into it.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        calls.append(model)
        return responses[len(calls) - 1]

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )
    assert list(result.keys()) == ["classify", "extract", "respond"]


def test_execute_multi_field_dict_input_survives_across_steps(monkeypatch):
    """templatingDemo-style regression: `escalate` needs the same named
    dossier fields `triage` used, plus `triage_output` -- collapsing
    input_data into a single `input` key would strand those fields."""
    _patch_logging(monkeypatch)

    seen_user_content = []
    responses = ["escalate to billing team", '{"escalate": true, "urgency": "high", "reason": "gold tier, SLA breach imminent"}']

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        seen_user_content.append(user_content)
        return responses[len(seen_user_content) - 1]

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "templatingDemo",
            "input": {
                "ticket_id": "T-1",
                "customer_name": "Ada",
                "customer_tier": "gold",
                "body": "My invoice is wrong",
                "account_history": "3 prior tickets, no refunds issued",
                "sla_minutes_remaining": 45,
            },
            "backend": "agent_sdk",
        }
    )

    # escalate step's rendered user turn must still contain every original
    # dossier field, not just "input" + "triage_output".
    escalate_user_content = seen_user_content[1]
    assert "T-1" in escalate_user_content
    assert "Ada" in escalate_user_content
    assert "gold" in escalate_user_content
    assert "My invoice is wrong" in escalate_user_content
    assert "3 prior tickets, no refunds issued" in escalate_user_content
    assert "45" in escalate_user_content


def test_execute_full_process_threads_prior_step_outputs(monkeypatch):
    _patch_logging(monkeypatch)

    seen_user_content = []
    responses = [
        "billing",
        '{"summary": "double charge", "urgency": "high"}',
        "We're sorry for the double charge and are looking into it.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        seen_user_content.append(user_content)
        return responses[len(seen_user_content) - 1]

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "ticketClassification",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )

    # classify: legacy plain-string path, unaffected by threading.
    assert seen_user_content[0] == "I was double charged"
    # extract: must see classify's output plus the original ticket text.
    assert "billing" in seen_user_content[1]
    assert "I was double charged" in seen_user_content[1]
    # respond: must see both classify's and extract's outputs plus the
    # original ticket text -- this is the exact data classify_soa.yaml's
    # system_prompt tells the model it will have.
    assert "billing" in seen_user_content[2]
    assert "double charge" in seen_user_content[2]
    assert "I was double charged" in seen_user_content[2]


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

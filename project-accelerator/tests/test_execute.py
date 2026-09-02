import pytest

import project_accelerator.core as core_module
from orchestration_accelerator.registry import UnsupportedCapabilityError
from project_accelerator import PayloadValidationError, execute


def _result(text, **overrides):
    base = {
        "text": text,
        "model_used": "claude-haiku-4-5-20251001",
        "usage": {},
        "stop_reason": "end_turn",
        "request_id": None,
        "latency_ms": 0.0,
        "session_id": None,
        "tool_calls": [],
    }
    base.update(overrides)
    return base


def _patch_router(monkeypatch, response="billing"):
    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        return _result(response, model_used=model)

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
    assert result["classify"]["output"] == "billing"


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
        return _result(responses[len(calls) - 1], model_used=model)

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
        return _result(responses[len(seen_user_content) - 1], model_used=model)

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
    # triage's output must also be threaded in via {{triage_output}}.
    assert "escalate to billing team" in escalate_user_content


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
        return _result(responses[len(seen_user_content) - 1], model_used=model)

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
        return _result("ok", model_used=model)

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
    assert result["triage"]["output"] == "ok"
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
                "triage_output": "Category: technical. Urgency: high.",
            },
            "backend": "agent_sdk",
        }
    )
    assert result["escalate"]["output"] == {
        "escalate": True,
        "urgency": "high",
        "reason": "SLA breach imminent",
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
    assert result["someUndefinedProcess"]["output"] == "anything goes"


def test_execute_returns_structured_result_with_usage_and_stop_reason(monkeypatch):
    """Part B: results[step] is a dict carrying output plus model call
    metadata, not a bare string -- proves no information loss, only
    relocation, from the pre-Part-B contract."""
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        return _result(
            "billing",
            model_used="claude-sonnet-5",
            usage={"input_tokens": 12, "output_tokens": 3},
            stop_reason="end_turn",
            latency_ms=42.5,
        )

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )
    step_result = result["classify"]
    assert step_result["output"] == "billing"
    assert step_result["model_used"] == "claude-sonnet-5"
    assert step_result["stop_reason"] == "end_turn"
    assert step_result["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert step_result["latency_ms"] == 42.5
    assert step_result["tool_calls"] == []
    assert step_result["request_id"] is None


def test_threading_pulls_output_field_not_whole_dict(monkeypatch):
    """The {{<stepName>_output}} placeholder must thread the prior step's
    text output, not a stringified dict -- the one spot Part B's plan
    flagged as able to silently corrupt output if missed."""
    _patch_logging(monkeypatch)

    seen_user_content = []
    responses = [
        "billing",
        '{"summary": "double charge", "urgency": "high"}',
        "We're sorry for the double charge and are looking into it.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        seen_user_content.append(user_content)
        return _result(responses[len(seen_user_content) - 1], model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "ticketClassification",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )

    assert "billing" in seen_user_content[1]
    assert "{'output'" not in seen_user_content[1]
    assert "model_used" not in seen_user_content[1]


def test_assistant_prompt_on_agent_sdk_raises_before_model_call(monkeypatch):
    called = False

    async def _fake_execute_with_fallback(**kwargs):
        nonlocal called
        called = True
        return _result("should not run")

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)
    _patch_logging(monkeypatch)

    with pytest.raises(UnsupportedCapabilityError):
        execute(
            {
                "process": "fewshotLabeling",
                "step": "label",
                "input": {"ticket_text": "hello"},
                "backend": "agent_sdk",
            }
        )
    assert called is False


def test_assistant_prompt_on_messages_api_passes_through(monkeypatch):
    _patch_logging(monkeypatch)
    seen = {}

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        seen["assistant_prompt"] = kwargs.get("assistant_prompt")
        return _result("billing-label", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "fewshotLabeling",
            "step": "label",
            "input": {"ticket_text": "hello"},
            "backend": "messages_api",
        }
    )
    assert result["label"]["output"] == "billing-label"
    assert seen["assistant_prompt"] is not None
    assert "billing-duplicate-charge" in seen["assistant_prompt"]


def test_stream_true_step_invokes_on_chunk_with_step_name(monkeypatch):
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, on_chunk=None, **kwargs):
        if on_chunk is not None:
            await on_chunk("Hello ")
            await on_chunk("world")
        return _result("Hello world", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    received = []

    def on_chunk(step_name, chunk):
        received.append((step_name, chunk))

    result = execute(
        {
            "process": "streamingDemo",
            "step": "narrate",
            "input": {"scenario": "a login bug"},
            "backend": "messages_api",
            "on_chunk": on_chunk,
        }
    )
    assert received == [("narrate", "Hello "), ("narrate", "world")]
    assert result["narrate"]["output"] == "Hello world"


def test_stream_true_step_with_no_on_chunk_still_works(monkeypatch):
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, on_chunk=None, **kwargs):
        assert on_chunk is None
        return _result("Hello world", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "streamingDemo",
            "step": "narrate",
            "input": {"scenario": "a login bug"},
            "backend": "messages_api",
        }
    )
    assert result["narrate"]["output"] == "Hello world"


def test_non_stream_step_does_not_receive_on_chunk(monkeypatch):
    """A step with no stream: true must not be wired with a step-level
    on_chunk wrapper, even when the payload supplies one -- only
    stream: true steps opt in."""
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, on_chunk=None, **kwargs):
        assert on_chunk is None
        return _result("billing", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "I was double charged",
            "backend": "agent_sdk",
            "on_chunk": lambda step_name, chunk: None,
        }
    )


def test_streaming_cross_step_receives_full_text_via_threading(monkeypatch):
    """Part D's 'full text only' decision: a later step's
    {{stepName_output}} placeholder must receive step 1's fully
    assembled text, not chunks -- streaming is purely a side-channel
    emission, not a new data shape flowing between steps."""
    _patch_logging(monkeypatch)

    seen_user_content = []
    responses = [
        "billing",
        '{"summary": "double charge", "urgency": "high"}',
        "We're sorry for the double charge and are looking into it.",
    ]

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, on_chunk=None, **kwargs):
        seen_user_content.append(user_content)
        return _result(responses[len(seen_user_content) - 1], model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "ticketClassification",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )

    assert "billing" in seen_user_content[1]

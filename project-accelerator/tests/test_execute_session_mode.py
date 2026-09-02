"""
test_execute_session_mode.py

Covers context_mode: session's execute() path (see
.claude/rules/context-mode.md) -- opening/reusing one ClaudeSDKClient
across all steps of a call, cross-call resume via payload["session_id"],
the messages_api restriction, and mirror_error logging. Mocks
open_agent_sdk_session()/run_session_turn() at the module level core.py
imports them from -- no real claude_agent_sdk network/process calls.
"""

import pytest

import project_accelerator.core as core_module
from orchestration_accelerator.registry import UnsupportedCapabilityError
from project_accelerator import execute


def _patch_logging(monkeypatch):
    async def _fake_log(*args, **kwargs):
        return None

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)


def _patch_logging_capture(monkeypatch):
    calls = []

    async def _fake_log(scope, session_id, turn_index=0, **fields):
        calls.append({"scope": scope, "turn_index": turn_index, **fields})

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)
    return calls


class _FakeClient:
    def __init__(self):
        self.disconnected = False
        self.queries = []

    async def disconnect(self):
        self.disconnected = True


def _patch_session_backend(monkeypatch, responses=None, capture_opens=None):
    """responses: list of text strings returned in turn order. capture_opens:
    a list appended with each open_agent_sdk_session() call's kwargs, so
    tests can assert resume=/session_store= were passed correctly."""
    responses = responses or ["intake response", "diagnose response"]
    clients_opened = []

    async def _fake_open(**kwargs):
        if capture_opens is not None:
            capture_opens.append(kwargs)
        client = _FakeClient()
        clients_opened.append(client)
        return client

    call_count = {"n": 0}

    async def _fake_run_turn(client, user_content, model, on_mirror_error=None):
        idx = call_count["n"]
        call_count["n"] += 1
        text = responses[idx] if idx < len(responses) else responses[-1]
        return {
            "text": text,
            "model_used": model,
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "stop_reason": "end_turn",
            "request_id": None,
            "latency_ms": 1.0,
            "session_id": "sess-abc",
            "tool_calls": [],
        }

    monkeypatch.setattr(core_module, "open_agent_sdk_session", _fake_open)
    monkeypatch.setattr(core_module, "run_session_turn", _fake_run_turn)
    return clients_opened


def test_session_mode_runs_every_step_on_same_client(monkeypatch):
    _patch_logging(monkeypatch)
    clients_opened = _patch_session_backend(monkeypatch)

    result = execute(
        {
            "process": "supportSession",
            "input": "My app crashes on login.",
            "backend": "agent_sdk",
        }
    )

    assert list(result.keys()) == ["intake", "diagnose"]
    assert result["intake"]["output"] == "intake response"
    assert result["diagnose"]["output"] == "diagnose response"
    # Only one client opened -- both steps ran on it, not a fresh one each.
    assert len(clients_opened) == 1
    assert clients_opened[0].disconnected is True


def test_session_mode_result_includes_session_id(monkeypatch):
    _patch_logging(monkeypatch)
    _patch_session_backend(monkeypatch)

    result = execute(
        {
            "process": "supportSession",
            "input": "My app crashes on login.",
            "backend": "agent_sdk",
        }
    )
    assert result["diagnose"]["session_id"] == "sess-abc"


def test_session_mode_cross_call_resume_passes_session_id(monkeypatch):
    _patch_logging(monkeypatch)
    opens = []
    _patch_session_backend(monkeypatch, capture_opens=opens)

    execute(
        {
            "process": "supportSession",
            "step": "diagnose",
            "input": "Follow-up detail.",
            "backend": "agent_sdk",
            "session_id": "sess-from-earlier-call",
        }
    )

    assert opens[0]["resume"] == "sess-from-earlier-call"


def test_session_mode_fresh_call_has_no_resume(monkeypatch):
    _patch_logging(monkeypatch)
    opens = []
    _patch_session_backend(monkeypatch, capture_opens=opens)

    execute(
        {
            "process": "supportSession",
            "input": "First contact.",
            "backend": "agent_sdk",
        }
    )
    assert opens[0]["resume"] is None


def test_session_mode_passes_resolved_session_store(monkeypatch):
    _patch_logging(monkeypatch)
    opens = []
    _patch_session_backend(monkeypatch, capture_opens=opens)

    execute(
        {
            "process": "supportSession",
            "input": "First contact.",
            "backend": "agent_sdk",
        }
    )
    from claude_agent_sdk import InMemorySessionStore

    assert isinstance(opens[0]["session_store"], InMemorySessionStore)


def test_session_mode_with_messages_api_raises_before_any_call(monkeypatch):
    _patch_logging(monkeypatch)
    opens = []

    async def _fake_open(**kwargs):
        opens.append(kwargs)
        return _FakeClient()

    monkeypatch.setattr(core_module, "open_agent_sdk_session", _fake_open)

    with pytest.raises(UnsupportedCapabilityError):
        execute(
            {
                "process": "supportSession",
                "input": "hello",
                "backend": "messages_api",
            }
        )
    assert opens == []


def test_session_mode_logs_model_call_end_with_metadata(monkeypatch):
    calls = _patch_logging_capture(monkeypatch)
    _patch_session_backend(monkeypatch)

    execute(
        {
            "process": "supportSession",
            "input": "My app crashes on login.",
            "backend": "agent_sdk",
        }
    )

    end_calls = [c for c in calls if c["scope"] == "MODEL_CALL_END"]
    assert len(end_calls) == 2
    assert end_calls[0]["metadata"]["usage"] == {"input_tokens": 5, "output_tokens": 2}
    assert end_calls[0]["metadata"]["session_id"] == "sess-abc"


def test_session_mode_mirror_error_logs_warning(monkeypatch):
    calls = _patch_logging_capture(monkeypatch)

    async def _fake_open(**kwargs):
        return _FakeClient()

    async def _fake_run_turn(client, user_content, model, on_mirror_error=None):
        if on_mirror_error is not None:
            await on_mirror_error("append failed: disk full", "session-key-123")
        return {
            "text": "ok",
            "model_used": model,
            "usage": {},
            "stop_reason": "end_turn",
            "request_id": None,
            "latency_ms": 1.0,
            "session_id": "sess-abc",
            "tool_calls": [],
        }

    monkeypatch.setattr(core_module, "open_agent_sdk_session", _fake_open)
    monkeypatch.setattr(core_module, "run_session_turn", _fake_run_turn)

    execute(
        {
            "process": "supportSession",
            "step": "intake",
            "input": "hello",
            "backend": "agent_sdk",
        }
    )

    warnings = [c for c in calls if c["scope"] == "WARNING"]
    assert len(warnings) == 1
    assert warnings[0]["payload"]["mirror_error"] == "append failed: disk full"

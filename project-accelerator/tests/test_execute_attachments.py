"""
test_execute_attachments.py

execute()-level wiring for the `attachments` payload key -- see
.claude/rules/attachments.md. Complements model-router's
test_attachments.py (which exercises call_messages_api()/
call_agent_sdk() directly) by proving attachments actually reach
execute_with_fallback() from execute()'s payload, and that
result["uploaded_file_ids"] surfaces correctly.
"""

import project_accelerator.core as core_module
from project_accelerator import execute


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
        "uploaded_file_ids": [],
    }
    base.update(overrides)
    return base


def _patch_logging(monkeypatch):
    async def _fake_log(*args, **kwargs):
        return None

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)


def test_attachments_key_is_passed_through_to_execute_with_fallback(monkeypatch):
    """attachments must reach execute_with_fallback() as its own explicit
    kwarg, separate from capability passthrough."""
    _patch_logging(monkeypatch)
    captured = {}

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, attachments=None, **kwargs
    ):
        captured["attachments"] = attachments
        return _result("billing", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    attachments = [{"file_id": "file_001", "kind": "document"}]
    execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "x",
            "backend": "agent_sdk",
            "attachments": attachments,
        }
    )

    assert captured["attachments"] == attachments


def test_no_attachments_key_execute_with_fallback_receives_none(monkeypatch):
    """Regression: a payload with no `attachments` key at all must call
    execute_with_fallback(attachments=None) -- the exact same call shape
    as before attachments existed, proving the no-attachments request
    path is unaffected end-to-end through execute()."""
    _patch_logging(monkeypatch)
    captured = {}

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, attachments=None, **kwargs
    ):
        captured["attachments"] = attachments
        return _result("billing", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "x",
            "backend": "agent_sdk",
        }
    )

    assert captured["attachments"] is None


def test_attachments_key_accepted_as_optional_payload_key():
    """`attachments` is a known optional payload key -- it must not raise
    PayloadValidationError's "unknown key" check the way an unrelated
    unexpected key would."""
    assert "attachments" in core_module.OPTIONAL_PAYLOAD_KEYS


def test_result_includes_uploaded_file_ids(monkeypatch):
    """execute()'s result dict must surface uploaded_file_ids from the
    backend call result."""
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        return _result("billing", model_used=model, uploaded_file_ids=["file_auto_001"])

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "x",
            "backend": "agent_sdk",
            "attachments": [{"path": "some/local/path.txt", "kind": "document"}],
        }
    )

    assert result["classify"]["uploaded_file_ids"] == ["file_auto_001"]


def test_result_uploaded_file_ids_defaults_empty_without_attachments(monkeypatch):
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(*, model, fallback, system_prompt, user_content, backend, environment, **kwargs):
        return _result("billing", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "x",
            "backend": "agent_sdk",
        }
    )

    assert result["classify"]["uploaded_file_ids"] == []

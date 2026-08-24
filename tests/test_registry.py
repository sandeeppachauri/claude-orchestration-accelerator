import os

import pytest

from orchestration_accelerator.registry import (
    ProcessNotFoundError,
    UnsupportedCapabilityError,
    get_allowed_capabilities,
    get_default_step_config,
    get_process,
    validate_capabilities,
)


def test_get_ticket_classification():
    process = get_process("ticketClassification")
    assert process["id"] == "ticketClassification_01"
    assert process["steps"] == ["classify", "extract", "respond"]
    assert process["step_config"]["classify"]["model"] == "claude-haiku-4-5-20251001"
    assert process["step_config"]["extract"]["fallback"] == ["claude-haiku-4-5-20251001"]


def test_get_onboarding():
    process = get_process("onboarding")
    assert process["steps"] == ["welcome", "verify", "finalize"]
    assert process["step_config"]["verify"]["prompt"] == "verify_kyc.yaml"


def test_unknown_process_raises():
    with pytest.raises(ProcessNotFoundError):
        get_process("does-not-exist")


def test_default_step_config_uses_env_default_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "claude-sonnet-5")
    cfg = get_default_step_config()
    assert cfg["model"] == "claude-sonnet-5"
    assert cfg["fallback"] == []
    assert cfg["system_prompt"]


def test_default_step_config_falls_back_when_env_unset(monkeypatch):
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    cfg = get_default_step_config()
    assert cfg["model"] == "claude-sonnet-5"


def test_get_allowed_capabilities_agent_sdk():
    allowed = get_allowed_capabilities("agent_sdk")
    assert "max_turns" in allowed
    assert "thinking" in allowed
    assert "temperature" not in allowed


def test_get_allowed_capabilities_messages_api():
    allowed = get_allowed_capabilities("messages_api")
    assert "temperature" in allowed
    assert "max_turns" not in allowed


def test_get_allowed_capabilities_unknown_backend_is_empty():
    assert get_allowed_capabilities("does-not-exist") == set()


def test_validate_capabilities_allows_whitelisted_keys():
    validate_capabilities({"max_turns": 3, "thinking": {}}, "agent_sdk")


def test_validate_capabilities_rejects_wrong_backend_key():
    with pytest.raises(UnsupportedCapabilityError):
        validate_capabilities({"temperature": 0.2}, "agent_sdk")


def test_validate_capabilities_rejects_unknown_key():
    with pytest.raises(UnsupportedCapabilityError):
        validate_capabilities({"not_a_real_key": 1}, "messages_api")

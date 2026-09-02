import os

import pytest

from orchestration_accelerator.registry import (
    InvalidContextModeError,
    ProcessNotFoundError,
    SessionStoreResolutionError,
    UnsupportedCapabilityError,
    get_allowed_capabilities,
    get_default_step_config,
    get_process,
    resolve_session_store,
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


def test_get_process_default_context_mode_is_threaded():
    process = get_process("ticketClassification")
    assert process["context_mode"] == "threaded"
    assert process["trimming"] is None
    assert process["session_store"] is None


def test_get_process_reads_context_mode_session():
    process = get_process("supportSession")
    assert process["context_mode"] == "session"
    assert process["trimming"] == {"strategy": "turn_count", "max_turns": 20}
    assert process["session_store"] == {"backend": "memory"}
    assert process["steps"] == ["intake", "diagnose"]


def test_invalid_context_mode_raises(tmp_path):
    bad_registry = tmp_path / "process_registry.yaml"
    bad_registry.write_text(
        "badProcess:\n"
        "  id: badProcess_01\n"
        "  context_mode: not_a_real_mode\n"
        "  steps: [only]\n"
        "  only: {prompt: classify.yaml, model: m, fallback: []}\n"
    )
    with pytest.raises(InvalidContextModeError):
        get_process("badProcess", path=bad_registry)


def test_resolve_session_store_none_when_omitted():
    assert resolve_session_store(None) is None


def test_resolve_session_store_memory_backend():
    from claude_agent_sdk import InMemorySessionStore

    store = resolve_session_store({"backend": "memory"})
    assert isinstance(store, InMemorySessionStore)


def test_resolve_session_store_custom_backend_calls_factory(tmp_path, monkeypatch):
    import sys
    import types

    module = types.ModuleType("fake_store_module")
    sentinel = object()
    module.build_store = lambda: sentinel
    sys.modules["fake_store_module"] = module
    try:
        store = resolve_session_store(
            {"backend": "custom", "factory": "fake_store_module:build_store"}
        )
        assert store is sentinel
    finally:
        del sys.modules["fake_store_module"]


def test_resolve_session_store_custom_backend_missing_factory_raises():
    with pytest.raises(SessionStoreResolutionError):
        resolve_session_store({"backend": "custom"})


@pytest.mark.parametrize("backend", ["s3", "redis", "postgres"])
def test_resolve_session_store_copy_in_yourself_backends_raise_clear_error(backend):
    with pytest.raises(SessionStoreResolutionError) as excinfo:
        resolve_session_store({"backend": backend})
    assert "context-mode.md" in str(excinfo.value)


def test_resolve_session_store_unknown_backend_raises():
    with pytest.raises(SessionStoreResolutionError):
        resolve_session_store({"backend": "not-a-real-backend"})

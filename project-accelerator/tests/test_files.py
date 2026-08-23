import sys
import types

from project_accelerator import upload_file


def test_upload_file_agent_sdk_returns_local_path(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = upload_file(f, environment="local", backend="agent_sdk")
    assert result == str(f.resolve())


def test_upload_file_resolves_environment(tmp_path, monkeypatch):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    captured = {}

    class FakeFiles:
        def create(self, file, purpose):
            return type("R", (), {"id": "file_abc"})()

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.files = FakeFiles()

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    def _fake_build_api_credential(environment):
        captured["environment"] = environment
        return "sk-staging"

    fake_auth = types.SimpleNamespace(build_api_credential=_fake_build_api_credential)
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)

    result = upload_file(f, backend="messages_api")
    assert result == "file_abc"
    assert captured["environment"] == "staging"
    assert captured["api_key"] == "sk-staging"

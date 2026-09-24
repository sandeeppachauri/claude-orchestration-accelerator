import sys
import types

from project_accelerator import upload_file


def test_upload_file_agent_sdk_returns_local_path(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = upload_file(f, environment="local", backend="agent_sdk")
    assert result == str(f.resolve())


def test_upload_file_resolves_environment(tmp_path, monkeypatch):
    """Autospec against the real `anthropic.resources.files.Files` class --
    a renamed/removed method (e.g. the pre-GA `files.create`) raises
    AttributeError here instead of silently passing like the old
    hand-rolled FakeFiles/FakeClient fakes did."""
    from unittest.mock import create_autospec

    from anthropic.resources.files import Files

    f = tmp_path / "doc.txt"
    f.write_text("hello")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    captured = {}

    files_mock = create_autospec(Files, instance=True)
    files_mock.upload.return_value = type("R", (), {"id": "file_abc"})()

    fake_client = types.SimpleNamespace(files=files_mock)

    def _fake_anthropic_ctor(api_key, base_url=None):
        captured["api_key"] = api_key
        return fake_client

    fake_anthropic = types.SimpleNamespace(Anthropic=_fake_anthropic_ctor)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    def _fake_build_api_credential(environment):
        captured["environment"] = environment
        return "sk-staging"

    fake_auth = types.SimpleNamespace(
        build_api_credential=_fake_build_api_credential,
        build_base_url=lambda environment: None,
    )
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)

    result = upload_file(f, backend="messages_api")
    assert result == "file_abc"
    assert captured["environment"] == "staging"
    assert captured["api_key"] == "sk-staging"
    # GA files.upload() has no `purpose` kwarg -- proves the call site
    # was fixed to drop it, not just renamed create->upload.
    assert "purpose" not in files_mock.upload.call_args.kwargs

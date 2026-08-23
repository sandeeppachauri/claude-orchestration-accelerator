from pathlib import Path

import pytest

from orchestration_accelerator.file import FileManager, FileUploadError, upload_file


def test_agent_sdk_upload_returns_local_path(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    manager = FileManager(environment="local")
    result = manager.upload(f, backend="agent_sdk")
    assert result == str(f.resolve())


def test_upload_missing_file_raises():
    manager = FileManager(environment="local")
    with pytest.raises(FileUploadError):
        manager.upload("does-not-exist.txt", backend="agent_sdk")


def test_upload_unsupported_backend_raises(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    manager = FileManager(environment="local")
    with pytest.raises(FileUploadError):
        manager.upload(f, backend="not-a-backend")


def test_messages_api_upload_uses_auth_and_anthropic_client(tmp_path, monkeypatch):
    f = tmp_path / "doc.txt"
    f.write_text("hello")

    class FakeFiles:
        def create(self, file, purpose):
            assert purpose == "user_data"
            return type("R", (), {"id": "file_123"})()

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "sk-test"
            self.files = FakeFiles()

    import sys
    import types

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    fake_auth = types.SimpleNamespace(build_api_credential=lambda environment: "sk-test")
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)

    manager = FileManager(environment="local")
    result = manager.upload(f, backend="messages_api")
    assert result == "file_123"


def test_module_level_upload_file_delegates(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = upload_file(f, environment="local", backend="agent_sdk")
    assert result == str(f.resolve())

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


def _autospec_files_client(monkeypatch, files_mock):
    """Builds a fake `anthropic` module whose `Anthropic(...)` constructor
    returns an object with `.files` set to `files_mock` -- an autospec of
    the real `anthropic.resources.files.Files` class, so a call to a
    renamed/removed/resignatured method raises AttributeError/TypeError
    instead of silently succeeding like the old hand-rolled FakeFiles did."""
    import sys
    import types

    fake_client = types.SimpleNamespace(files=files_mock)
    fake_anthropic_module = types.SimpleNamespace(
        Anthropic=lambda api_key, base_url=None: fake_client
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)
    monkeypatch.setitem(
        sys.modules,
        "auth_accelerator",
        types.SimpleNamespace(
            build_api_credential=lambda environment: "sk-test",
            build_base_url=lambda environment: None,
        ),
    )


def test_messages_api_upload_uses_auth_and_anthropic_client(tmp_path, monkeypatch):
    """Autospec against the real installed `anthropic.resources.files.Files`
    class -- if `upload`/`retrieve_metadata` are ever renamed again, or
    `upload`'s real keyword-only signature changes, this raises
    AttributeError/TypeError instead of silently passing."""
    from unittest.mock import create_autospec

    from anthropic.resources.files import Files

    f = tmp_path / "doc.txt"
    f.write_text("hello")

    files_mock = create_autospec(Files, instance=True)
    files_mock.upload.return_value = type("R", (), {"id": "file_123"})()
    _autospec_files_client(monkeypatch, files_mock)

    manager = FileManager(environment="local")
    result = manager.upload(f, backend="messages_api")
    assert result == "file_123"
    files_mock.upload.assert_called_once()
    # GA files.upload() has no `purpose` kwarg -- passing it would raise
    # TypeError against the real autospec'd signature, so this call
    # succeeding proves the fix (dropping `purpose`) actually took.
    assert "purpose" not in files_mock.upload.call_args.kwargs


def test_retrieve_metadata_uses_real_ga_method_name(monkeypatch):
    """Guards against the pre-GA `files.retrieve` name creeping back in --
    `retrieve` doesn't exist on the real Files class, so calling it against
    the autospec would raise AttributeError."""
    from unittest.mock import create_autospec

    from anthropic.resources.files import Files

    files_mock = create_autospec(Files, instance=True)
    files_mock.retrieve_metadata.return_value = type("R", (), {"id": "file_123"})()
    _autospec_files_client(monkeypatch, files_mock)

    manager = FileManager(environment="local")
    result = manager.retrieve_metadata("file_123")
    assert result.id == "file_123"
    files_mock.retrieve_metadata.assert_called_once_with("file_123")

    # deprecated alias still works, delegating to the same GA method
    files_mock.retrieve_metadata.reset_mock()
    result = manager.retrieve("file_123")
    assert result.id == "file_123"
    files_mock.retrieve_metadata.assert_called_once_with("file_123")


def test_module_level_upload_file_delegates(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = upload_file(f, environment="local", backend="agent_sdk")
    assert result == str(f.resolve())

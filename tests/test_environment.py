from orchestration_accelerator.environment import resolve_environment


def test_payload_value_wins(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert resolve_environment("dev") == "dev"


def test_falls_back_to_hardcoded_local(monkeypatch, tmp_path):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    # no .env in this empty tmp dir
    assert resolve_environment(None, dotenv_path=tmp_path / ".env") == "local"


def test_dotenv_value_used_when_no_payload(monkeypatch, tmp_path):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("ENVIRONMENT=dev\n")
    assert resolve_environment(None, dotenv_path=dotenv_file) == "dev"

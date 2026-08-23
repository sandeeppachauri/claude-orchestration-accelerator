import sys
import types

from project_accelerator import execute_batch


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeResult:
    def __init__(self, text):
        self.type = "succeeded"
        self.message = _FakeMessage(text)


class _FakeResultEntry:
    def __init__(self, custom_id, text):
        self.custom_id = custom_id
        self.result = _FakeResult(text)


class _FakeBatch:
    def __init__(self, id_):
        self.id = id_
        self.processing_status = "ended"


class _FakeBatches:
    def __init__(self, outputs):
        self._outputs = outputs
        self.created_requests = None

    def create(self, requests):
        self.created_requests = requests
        return _FakeBatch("batch_123")

    def retrieve(self, batch_id):
        return _FakeBatch(batch_id)

    def results(self, batch_id):
        return [
            _FakeResultEntry(req["custom_id"], self._outputs[i])
            for i, req in enumerate(self.created_requests)
        ]


def _install_fake_anthropic(monkeypatch, outputs):
    fake_batches = _FakeBatches(outputs)
    fake_messages = types.SimpleNamespace(batches=fake_batches)

    class FakeClient:
        def __init__(self, api_key):
            self.messages = fake_messages

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    fake_auth = types.SimpleNamespace(build_api_credential=lambda environment: "sk-test")
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)
    return fake_batches


def test_execute_batch_classifies_each_input(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no process_registry.yaml here -> falls back to shipped defaults
    _install_fake_anthropic(monkeypatch, outputs=["billing", "technical"])

    result = execute_batch(
        {
            "batch_id": "ticketClassificationBatch_01",
            "inputs": ["I was double charged", "App keeps crashing"],
        }
    )

    assert result["batch_id"] == "ticketClassificationBatch_01"
    assert len(result["results"]) == 2
    assert result["results"][0]["output"] == "billing"
    assert result["results"][0]["error"] is None
    assert result["results"][1]["output"] == "technical"

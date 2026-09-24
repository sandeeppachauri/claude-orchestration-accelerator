"""
test_batch_split_api.py

Exercises the split batch API (submit_batch/get_batch_status/
collect_batch/cancel_batch/resubmit_failed) and BatchStateStore -- see
.claude/rules/batch-registry.md. execute_batch()'s own backward-compat
regression coverage lives in test_batches.py.

Verification-section coverage (see the A5/A7 plan):
1. Process-restart resumability via a persisted handle -- no resubmission.
2. totals == sum of per-item usage.
3. Text extraction survives `thinking` blocks (joins all type=="text"
   blocks, not content[0].text).
"""

import sys
import types

import pytest

from orchestration_accelerator.batch import (
    BatchJobError,
    cancel_batch,
    collect_batch,
    get_batch_status,
    resubmit_failed,
    submit_batch,
)
from orchestration_accelerator.batch.batch_state_store import (
    BatchStateStoreResolutionError,
    resolve_batch_state_store,
)


class _FakeBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text


class _FakeUsage:
    def __init__(self, input_tokens=10, output_tokens=5, cache_creation=0, cache_read=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation
        self.cache_read_input_tokens = cache_read


class _FakeMessage:
    def __init__(self, content_blocks, usage=None, model="claude-haiku-4-5-20251001", stop_reason="end_turn"):
        self.content = content_blocks
        self.usage = usage or _FakeUsage()
        self.model = model
        self.stop_reason = stop_reason


class _FakeResult:
    def __init__(self, type_, message=None, error_text=None):
        self.type = type_
        if message is not None:
            self.message = message
        self._error_text = error_text

    def __str__(self):
        return self._error_text or self.type


class _FakeResultEntry:
    def __init__(self, custom_id, result, entry_id="req_001"):
        self.custom_id = custom_id
        self.result = result
        self.id = entry_id


class _FakeBatch:
    def __init__(self, id_, processing_status="ended"):
        self.id = id_
        self.processing_status = processing_status


class _FakeBatches:
    def __init__(self):
        self.created_requests_by_batch: dict[str, list] = {}
        self.results_by_batch: dict[str, list] = {}
        self.statuses: dict[str, str] = {}
        self._counter = 0
        self.cancel_calls: list[str] = []

    def create(self, requests):
        self._counter += 1
        batch_id = f"batch_{self._counter}"
        self.created_requests_by_batch[batch_id] = requests
        self.statuses[batch_id] = "ended"
        return _FakeBatch(batch_id)

    def retrieve(self, batch_id):
        return _FakeBatch(batch_id, processing_status=self.statuses.get(batch_id, "ended"))

    def results(self, batch_id):
        return self.results_by_batch.get(batch_id, [])

    def cancel(self, batch_id):
        self.cancel_calls.append(batch_id)
        return _FakeBatch(batch_id, processing_status="canceling")


def _install_fake_anthropic(monkeypatch):
    fake_batches = _FakeBatches()
    fake_messages = types.SimpleNamespace(batches=fake_batches)

    class FakeClient:
        def __init__(self, api_key, base_url=None):
            self.messages = fake_messages

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    fake_auth = types.SimpleNamespace(
        build_api_credential=lambda environment: "sk-test",
        build_base_url=lambda environment: None,
    )
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)
    return fake_batches


def test_submit_batch_does_not_block_on_polling(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)

    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})

    assert handle["batch_job"] == "ticketClassificationBatch_01"
    assert len(handle["provider_batch_ids"]) == 1
    assert handle["provider_batch_ids"][0] in fake_batches.created_requests_by_batch
    assert handle["custom_ids"] == ["ticketClassificationBatch_01-0"]
    assert handle["handle_version"] == 1


def test_submit_batch_items_form_with_custom_ids_and_attachments(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)

    handle = submit_batch(
        {
            "batch_id": "ticketClassificationBatch_01",
            "items": [
                {"custom_id": "U-001", "input": "a ticket", "attachments": None},
                {"custom_id": "U-002", "input": "another ticket"},
            ],
        }
    )

    assert handle["custom_ids"] == ["U-001", "U-002"]
    requests = list(fake_batches.created_requests_by_batch.values())[0]
    assert [r["custom_id"] for r in requests] == ["U-001", "U-002"]


def test_get_batch_status_non_blocking(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})

    fake_batches.statuses[handle["provider_batch_ids"][0]] = "in_progress"
    status = get_batch_status(handle)
    assert status["all_ended"] is False
    assert status["statuses"] == ["in_progress"]

    fake_batches.statuses[handle["provider_batch_ids"][0]] = "ended"
    status = get_batch_status(handle)
    assert status["all_ended"] is True


def test_collect_batch_reads_full_usage_and_totals(monkeypatch, tmp_path):
    """Verification #2: totals == sum of per-item usage."""
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch(
        {"batch_id": "ticketClassificationBatch_01", "inputs": ["ticket one", "ticket two"]}
    )
    provider_batch_id = handle["provider_batch_ids"][0]

    fake_batches.results_by_batch[provider_batch_id] = [
        _FakeResultEntry(
            "ticketClassificationBatch_01-0",
            _FakeResult("succeeded", _FakeMessage([_FakeBlock("text", "billing")], _FakeUsage(10, 5))),
        ),
        _FakeResultEntry(
            "ticketClassificationBatch_01-1",
            _FakeResult("succeeded", _FakeMessage([_FakeBlock("text", "technical")], _FakeUsage(8, 4))),
        ),
    ]

    batch_result = collect_batch(handle)

    assert batch_result["status"] == "ended"
    assert batch_result["totals"]["succeeded"] == 2
    assert batch_result["totals"]["input_tokens"] == 18
    assert batch_result["totals"]["output_tokens"] == 9
    outputs = {r["custom_id"]: r["output"] for r in batch_result["results"]}
    assert outputs == {"ticketClassificationBatch_01-0": "billing", "ticketClassificationBatch_01-1": "technical"}


def test_collect_batch_survives_thinking_blocks(monkeypatch, tmp_path):
    """Verification #3: a thinking-enabled step's batch result still
    yields the final text answer, not content[0] (which would be the
    thinking block, not text)."""
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})
    provider_batch_id = handle["provider_batch_ids"][0]

    fake_batches.results_by_batch[provider_batch_id] = [
        _FakeResultEntry(
            "ticketClassificationBatch_01-0",
            _FakeResult(
                "succeeded",
                _FakeMessage(
                    [
                        _FakeBlock("thinking", "internal reasoning, not the answer"),
                        _FakeBlock("text", "billing"),
                    ]
                ),
            ),
        ),
    ]

    batch_result = collect_batch(handle)
    assert batch_result["results"][0]["output"] == "billing"
    assert "internal reasoning" not in batch_result["results"][0]["raw_output"]


def test_collect_batch_handles_errored_expired_canceled(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch(
        {"batch_id": "ticketClassificationBatch_01", "inputs": ["a", "b", "c"]}
    )
    provider_batch_id = handle["provider_batch_ids"][0]

    fake_batches.results_by_batch[provider_batch_id] = [
        _FakeResultEntry("ticketClassificationBatch_01-0", _FakeResult("errored", error_text="rate limited")),
        _FakeResultEntry("ticketClassificationBatch_01-1", _FakeResult("expired")),
        _FakeResultEntry("ticketClassificationBatch_01-2", _FakeResult("canceled")),
    ]

    batch_result = collect_batch(handle)
    statuses = {r["custom_id"]: r["status"] for r in batch_result["results"]}
    assert statuses == {
        "ticketClassificationBatch_01-0": "errored",
        "ticketClassificationBatch_01-1": "expired",
        "ticketClassificationBatch_01-2": "canceled",
    }
    assert batch_result["totals"]["errored"] == 1
    assert batch_result["totals"]["expired"] == 1
    assert batch_result["totals"]["canceled"] == 1


def test_collect_batch_raises_if_not_ended(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})
    fake_batches.statuses[handle["provider_batch_ids"][0]] = "in_progress"

    with pytest.raises(BatchJobError):
        collect_batch(handle)


def test_process_restart_resumability_via_state_store(monkeypatch, tmp_path):
    """Verification #1: kill/simulate process death after submit_batch();
    a fresh call to collect_batch() using only the persisted handle
    returns results with no resubmission."""
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)

    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})
    provider_batch_id = handle["provider_batch_ids"][0]
    fake_batches.results_by_batch[provider_batch_id] = [
        _FakeResultEntry(
            "ticketClassificationBatch_01-0",
            _FakeResult("succeeded", _FakeMessage([_FakeBlock("text", "billing")])),
        ),
    ]

    # Simulate a process restart: only the persisted (plain dict, no
    # in-memory _configs/_process_name/_items_by_custom_id) handle
    # survives -- exactly what a caller would get back from JSON storage.
    persisted_handle = {k: v for k, v in handle.items() if not k.startswith("_")}

    requests_before = len(fake_batches.created_requests_by_batch)
    batch_result = collect_batch(persisted_handle)
    requests_after = len(fake_batches.created_requests_by_batch)

    assert requests_after == requests_before  # no resubmission happened
    assert batch_result["results"][0]["output"] == "billing"


def test_cancel_batch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["a ticket"]})

    result = cancel_batch(handle)
    assert result["canceled"] == [True]
    assert fake_batches.cancel_calls == handle["provider_batch_ids"]


def _write_fake_registries(tmp_path, *, fallback_model="claude-sonnet-5", max_requests_per_batch=None):
    """ticketClassificationBatch's real fallback chain equals its own
    model (fallback: [claude-haiku-4-5-20251001]), so it has zero real
    fallback_remaining -- resubmit_failed()/chunking tests need their own
    registries with a distinct fallback model / max_requests_per_batch."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "process_registry.yaml").write_text(
        "fakeProcess:\n"
        "  id: fakeProcess_01\n"
        "  description: test process\n"
        "  steps: [classify]\n"
        "  classify:\n"
        "    model: claude-haiku-4-5-20251001\n"
        f"    fallback: [{fallback_model}]\n"
    )
    extra = f"\n  max_requests_per_batch: {max_requests_per_batch}" if max_requests_per_batch else ""
    (config_dir / "batch_registry.yaml").write_text(
        "fakeBatch:\n"
        "  batch_id: fakeBatch_01\n"
        "  process: fakeProcess_01\n"
        "  step: classify\n"
        "  environment: local" + extra + "\n"
    )
    return config_dir


def test_resubmit_failed_retries_only_errored_items(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    config_dir = _write_fake_registries(tmp_path, fallback_model="claude-sonnet-5")

    handle = submit_batch(
        {"batch_id": "fakeBatch_01", "inputs": ["ticket one", "ticket two"]},
        registry_path=config_dir / "process_registry.yaml",
    )
    provider_batch_id = handle["provider_batch_ids"][0]
    fake_batches.results_by_batch[provider_batch_id] = [
        _FakeResultEntry("fakeBatch_01-0", _FakeResult("errored", error_text="overloaded")),
        _FakeResultEntry(
            "fakeBatch_01-1",
            _FakeResult("succeeded", _FakeMessage([_FakeBlock("text", "technical")])),
        ),
    ]
    batch_result = collect_batch(handle, registry_path=config_dir / "process_registry.yaml")

    retry_handle = resubmit_failed(handle, batch_result, registry_path=config_dir / "process_registry.yaml")

    assert retry_handle is not None
    assert retry_handle["custom_ids"] == ["fakeBatch_01-0"]
    assert retry_handle["model"] == "claude-sonnet-5"  # fallback model
    assert retry_handle["fallback_remaining"] == []


def test_resubmit_failed_returns_none_when_nothing_errored(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["ticket one"]})
    fake_batches.results_by_batch[handle["provider_batch_ids"][0]] = [
        _FakeResultEntry(
            "ticketClassificationBatch_01-0",
            _FakeResult("succeeded", _FakeMessage([_FakeBlock("text", "billing")])),
        ),
    ]
    batch_result = collect_batch(handle)

    assert resubmit_failed(handle, batch_result) is None


def test_resubmit_failed_requires_original_handle_object(monkeypatch, tmp_path):
    """A handle round-tripped through storage (no in-memory
    _items_by_custom_id) cannot retry -- original inputs are never
    persisted."""
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    handle = submit_batch({"batch_id": "ticketClassificationBatch_01", "inputs": ["ticket one"]})
    fake_batches.results_by_batch[handle["provider_batch_ids"][0]] = [
        _FakeResultEntry("ticketClassificationBatch_01-0", _FakeResult("errored", error_text="boom")),
    ]
    batch_result = collect_batch(handle)
    persisted_handle = {k: v for k, v in handle.items() if not k.startswith("_")}

    with pytest.raises(BatchJobError):
        resubmit_failed(persisted_handle, batch_result)


def test_max_requests_per_batch_chunks_submission(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_batches = _install_fake_anthropic(monkeypatch)
    config_dir = _write_fake_registries(tmp_path, max_requests_per_batch=2)

    handle = submit_batch(
        {"batch_id": "fakeBatch_01", "inputs": ["t1", "t2", "t3", "t4", "t5"]},
        registry_path=config_dir / "process_registry.yaml",
    )

    assert len(handle["provider_batch_ids"]) == 3  # 2 + 2 + 1


def test_resolve_batch_state_store_none_default():
    from orchestration_accelerator.batch.batch_state_store import _NoneStateStore

    store = resolve_batch_state_store(None)
    assert isinstance(store, _NoneStateStore)
    assert store.load("x", ["y"]) is None
    assert store.list_open() == []


def test_resolve_batch_state_store_file_backend(tmp_path):
    store = resolve_batch_state_store({"backend": "file", "path": str(tmp_path / "handles.json")})
    handle = {"batch_job": "j1", "provider_batch_ids": ["b1"], "custom_ids": ["c1"]}
    store.save(handle)

    loaded = store.load("j1", ["b1"])
    assert loaded["custom_ids"] == ["c1"]
    assert len(store.list_open()) == 1

    store.mark_collected("j1", ["b1"])
    assert store.list_open() == []


def test_resolve_batch_state_store_custom_backend_calls_factory(monkeypatch):
    built = {}

    def _factory():
        built["called"] = True
        return object()

    import types as t

    fake_module = t.SimpleNamespace(build=_factory)
    monkeypatch.setitem(sys.modules, "fake_batch_store_module", fake_module)

    resolve_batch_state_store({"backend": "custom", "factory": "fake_batch_store_module:build"})
    assert built["called"]


def test_resolve_batch_state_store_unknown_backend_raises():
    with pytest.raises(BatchStateStoreResolutionError):
        resolve_batch_state_store({"backend": "redis"})


def test_resolve_batch_state_store_custom_missing_factory_raises():
    with pytest.raises(BatchStateStoreResolutionError):
        resolve_batch_state_store({"backend": "custom"})

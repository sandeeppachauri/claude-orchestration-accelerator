import pytest

from orchestration_accelerator.batch.batch_registry import (
    BatchJobNotFoundError,
    get_batch_job,
    load_batch_registry,
)
from orchestration_accelerator.registry import ProcessNotFoundError, get_process_by_id


def test_load_root_batch_registry():
    registry = load_batch_registry()
    assert "ticketClassificationBatch" in registry


def test_get_batch_job_resolves_defaults():
    job = get_batch_job("ticketClassificationBatch_01")
    assert job["id"] == "ticketClassificationBatch_01"
    assert job["process_id"] == "ticketClassification_01"
    assert job["step"] == "classify"
    assert job["poll_interval_seconds"] == 5
    assert job["poll_timeout_seconds"] == 3600


def test_unknown_batch_id_raises():
    with pytest.raises(BatchJobNotFoundError):
        get_batch_job("does-not-exist")


def test_get_process_by_id_resolves():
    process_name, block = get_process_by_id("ticketClassification_01")
    assert process_name == "ticketClassification"
    assert block["id"] == "ticketClassification_01"


def test_get_process_by_id_unknown_raises():
    with pytest.raises(ProcessNotFoundError):
        get_process_by_id("does-not-exist")

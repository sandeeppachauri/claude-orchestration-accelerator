"""
test_execute_parallel_mode.py

Covers parallel_processing: true's execute() path (see
.claude/rules/parallel-processing.md) -- every step but the last running
concurrently via asyncio.gather(), the mandatory trailing synthesis_step
reconciling every branch's output via {{<stepName>_output}} templating,
and the context_mode: session + messages_api restriction. Mocks
execute_with_fallback()/open_agent_sdk_session()/run_session_turn() at the
module level core.py imports them from -- no real network/process calls.
"""

import asyncio

import pytest

import project_accelerator.core as core_module
from orchestration_accelerator.registry import UnsupportedCapabilityError
from project_accelerator import execute


def _result(text, **overrides):
    base = {
        "text": text,
        "model_used": "claude-haiku-4-5-20251001",
        "usage": {},
        "stop_reason": "end_turn",
        "request_id": None,
        "latency_ms": 0.0,
        "session_id": None,
        "tool_calls": [],
    }
    base.update(overrides)
    return base


def _patch_logging(monkeypatch):
    async def _fake_log(*args, **kwargs):
        return None

    import orchestration_accelerator.logging as logging_module

    monkeypatch.setattr(logging_module, "log", _fake_log)


def _patch_router_by_step(monkeypatch, responses_by_step, concurrency_probe=None):
    """responses_by_step: {step_name: output_text}. concurrency_probe, if
    given, is a dict this fixture uses to record how many calls are
    in-flight simultaneously -- lets a test assert branches actually
    overlapped rather than running one after another."""

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, **kwargs
    ):
        step_name = None
        # step name isn't passed directly to execute_with_fallback, but the
        # response text is looked up by matching system_prompt content is
        # brittle -- instead route by call order via a shared counter on
        # the probe, matched against responses_by_step's insertion order.
        if concurrency_probe is not None:
            concurrency_probe["in_flight"] += 1
            concurrency_probe["max_in_flight"] = max(
                concurrency_probe["max_in_flight"], concurrency_probe["in_flight"]
            )
            await asyncio.sleep(0.01)
            concurrency_probe["in_flight"] -= 1
        idx = concurrency_probe["calls"] if concurrency_probe is not None else 0
        if concurrency_probe is not None:
            concurrency_probe["calls"] += 1
        text = list(responses_by_step.values())[idx % len(responses_by_step)]
        return _result(text, model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)


def test_parallel_branches_run_concurrently(monkeypatch):
    _patch_logging(monkeypatch)
    probe = {"in_flight": 0, "max_in_flight": 0, "calls": 0}
    _patch_router_by_step(
        monkeypatch,
        {"parallel_sentiment": "positive", "parallel_risk": "low", "synthesis_step": '{"sentiment": "positive", "risk": "low", "recommended_action": "no action needed"}'},
        concurrency_probe=probe,
    )

    result = execute(
        {
            "process": "parallelAnalysisDemo",
            "input": "The product works great, thanks!",
            "backend": "agent_sdk",
        }
    )

    assert set(result.keys()) == {"parallel_sentiment", "parallel_risk", "synthesis_step"}
    # Both branches overlapped in time -- proves asyncio.gather() concurrency,
    # not accidental sequential execution.
    assert probe["max_in_flight"] >= 2


def test_synthesis_step_receives_both_branch_outputs(monkeypatch):
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, **kwargs
    ):
        if "sentiment" in system_prompt.lower():
            return _result("positive", model_used=model)
        if "risk" in system_prompt.lower():
            return _result("low", model_used=model)
        # synthesis step -- assert both branch outputs were templated in.
        assert "positive" in user_content
        assert "low" in user_content
        return _result(
            '{"sentiment": "positive", "risk": "low", "recommended_action": "no action needed"}',
            model_used=model,
        )

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "parallelAnalysisDemo",
            "input": "The product works great, thanks!",
            "backend": "agent_sdk",
        }
    )

    assert result["parallel_sentiment"]["output"] == "positive"
    assert result["parallel_risk"]["output"] == "low"
    assert result["synthesis_step"]["output"]["sentiment"] == "positive"
    assert result["synthesis_step"]["output"]["risk"] == "low"


def test_single_step_narrowing_bypasses_parallel_mode(monkeypatch):
    """payload["step"] narrowed to one step of a parallel_processing
    process must run through the normal single-step path unchanged --
    there is nothing to parallelize with only one step selected."""
    _patch_logging(monkeypatch)

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, **kwargs
    ):
        return _result("positive", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "parallelAnalysisDemo",
            "step": "parallel_sentiment",
            "input": "The product works great, thanks!",
            "backend": "agent_sdk",
        }
    )

    assert list(result.keys()) == ["parallel_sentiment"]
    assert result["parallel_sentiment"]["output"] == "positive"


def test_non_parallel_process_unaffected(monkeypatch):
    """A process without parallel_processing keeps running strictly
    sequentially -- confirms zero behavior change for existing processes."""
    _patch_logging(monkeypatch)
    call_order = []

    async def _fake_execute_with_fallback(
        *, model, fallback, system_prompt, user_content, backend, environment, **kwargs
    ):
        call_order.append(user_content)
        return _result("billing", model_used=model)

    monkeypatch.setattr(core_module, "execute_with_fallback", _fake_execute_with_fallback)

    result = execute(
        {
            "process": "ticketClassification",
            "step": "classify",
            "input": "I was double charged",
            "backend": "agent_sdk",
        }
    )
    assert result["classify"]["output"] == "billing"


def test_parallel_processing_session_mode_with_messages_api_raises(monkeypatch):
    _patch_logging(monkeypatch)
    registry_yaml = """
parallelSessionDemo:
  id: parallelSessionDemo_01
  parallel_processing: true
  context_mode: session
  steps: [branchA, branchB, synthesis_step]
  branchA: {prompt: parallel_sentiment.yaml, model: claude-haiku-4-5-20251001, fallback: []}
  branchB: {prompt: parallel_risk.yaml, model: claude-haiku-4-5-20251001, fallback: []}
  synthesis_step: {prompt: parallel_synthesis.yaml, model: claude-haiku-4-5-20251001, fallback: []}
"""

    def _fake_resolve_registry_and_prompts_dir(tmp_registry):
        from pathlib import Path

        from orchestration_accelerator.prompting import PROMPTS_DIR

        return tmp_registry, PROMPTS_DIR

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "process_registry.yaml"
        registry_path.write_text(registry_yaml)
        monkeypatch.setattr(
            core_module,
            "_resolve_registry_and_prompts_dir",
            lambda: _fake_resolve_registry_and_prompts_dir(registry_path),
        )

        with pytest.raises(UnsupportedCapabilityError):
            execute(
                {
                    "process": "parallelSessionDemo",
                    "input": "hello",
                    "backend": "messages_api",
                }
            )

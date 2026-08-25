"""
test_backends.py

Exercises call_agent_sdk()'s own text-accumulation loop directly (not via
the fallback executor -- see test_router.py for that), specifically the
AgentProducedNoTextError guard: a model that spends its whole run on
tool calls and never emits a TextBlock must fail loudly and specifically,
not surface five frames later as an opaque json.loads("") error out of
PromptManager.validate_output().
"""

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

import model_router_accelerator.backends as backends_module
from model_router_accelerator.exceptions import AgentProducedNoTextError


def _make_fake_query(messages):
    async def _fake_query(*, prompt, options):
        for message in messages:
            yield message

    return _fake_query


async def test_call_agent_sdk_raises_when_only_tool_calls_made(monkeypatch):
    messages = [
        AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Read", input={})],
            model="claude-haiku-4-5-20251001",
        ),
        AssistantMessage(
            content=[ToolUseBlock(id="t2", name="Read", input={})],
            model="claude-haiku-4-5-20251001",
        ),
    ]
    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _make_fake_query(messages))

    with pytest.raises(AgentProducedNoTextError) as excinfo:
        await backends_module.call_agent_sdk(
            model="claude-haiku-4-5-20251001",
            system_prompt="sys",
            user_content="hi",
            environment="local",
            max_turns=3,
        )
    assert "2 tool call(s)" in str(excinfo.value)


async def test_call_agent_sdk_returns_text_when_present(monkeypatch):
    messages = [
        AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Read", input={})],
            model="claude-haiku-4-5-20251001",
        ),
        AssistantMessage(
            content=[TextBlock(text='{"escalate": true}')],
            model="claude-haiku-4-5-20251001",
        ),
    ]
    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _make_fake_query(messages))

    result = await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        max_turns=3,
    )
    assert result == '{"escalate": true}'

"""
test_backends.py

Exercises call_agent_sdk()'s own text-accumulation loop directly (not via
the fallback executor -- see test_router.py for that), specifically the
AgentProducedNoTextError guard: a model that spends its whole run on
tool calls and never emits a TextBlock must fail loudly and specifically,
not surface five frames later as an opaque json.loads("") error out of
PromptManager.validate_output().
"""

import sys
import types

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

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
    assert result["text"] == '{"escalate": true}'
    assert result["model_used"] == "claude-haiku-4-5-20251001"
    assert result["tool_calls"] == [{"name": "tool", "count": 1}]
    assert result["request_id"] is None
    assert isinstance(result["latency_ms"], float)


async def test_call_agent_sdk_captures_usage_and_session_id_from_result_message(monkeypatch):
    messages = [
        AssistantMessage(
            content=[TextBlock(text='{"escalate": true}')],
            model="claude-haiku-4-5-20251001",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="sess-123",
            stop_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
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
    assert result["session_id"] == "sess-123"
    assert result["stop_reason"] == "end_turn"
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 5}


class _FakeUsage:
    def __init__(self):
        self.input_tokens = 10
        self.output_tokens = 4
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _FakeContentBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeContentBlock(text)]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"
        self.model = "claude-haiku-4-5-20251001"
        self.id = "req-123"


def _install_fake_messages_api(monkeypatch, response_text="ok"):
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeResponse(response_text)

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    fake_auth = types.SimpleNamespace(build_api_credential=lambda environment: "sk-test")
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)
    return captured


async def test_call_messages_api_no_assistant_prompt_single_turn_messages(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
    )
    assert result["text"] == "ok"
    assert captured["kwargs"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_call_messages_api_assistant_prompt_prepends_assistant_turn(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Ticket: hello\nLabel:",
        environment="local",
        assistant_prompt="Example ticket: x\nLabel: billing-duplicate-charge",
    )
    assert result["text"] == "ok"
    assert captured["kwargs"]["messages"] == [
        {"role": "assistant", "content": "Example ticket: x\nLabel: billing-duplicate-charge"},
        {"role": "user", "content": "Ticket: hello\nLabel:"},
    ]


async def test_call_messages_api_captures_usage_and_request_id(monkeypatch):
    _install_fake_messages_api(monkeypatch)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
    )
    assert result["model_used"] == "claude-haiku-4-5-20251001"
    assert result["stop_reason"] == "end_turn"
    assert result["request_id"] == "req-123"
    assert result["usage"] == {
        "input_tokens": 10,
        "output_tokens": 4,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }
    assert result["session_id"] is None
    assert result["tool_calls"] == []


class _FakeStreamDelta:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _FakeStreamEvent:
    def __init__(self, type_, delta=None):
        self.type = type_
        self.delta = delta


class _FakeMessageStream:
    """Mimics anthropic.MessageStream's context-manager + iterator
    protocol -- __enter__ returns self, iterating yields raw stream
    events, get_final_message() returns the accumulated response."""

    def __init__(self, events, final_response):
        self._events = events
        self._final_response = final_response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final_response


def _install_fake_streaming_messages_api(monkeypatch, chunks, response_text):
    events = [
        _FakeStreamEvent("content_block_delta", _FakeStreamDelta("text_delta", c))
        for c in chunks
    ]
    events.append(_FakeStreamEvent("message_stop"))
    final_response = _FakeResponse(response_text)
    captured = {}

    class FakeMessages:
        def stream(self, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeMessageStream(events, final_response)

    class FakeClient:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    fake_auth = types.SimpleNamespace(build_api_credential=lambda environment: "sk-test")
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)
    return captured


async def test_call_messages_api_stream_invokes_on_chunk_per_delta(monkeypatch):
    _install_fake_streaming_messages_api(monkeypatch, chunks=["Hel", "lo "], response_text="Hello world")
    received = []

    async def on_chunk(chunk):
        received.append(chunk)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        stream=True,
        on_chunk=on_chunk,
    )
    assert received == ["Hel", "lo "]
    # Final accumulated text comes from get_final_message(), identical
    # shape to the non-streaming path -- no data loss.
    assert result["text"] == "Hello world"


async def test_call_messages_api_stream_no_on_chunk_still_returns_final_text(monkeypatch):
    _install_fake_streaming_messages_api(monkeypatch, chunks=["a", "b"], response_text="ab")

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        stream=True,
    )
    assert result["text"] == "ab"


async def test_call_messages_api_stream_supports_sync_on_chunk(monkeypatch):
    _install_fake_streaming_messages_api(monkeypatch, chunks=["x"], response_text="x")
    received = []

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        stream=True,
        on_chunk=received.append,
    )
    assert received == ["x"]
    assert result["text"] == "x"


async def test_call_agent_sdk_stream_invokes_on_chunk_from_stream_events(monkeypatch):
    from claude_agent_sdk import StreamEvent

    messages = [
        StreamEvent(
            uuid="u1",
            session_id="s1",
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
        ),
        StreamEvent(
            uuid="u2",
            session_id="s1",
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
        ),
        AssistantMessage(
            content=[TextBlock(text="Hello")],
            model="claude-haiku-4-5-20251001",
        ),
    ]
    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _make_fake_query(messages))
    received = []

    result = await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        max_turns=3,
        stream=True,
        on_chunk=received.append,
    )
    assert received == ["Hel", "lo"]
    assert result["text"] == "Hello"


async def test_call_agent_sdk_stream_sets_include_partial_messages(monkeypatch):
    captured_options = {}

    async def _fake_query(*, prompt, options):
        captured_options["options"] = options
        yield AssistantMessage(
            content=[TextBlock(text="ok")], model="claude-haiku-4-5-20251001"
        )

    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _fake_query)

    await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        max_turns=1,
        stream=True,
    )
    assert captured_options["options"].include_partial_messages is True


async def test_call_agent_sdk_no_stream_leaves_include_partial_messages_false(monkeypatch):
    captured_options = {}

    async def _fake_query(*, prompt, options):
        captured_options["options"] = options
        yield AssistantMessage(
            content=[TextBlock(text="ok")], model="claude-haiku-4-5-20251001"
        )

    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _fake_query)

    await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
        max_turns=1,
    )
    assert captured_options["options"].include_partial_messages is False

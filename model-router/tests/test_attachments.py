"""
test_attachments.py

Exercises attachments end-to-end through call_messages_api()/
call_agent_sdk() -- see .claude/rules/attachments.md. No-attachments
regression coverage lives alongside it in test_backends.py
(test_call_messages_api_no_assistant_prompt_single_turn_messages asserts
`messages == [{"role": "user", "content": "hi"}]`, a plain string, proving
the no-attachments request is unaffected).
"""

from __future__ import annotations

import sys
import types

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

import model_router_accelerator.backends as backends_module
from model_router_accelerator.attachments import AttachmentError


class _FakeResponse:
    def __init__(self, text, model="claude-haiku-4-5-20251001"):
        self.content = [types.SimpleNamespace(type="text", text=text)]
        self.model = model
        self.stop_reason = "end_turn"
        self.usage = types.SimpleNamespace(
            input_tokens=10, output_tokens=5,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        self.id = "req_123"


def _install_fake_messages_api(monkeypatch, response_text="ok"):
    captured = {}

    class FakeFiles:
        def upload(self, file, **kwargs):
            captured.setdefault("uploaded_paths", []).append(file.name)
            return types.SimpleNamespace(id="file_uploaded_001")

    class FakeMessages:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeResponse(response_text)

    class FakeClient:
        def __init__(self, api_key, base_url=None):
            self.messages = FakeMessages()
            self.files = FakeFiles()

    fake_anthropic = types.SimpleNamespace(Anthropic=FakeClient)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    class FakeAuthResolutionError(Exception):
        pass

    fake_auth_exceptions = types.SimpleNamespace(AuthResolutionError=FakeAuthResolutionError)
    fake_auth = types.SimpleNamespace(
        build_api_credential=lambda environment: "sk-test",
        build_base_url=lambda environment: "https://api.anthropic.com",
        exceptions=fake_auth_exceptions,
    )
    monkeypatch.setitem(sys.modules, "auth_accelerator", fake_auth)
    monkeypatch.setitem(sys.modules, "auth_accelerator.exceptions", fake_auth_exceptions)
    return captured


async def test_messages_api_file_id_attachment_builds_document_block(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Summarize this file.",
        environment="local",
        attachments=[{"file_id": "file_existing_001", "kind": "document", "title": "doc.pdf"}],
    )

    assert result["text"] == "ok"
    messages = captured["kwargs"]["messages"]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert content == [
        {
            "type": "document",
            "source": {"type": "file", "file_id": "file_existing_001"},
            "title": "doc.pdf",
        },
        {"type": "text", "text": "Summarize this file."},
    ]
    assert result["uploaded_file_ids"] == []


async def test_messages_api_text_attachment_builds_inline_document_block(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Explain this code.",
        environment="local",
        attachments=[{"text": "public class Foo {}", "kind": "text", "title": "Foo.java"}],
    )

    messages = captured["kwargs"]["messages"]
    content = messages[0]["content"]
    assert content == [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": "public class Foo {}"},
            "title": "Foo.java",
        },
        {"type": "text", "text": "Explain this code."},
    ]
    assert result["uploaded_file_ids"] == []


async def test_messages_api_path_attachment_auto_uploads_and_returns_file_id(
    monkeypatch, tmp_path
):
    captured = _install_fake_messages_api(monkeypatch)
    f = tmp_path / "notes.txt"
    f.write_text("hello world")

    result = await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Summarize.",
        environment="local",
        attachments=[{"path": str(f), "kind": "document"}],
    )

    messages = captured["kwargs"]["messages"]
    content = messages[0]["content"]
    assert content[0] == {
        "type": "document",
        "source": {"type": "file", "file_id": "file_uploaded_001"},
    }
    assert result["uploaded_file_ids"] == ["file_uploaded_001"]


async def test_messages_api_image_attachment_builds_image_block(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="What's in this image?",
        environment="local",
        attachments=[{"file_id": "file_img_001", "kind": "image"}],
    )

    content = captured["kwargs"]["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "file", "file_id": "file_img_001"}}


async def test_messages_api_attachment_cache_control(monkeypatch):
    captured = _install_fake_messages_api(monkeypatch)

    await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Summarize.",
        environment="local",
        attachments=[{"file_id": "file_001", "kind": "document", "cache": True}],
    )

    content = captured["kwargs"]["messages"][0]["content"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}


async def test_messages_api_attachment_requires_exactly_one_source(monkeypatch):
    _install_fake_messages_api(monkeypatch)

    with pytest.raises(AttachmentError):
        await backends_module.call_messages_api(
            model="claude-haiku-4-5-20251001",
            system_prompt="sys",
            user_content="hi",
            environment="local",
            attachments=[{"file_id": "a", "path": "b"}],
        )


async def test_messages_api_no_attachments_key_omitted_is_unaffected(monkeypatch):
    """No `attachments` argument at all -- default None -- must produce the
    exact same plain-string message as before attachments existed."""
    captured = _install_fake_messages_api(monkeypatch)

    await backends_module.call_messages_api(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
    )
    assert captured["kwargs"]["messages"] == [{"role": "user", "content": "hi"}]


def _make_fake_query_capturing_prompt(captured, messages):
    async def _fake_query(*, prompt, options):
        captured["prompt"] = prompt
        if hasattr(prompt, "__aiter__"):
            captured["prompt_items"] = [item async for item in prompt]
        for message in messages:
            yield message

    return _fake_query


async def test_agent_sdk_text_attachment_uses_streaming_input(monkeypatch):
    captured: dict = {}
    messages = [AssistantMessage(content=[TextBlock(text="ok")], model="claude-haiku-4-5-20251001")]
    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _make_fake_query_capturing_prompt(captured, messages))

    result = await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="Explain this.",
        environment="local",
        attachments=[{"text": "print('hi')", "kind": "text", "title": "script.py"}],
    )

    assert result["text"] == "ok"
    assert hasattr(captured["prompt"], "__aiter__")
    item = captured["prompt_items"][0]
    assert item["type"] == "user"
    assert item["message"]["role"] == "user"
    content = item["message"]["content"]
    assert content == [
        {"type": "text", "text": "[script.py]\nprint('hi')"},
        {"type": "text", "text": "Explain this."},
    ]


async def test_agent_sdk_no_attachments_uses_plain_string_prompt(monkeypatch):
    """No attachments -- `prompt` must stay the plain string, not switch to
    the async-iterable streaming-input form."""
    captured: dict = {}
    messages = [AssistantMessage(content=[TextBlock(text="ok")], model="claude-haiku-4-5-20251001")]
    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", _make_fake_query_capturing_prompt(captured, messages))

    await backends_module.call_agent_sdk(
        model="claude-haiku-4-5-20251001",
        system_prompt="sys",
        user_content="hi",
        environment="local",
    )
    assert captured["prompt"] == "hi"


async def test_agent_sdk_file_id_attachment_raises_unsupported(monkeypatch):
    import claude_agent_sdk

    async def _unreachable_query(*, prompt, options):
        raise AssertionError("query() must not be called before AttachmentError is raised")
        yield  # pragma: no cover

    monkeypatch.setattr(claude_agent_sdk, "query", _unreachable_query)

    with pytest.raises(AttachmentError):
        await backends_module.call_agent_sdk(
            model="claude-haiku-4-5-20251001",
            system_prompt="sys",
            user_content="hi",
            environment="local",
            attachments=[{"file_id": "file_001", "kind": "document"}],
        )

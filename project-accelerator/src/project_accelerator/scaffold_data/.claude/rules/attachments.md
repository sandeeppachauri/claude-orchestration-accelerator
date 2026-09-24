# `attachments` -- file/text content in a model call (A7)

New optional **payload** key (not a `process_registry.yaml` capability),
on both `execute()`'s payload and a batch item
(`submit_batch()`'s `items: [{custom_id, input, attachments?}]`).

```python
result = execute({
    "process": "ticketClassification",
    "step": "classify",
    "input": "Summarize the attached invoice.",
    "backend": "messages_api",
    "attachments": [
        {"file_id": "file_01..", "kind": "document", "title": "invoice.pdf", "cache": True},
        {"path": "./src/UI_MAP.xml", "kind": "document"},
        {"text": "<inline source>", "kind": "text", "title": "script-step-7"},
        {"file_id": "file_02..", "kind": "image"},
    ],
})
```

Each entry is `{file_id|path|text, kind, title?, mime_type?, cache?}` --
**exactly one** of `file_id`/`path`/`text`. `kind` is `"document"`
(default), `"image"`, or `"text"` (only valid with `text`, never
`path`/`file_id`). `cache: true` sets an ephemeral prompt-cache
`cache_control` block on that attachment.

## Why `attachments` is a payload key, not a capability

`process_registry.yaml` step keys besides `prompt`/`model`/`fallback`/
`system_prompt` are **capability passthrough** (see
`.claude/rules/process-registry.md`) -- fixed per step, validated against
`config/capability_registry.yaml`'s per-backend whitelist before the
model call. `attachments` deliberately does **not** go through that path,
for two reasons:

1. Capabilities are fixed per step in config; `attachments` varies on
   every call (a different file per request to the same step).
2. Routing it through `validate_capabilities()` would force it onto
   `capability_registry.yaml`'s whitelist, letting a step hard-code files
   in config -- wrong for a per-call value, and it would leak into
   `.claude/rules/capability-registry.md`'s illustrative fence and the
   scaffold's generated HOWTO capability table (both of which
   `check_scaffold_sync.py` cross-checks against the real registry file).

Instead, `attachments` is in `project_accelerator.core`'s
`OPTIONAL_PAYLOAD_KEYS` (same tier as `step`/`environment`/`session_id`/
`on_chunk`) and threaded through `execute_with_fallback()` /
`call_messages_api()` / `call_agent_sdk()` as its **own explicit keyword
argument**, entirely bypassing `validate_capabilities()` -- it never
appears in `capability_registry.yaml`, on either backend.

## Per-backend behavior

- **`messages_api`**: builds `messages[-1]["content"]` as a block array
  -- `[<document/image blocks>, {"type": "text", "text": user_content}]`
  -- instead of the bare string used when no attachments are present.
  - `file_id` -> `{"type": "document"|"image", "source": {"type": "file", "file_id": ...}}`
    (real anthropic 1.8.0 GA shape -- confirmed against the SDK's own
    type stubs, `anthropic.types.FileDocumentSourceParam`/
    `FileImageSourceParam`).
  - `path` -> **auto-uploaded** via `FileManager.upload()` first (GA has
    no "attach a local path directly" block type), then treated as a
    `file_id` entry. The resulting id(s) are returned in
    `execute()`'s result under `results[step]["uploaded_file_ids"]`.
  - `text` -> inlined as a `{"type": "document", "source": {"type":
    "text", "media_type": "text/plain", "data": ...}}` block -- no
    upload, no network call.
  - `image` kind only supports `file_id` (an inline `text` attachment
    cannot be `kind: "image"`).
- **`agent_sdk`**: has **no Files API surface** -- a `file_id` attachment
  raises `AttachmentError` (a friendly "switch to backend: messages_api"
  message) before any call is made. `path`/`text` attachments are
  inlined as extra text blocks and sent via `query()`'s
  `AsyncIterable[dict]` streaming-input form -- `{"type": "user",
  "message": {"role": "user", "content": [...]}, "parent_tool_use_id":
  None, "session_id": None}` -- instead of the plain string `prompt`
  used when no attachments are present (confirmed against the installed
  `claude_agent_sdk.query()`'s own docstring for this exact dict shape).
- **No attachments** (key omitted or empty list) on either backend -> the
  request is **byte-identical** to today -- proven by a regression test
  asserting `messages == [{"role": "user", "content": "hi"}]` (a plain
  string, not a block array) and `prompt == "hi"` (a plain string, not an
  async iterable).

## Scope

Applies to the **sequential threaded step loop only** (`context_mode:
threaded`'s normal step-by-step execution) -- not `parallel_processing:
true` branches or `context_mode: session` steps in this iteration.

## Batch items

`submit_batch()`'s `items` form (`{custom_id, input, attachments?}`, as
opposed to the legacy bare `inputs` list) carries the same shape and
builds the same `messages_api` content blocks per item -- batches are
`messages_api`-only already, so there is no `agent_sdk`
streaming-input variant to support there.

## Implementation

`model_router_accelerator.attachments` (`build_messages_api_blocks()`,
`build_agent_sdk_content()`) holds the shared block-construction logic
used by both `call_messages_api()`/`call_agent_sdk()`
(`model-router/src/model_router_accelerator/backends.py`) and
`submit_batch()`/`resubmit_failed()`
(`src/orchestration_accelerator/batch/batch_manager.py`) -- one place to
change if the real API's accepted block shapes ever change.

See `model-router/tests/test_attachments.py` and
`project-accelerator/tests/test_execute_attachments.py` for worked
examples across both backends, and the no-attachments regression tests.

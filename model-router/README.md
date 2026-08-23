# claude-model-router-accelerator

Executes an ordered model/fallback chain against a pluggable backend
(`"agent_sdk"` | `"messages_api"`). Depends on
`claude-orchestration-accelerator` for `(process, step)` registry lookups
(model + fallback fields) — it does not parse `process_registry.yaml`
itself.

```python
from model_router_accelerator import execute_with_fallback

text = await execute_with_fallback(
    model="claude-haiku-4-5-20251001",
    fallback=["claude-sonnet-5", "claude-opus-4-8"],
    system_prompt="You are a support-ticket classifier...",
    user_content="Classify this ticket: ...",
    backend="agent_sdk",          # or "messages_api"
    environment="local",
)
```

On a rate-limit/overload error from `model`, each `fallback` entry is
tried in order (with basic backoff) until one succeeds or the chain is
exhausted (`FallbackChainExhaustedError`).

Backend selection is purely mechanical — the caller decides which backend
via the `backend` parameter; this package never auto-detects or infers
it. `claude_agent_sdk` and `anthropic` are imported lazily so importing
this package never hard-requires either SDK unless that backend is
actually used.

## Capability passthrough (`**extra`) per backend

Any keyword besides `model`/`fallback`/`system_prompt`/`user_content`/
`backend`/`environment` is forwarded untouched (`process_registry.yaml`'s
step keys land here) — the authoritative list of what each backend sets
explicitly vs. passes through:

- **`agent_sdk`** (`backends.py::call_agent_sdk`) — sets `environment`,
  `model`, `max_turns` (default `1`), `system_prompt` explicitly; `**extra`
  flows into `auth_accelerator.build_options(**extra)` → `ClaudeAgentOptions`
  (e.g. `permission_mode`, `thinking`).
- **`messages_api`** (`backends.py::call_messages_api`) — sets `model`,
  `max_tokens` (default `1024`), `system`, `messages` explicitly; `**extra`
  flows into `anthropic.messages.create(**extra)` (e.g. `temperature`,
  `top_p`).

An unsupported key for the chosen backend/SDK version raises a
`TypeError` at call time, not silently.

## Scope: text only

`execute_with_fallback()` covers the single-turn text path only. File
upload and batch processing (`orchestration_accelerator.file`/`.batch`)
call `anthropic`/`auth_accelerator` directly instead of routing through
this package — a batch job submits one Anthropic Batches API call for
many inputs at once, which doesn't fit this module's one-model-per-call
retry loop. See the root README's "File upload and batch processing"
section.

## Tests

```bash
pytest tests -q
```

Tests simulate rate-limit/overload errors at each position in the
fallback chain, for both backends, with the underlying API calls mocked
— no real network calls.

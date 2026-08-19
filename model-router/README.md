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

## Tests

```bash
pytest tests -q
```

Tests simulate rate-limit/overload errors at each position in the
fallback chain, for both backends, with the underlying API calls mocked
— no real network calls.

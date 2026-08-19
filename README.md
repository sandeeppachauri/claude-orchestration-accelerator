# claude-orchestration-accelerator

A master accelerator for building projects on either the Claude Agent SDK
or the raw Claude (Messages) API. Composes authentication, logging, prompt
resolution, and model routing/fallback behind one call:

```python
from project_accelerator import execute

result = execute({
    "process": "ticketClassification",
    "input": "some ticket text",
    "backend": "agent_sdk",
})
```

See `Master_Accelerator_Plan.md` at the repo root for the full design.

## Capabilities (per-step model config)

A step in `process_registry.yaml` can carry any extra key beyond
`prompt`/`model`/`fallback` — it passes straight through to the model
call, no accelerator code change needed. Supported keys depend on the
payload's `"backend"`:

| Capability | Backend | Example |
| --- | --- | --- |
| `max_turns` | `agent_sdk` | `max_turns: 1` |
| `thinking` (extended thinking) | `agent_sdk` | `thinking: {type: enabled, budget_tokens: 4096}` |
| `permission_mode` | `agent_sdk` | `permission_mode: acceptEdits` |
| `temperature` | `messages_api` | `temperature: 0.2` |
| `top_p` | `messages_api` | `top_p: 0.9` |
| `max_tokens` | `messages_api` | `max_tokens: 2048` |

`agent_sdk` keys pass through `auth_accelerator.build_options(**extra)`
into `ClaudeAgentOptions`; `messages_api` keys pass through directly to
`anthropic.messages.create(**extra)`. See
`.claude/rules/process-registry.md` for the full schema and
`process_registry.yaml`'s `classify` step for a live example
(`max_turns: 1`).

## Sub-projects

- [`claude-orchestration-accelerator`](./README_package.md) (this repo
  root as a Python package) — prompt resolution (`prompting/`) and the
  process registry (`registry/`), plus a default logging wrapper
  (`logging/`). See [`src/orchestration_accelerator/README.md`](./src/orchestration_accelerator/README.md)
  (package README lives alongside the package — see below).
- [`model-router/`](./model-router/README.md) — `claude-model-router-accelerator`:
  ordered model/fallback execution against a pluggable `agent_sdk` /
  `messages_api` backend.
- [`project-accelerator/`](./project-accelerator/README.md) — `claude-project-accelerator`:
  the master accelerator — the `execute(payload)` entry point and the
  `cpa` scaffold CLI.

## Existing, unaffected accelerators (separate repo, `D:\Claude\Accelerators`)

- `claude-auth-accelerator` — credential resolution.
- `ClaudeSDKLoggerAccelerator` — JSON-line tracing.

## Status

Phase 1 (this plan's Sections 4-6) is implemented. Phase 2 (a guided setup
skill) is a stub — see `.claude/skills/setup-accelerator/SKILL.md`.

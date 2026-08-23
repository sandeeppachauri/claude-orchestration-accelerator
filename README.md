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

## Environment configuration

`"environment"` (payload -> `.env`'s `ENVIRONMENT` -> `"local"`, see
`resolve_environment()`) picks which credential `auth_accelerator`
resolves, per `resolve_auth()`'s provider order: `local`/`dev` allow the
ambient `claude login` OAuth session (agent_sdk only); anything else
requires a console `ANTHROPIC_API_KEY` (works with either backend).

```python
# local / dev -- ambient `claude login` OAuth session, agent_sdk only
execute({"process": "ticketClassification", "input": "...",
         "environment": "local", "backend": "agent_sdk"})

# staging -- console API key from staging's env, either backend
execute({"process": "ticketClassification", "input": "...",
         "environment": "staging", "backend": "agent_sdk"})
execute({"process": "ticketClassification", "input": "...",
         "environment": "staging", "backend": "messages_api"})

# prod -- console API key from prod's env, either backend
execute({"process": "ticketClassification", "input": "...",
         "environment": "prod", "backend": "messages_api"})
```

Set `ANTHROPIC_API_KEY` in each environment's own `.env`/secret store
(never share a prod key into a local `.env`); `local`/`dev` skip that
requirement as long as `claude login` has run. Omitting `"environment"`
in the payload falls back to `.env`'s `ENVIRONMENT`, so a deployed
service typically sets `ENVIRONMENT` once via its own `.env` and never
passes `"environment"` per call — see `claude-auth-accelerator`'s README
for the full provider list.

## Runtime input: `{{key}}` placeholders

`prompts/*.yaml`'s `system_prompt` and optional `user_prompt` fields can
contain `{{key}}` placeholders filled from `execute()`'s payload
`"input"` at call time — static prose and dynamic values mixed in the
same string:

```python
execute({
    "process": "templatingDemo", "step": "triage",
    "input": {
        "ticket_id": "T-1", "customer_name": "Ada",
        "customer_tier": "gold", "body": "My invoice is wrong",
    },
    "backend": "agent_sdk",
})
```

The match is mandatory both ways, enforced by `PromptManager.render()`:
no placeholders in the prompt ⇒ `input` must be a plain string; any
`{{key}}` present ⇒ `input` must be a dict covering every placeholder
with no unused keys, and the prompt's `user_prompt` field becomes
required. Either mismatch raises `PromptValidationError` immediately.

See `process_registry.yaml`'s `templatingDemo` process and
`prompts/classify.yaml` (no placeholders) / `prompts/ticket_triage.yaml`
(multi-placeholder) / `prompts/escalation_decision.yaml` (placeholders in
both `system_prompt` and `user_prompt`, plus the full capability-key
table above on one step) for three worked examples, simplest to most
complex. `project-accelerator`'s generated `HOWTO.md` walks through all
three end to end for a scaffolded project.

## File upload and batch processing

Alongside `execute()`'s text path, two additional entry points follow the
same registry-driven, no-hardcoded-flow convention:

```python
from project_accelerator import upload_file, execute_batch

file_id = upload_file("invoice.pdf", backend="messages_api")

result = execute_batch({
    "batch_id": "ticketClassificationBatch_01",  # see batch_registry.yaml
    "inputs": ["ticket text 1", "ticket text 2"],
})
```

- **`upload_file(path, environment, backend, **extra)`** — `messages_api`
  uploads via Anthropic's Files API and returns a `file_id`; `agent_sdk`
  has no upload endpoint, so it returns the resolved local path, which
  flows through `build_options(**extra)` like any other capability
  passthrough key. Implemented in
  `orchestration_accelerator.file` (`FileManager`/`upload_file`).
- **`execute_batch(payload)`** — submits `payload["inputs"]` as one real
  Anthropic Message Batches API job (not a loop over `execute()`), polls
  until done, then validates each result against the referenced step's
  prompt format contract. `messages_api` only — there's no agent_sdk
  batch surface. `batch_registry.yaml` maps a `batch_id` to a
  `process_registry.yaml` process `id` (+ optional `step`), same
  never-reorder/never-subset rule as `execute()`'s payload. Implemented
  in `orchestration_accelerator.batch` (`execute_batch`).

See `.claude/rules/batch-registry.md` for the full `batch_registry.yaml`
schema, and `examples/file_upload_example.py` /
`examples/batch_processing_example.py` in any scaffolded project for
runnable samples.

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

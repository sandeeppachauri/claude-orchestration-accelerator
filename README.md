# claude-orchestration-accelerator

**Stop re-solving auth, logging, prompt config, and model routing on every
Claude Agent SDK project.** One accelerator composes them behind a single
`execute()` call — config-driven, not hardcoded.

## The problem

Every agent project re-solves the same handful of problems: credential
resolution, tracing/logging, prompt management, model fallback,
orchestration across steps. That boilerplate delays the actual business
logic, and inconsistent auth handling / no tracing / untested config
patterns raise risk and cost.

## The benefits

- **Faster delivery** — auth, logging, config, and routing are wired in
  from day one.
- **Consistency** — same pattern across every SDK project your team ships.
- **Lower risk** — shared, tested modules instead of copy-pasted one-offs.
- **Easier maintenance** — fix once in the accelerator, every project
  benefits.
- **Config-driven changes** — tune prompts or swap models via YAML, no
  redeploy.
- **One call to orchestrate** — `execute()` composes auth + logging +
  prompts + routing.

## 60-second quickstart

Scaffold a new project with the `cpa` CLI (`claude-project-accelerator`,
run via `pipx` — no local install needed):

```bash
# with a working sample process included (default)
pipx run --spec "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator" \
  cpa new --project-name my-app --sample-needed yes

# clean project, no sample
pipx run --spec "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator" \
  cpa new --project-name my-app --sample-needed no
```

Then call it:

```python
from project_accelerator import execute

result = execute({
    "process": "ticketClassification",
    "input": "some ticket text",
    "environment": "local",   # local/dev -> ambient `claude login` OAuth
    "backend": "agent_sdk",   # or "messages_api"
})
```

`execute()` resolves auth, resolves the `(process, step)` from
`process_registry.yaml`, calls the model with automatic fallback via the
model router, validates output against the prompt's format contract, then
logs the turn.

`result` is `{step_name: {output, model_used, stop_reason, usage,
tool_calls, request_id, latency_ms, session_id}, ...}` — `output` is the
validated text; the rest is metadata about that step's model call. See
`CHANGELOG.md` if migrating from a version where `result[step]` was a bare
string.

See `Master_Accelerator_Plan.md` at the repo root for the full design, and
a scaffolded project's generated `HOWTO.md` for a guided walkthrough.

## Architecture

Composed of three installable packages (this repo) plus two existing infra
accelerators (`D:\Claude\Accelerators`, separate repo):

| Accelerator | What it does |
| --- | --- |
| `claude-auth-accelerator` (existing) | Credential resolution across 3 modes — console API key -> ambient OAuth session -> OS-mounted session. `build_options()` for Agent SDK callers, `build_api_credential()` for raw Messages API callers. |
| `ClaudeSDKLoggerAccelerator` (existing) | Drop-in JSON-line tracing of tool calls and agent activity via `PreToolUse`/`PostToolUse` hooks. |
| `claude-orchestration-accelerator` (this repo root) | Prompt resolution (`PromptManager`) and the process registry, plus a default logging wrapper — on by default, all scopes enabled. |
| `claude-model-router-accelerator` (`model-router/`) | Ordered model/fallback execution against a pluggable backend (`agent_sdk` \| `messages_api`). |
| `claude-project-accelerator` (`project-accelerator/`) | The master accelerator — one entry point, `execute(payload)`, plus the `cpa` scaffold CLI. |

Nothing about which process/step/model/backend runs is hardcoded anywhere
in this path — it's entirely driven by the payload and by
`config/process_registry.yaml`.

## Core concepts

- **`process_registry.yaml`** is the single source of truth for a
  process's step order and per-step `{prompt, model, fallback}` config —
  the only place step flow is controlled. See
  `.claude/rules/process-registry.md`.
- **Capability passthrough** — any other key on a step (`max_turns`,
  `thinking`, `temperature`, `top_p`, `permission_mode`, ...) flows
  untouched through to the chosen backend's model call. Checked against
  `capability_registry.yaml`'s per-backend whitelist first, so an
  unsupported key raises `UnsupportedCapabilityError` before the model
  call, not a `TypeError` deep inside the SDK. See "Capabilities" below.
- **Guardrails** — named, config-tunable checks (`redaction`,
  `rate_limit`, ...) a step opts into via a `guardrails: [...]` key, fail
  open by default. See `.claude/rules/guardrails-registry.md`.
- **`{{key}}` placeholders** — dynamic input filled into prompts at call
  time, including threading a prior step's output forward. See "Runtime
  input" below.
- **`context_mode: session`** — a real, accumulating Agent SDK
  conversation across steps and calls (resume, auto-trim, session-store
  mirroring) instead of one-shot per-step calls. See
  `.claude/rules/context-mode.md`.
- **`parallel_processing: true`** — runs a process's steps concurrently,
  then reconciles them via a mandatory synthesis step. See
  `.claude/rules/parallel-processing.md`.
- **`stream: true`** — emits chunks to `execute()`'s `on_chunk` callback
  as they arrive, on both backends. See `.claude/rules/streaming.md`.

## Docker deployment

`cpa new --docker-project yes` generates a `Dockerfile`,
`docker-compose.yml`, `.dockerignore`, a FastAPI wrapper
(`examples/api_server.py` — `GET /health` + `POST /classify`), and
`setupDocker.md` (build/run/push/Kubernetes-deploy steps) — independent of
`--sample-needed`, so it works even on a clean project.

```bash
cpa new --project-name my-app --docker-project yes
cd my-app
docker compose up --build

curl http://localhost:8000/health
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"input": "my printer is broken"}'
```

`/classify` resolves a credential the same way `execute()` always does
(`claude-auth-accelerator`'s provider order): `ANTHROPIC_API_KEY` ->
ambient `claude login` OAuth session -> an OS-mounted session.
`docker-compose.yml` bind-mounts the host's `${HOME}/.claude`/
`${HOME}/.claude.json` into the container by default (container runs as a
non-root `agent` user matching that mount path) — if the host has already
run `claude login`, the container inherits that OAuth session with no raw
key needed. Otherwise set `ANTHROPIC_API_KEY` in the scaffolded project's
`.env` — `docker-compose.yml`'s `env_file` passes it through. See
`project-accelerator/README.md`'s "Docker deployment" section and the
generated `docs/HOWTO.md` for full detail, including Kubernetes deploy
steps.

## Key capabilities

Beyond the core `execute()` call:

- **True multi-turn sessions** — `context_mode: session` keeps a live
  conversation accumulating across steps and calls, with `resume` and
  auto-trimming built in.
- **Parallel step execution** — `parallel_processing: true` runs multiple
  steps concurrently, then auto-synthesizes the results via a dedicated
  synthesis step.
- **Real-time streaming** — `stream: true` plus an `on_chunk` callback
  delivers token-by-token responses on both the Agent SDK and Messages
  API backends.
- **Steps that build on steps** — later steps reference earlier steps'
  output via `{{step_output}}` placeholders.
- **Prompt caching** — opt any step into an Anthropic cache breakpoint,
  no extra plumbing beyond a config key.
- **Richer `execute()` results** — usage, latency, stop reason, session
  ID, tool calls: structured, not just a string.
- **Custom endpoint support** — `ANTHROPIC_BASE_URL` threaded through
  everywhere, for teams routing via a proxy or gateway.
- **Deep tracing** — logs show exactly what was sent to the model, not
  just a summary after the fact.

## Guardrails

Enforced per step, config-driven, fail-open by default (no `guardrails`
key or missing config file = no restriction, same posture as MCP
scoping):

- **`redaction`** — denies a tool call if input matches a regex pattern
  (e.g. SSN-shaped strings). Configured in `config/guardrails.yaml`.
- **`rate_limit`** — denies a tool call once `max_calls` is hit within a
  trailing time window.

Attach via `guardrails: [redactPII]` on any step — no code change,
resolved against `config/guardrails.yaml`. See
`.claude/rules/guardrails-registry.md`.

## What `cpa new` generates

Every scaffolded project ships a full, ready-to-run skeleton:

| Path | Contents |
| --- | --- |
| `.claude/` | Full reference Claude Code project skeleton — agents, commands, hooks, plugins, rules, skills |
| `config/`, `docs/`, `examples/` | Sample config, documentation stubs, runnable examples (file upload, batch processing) |
| `prompts/*.yaml` | Prompt configs — scope, format, constraints as structured YAML, not buried prose |
| `pipeline/run_pipeline.py` | Entry-point script wired to `execute()` |
| `logs/trace.log` | Default tracing output — on by default, all scopes enabled |
| `.env` + `logger_config.json` + `.mcp.json` | Environment, logging, and MCP config — pre-wired, ready to edit |
| `tests/` | Sample pipeline test included |

## Where this fits vs. other Claude tooling

| If you're... | Use | Why |
| --- | --- | --- |
| Building an agent without implementing the tool loop yourself | Agent SDK | Runs the agent loop in your own process (Python/TypeScript) |
| Doing interactive dev or one-off tasks from a terminal | Claude Code CLI | Terminal interface for daily interactive use |
| Calling the API directly, implementing the tool loop yourself | Client SDK | Direct Anthropic API access, no agent loop provided |
| Running long-running/async agents without managing your own sandbox | Managed Agents | Hosted REST API — Anthropic runs the agent and sandbox |

**This accelerator's focus is the Agent SDK path** — auth, logging, prompt
config, and orchestration for teams building agents as a library in their
own process.

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
`anthropic.messages.create(**extra)`. Every capability key is checked
against `capability_registry.yaml`'s per-backend whitelist first -- an
unlisted key raises `UnsupportedCapabilityError` immediately, not a
`TypeError` deep inside the SDK/API client (the two backends' allowed
sets are disjoint, not a shared superset -- see
`.claude/rules/capability-registry.md`). See
`.claude/rules/process-registry.md` for the full `process_registry.yaml`
schema and `process_registry.yaml`'s `classify` step for a live example
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

`ANTHROPIC_BASE_URL` (defaulted to `https://api.anthropic.com` in a
scaffolded `.env`) routes both backends' raw Messages API calls to a
custom endpoint — scope it per environment with
`ANTHROPIC_BASE_URL_<ENV>` (e.g. `ANTHROPIC_BASE_URL_PROD`), resolved by
`auth_accelerator.build_base_url()`/`resolve_auth()` the same way
`ANTHROPIC_API_KEY` is. The agent_sdk backend picks it up automatically
via `credential.env`; no separate wiring needed there.

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

Enforced by `PromptManager.render()`: no placeholders in the prompt ⇒
`input` must be a plain string; any `{{key}}` present ⇒ `input` must be
a dict covering every placeholder, and the prompt's `user_prompt` field
becomes required. Either mismatch raises `PromptValidationError`
immediately. Extra dict keys not referenced by this step's placeholders
are allowed and ignored -- a multi-step run without an explicit `step`
shares one flat `input` dict across steps that may need different
subsets of it.

See `process_registry.yaml`'s `templatingDemo` process and
`prompts/classify.yaml` (no placeholders) / `prompts/ticket_triage.yaml`
(multi-placeholder) / `prompts/escalation_decision.yaml` (placeholders in
both `system_prompt` and `user_prompt`, plus the full capability-key
table above on one step) for three worked examples, simplest to most
complex. `project-accelerator`'s generated `HOWTO.md` walks through all
three end to end for a scaffolded project.

A later step can also pull in an earlier step's raw result, via a
placeholder named `{{<stepName>_output}}` -- e.g. `{{triage_output}}` for
`triage`'s result, `{{classify_output}}` for `classify`'s. This name
isn't declared in the earlier step's own prompt YAML; it's generated
mechanically from that step's key in `steps: [...]`. See
`.claude/rules/process-registry.md`'s "Threading a prior step's output"
section for the full rules (only reaches placeholder-taking steps,
required once declared, must be supplied by hand when running that step
standalone).

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

### `process_registry.yaml` vs `batch_registry.yaml` -- what goes where

The two files never overlap in what they configure:

| | `process_registry.yaml` | `batch_registry.yaml` |
| --- | --- | --- |
| Owns | The **model invocation layer**: step order, `prompt`, `model`, `fallback` chain, and any capability passthrough key (`max_turns`, `thinking`, `temperature`, ...) | **Batch-run mechanics only**: `batch_id`, which `process`/`step` to run, `environment`, `poll_interval_seconds`, `poll_timeout_seconds` |
| Model/prompt info | Yes -- the only place it lives | No -- always resolved by following `batch_registry.yaml`'s `process` (+ optional `step`) reference back into `process_registry.yaml` |
| Used by | `execute()` (text path) and `execute_batch()` (batch path, indirectly) | `execute_batch()` only |

So a batch entry never duplicates model config -- it just points at a
`(process, step)` and `execute_batch()` reads that step's `prompt`/
`model`/`fallback`/capabilities straight out of `process_registry.yaml`.
See `.claude/rules/process-registry.md` and `.claude/rules/batch-registry.md`
for the full field-by-field schema of each.

## Sub-projects

- [`claude-orchestration-accelerator`](./docs/README_package.md) (this repo
  root as a Python package) — prompt resolution (`prompting/`) and the
  process registry (`registry/`), plus a default logging wrapper
  (`logging/`).
- [`model-router/`](./model-router/README.md) — `claude-model-router-accelerator`:
  ordered model/fallback execution against a pluggable `agent_sdk` /
  `messages_api` backend.
- [`project-accelerator/`](./project-accelerator/README.md) — `claude-project-accelerator`:
  the master accelerator — the `execute(payload)` entry point and the
  `cpa` scaffold CLI, including `cpa new --docker-project yes` (Docker/
  Kubernetes deployment artifacts + a FastAPI example, see that README's
  "Docker deployment" section and this repo's own root `Dockerfile`/
  `docker-compose.yml`/`examples/api_server.py` for a live reference).

## Existing, unaffected accelerators (separate repo, `D:\Claude\Accelerators`)

- `claude-auth-accelerator` — credential resolution.
- `ClaudeSDKLoggerAccelerator` — JSON-line tracing.

# claude-orchestration-accelerator

This repository is built on the `claude-project-accelerator` stack. Any
project scaffolded from here (via `cpa new --project-name <name>`) inherits
this same convention set.

## What this project is

A master accelerator composed of three installable packages plus two
existing infra accelerators:

- `claude-auth-accelerator` (existing, `Accelerators` repo) — credential
  resolution: `build_options(environment, model, max_turns, **extra)` for
  Claude Agent SDK callers, `build_api_credential(environment)` for raw
  Messages API callers.
- `ClaudeSDKLoggerAccelerator` (existing, `Accelerators` repo) — JSON-line
  tracing via `PreToolUse`/`PostToolUse` hooks and `log_event()`.
- `claude-orchestration-accelerator` (this repo root) — prompt resolution
  (`orchestration_accelerator.prompting.PromptManager`) and the process
  registry (`orchestration_accelerator.registry`), plus a default logging
  wrapper (`orchestration_accelerator.logging`).
- `claude-model-router-accelerator` (`model-router/`) — ordered
  model/fallback execution against a pluggable backend
  (`"agent_sdk"` | `"messages_api"`).
- `claude-project-accelerator` (`project-accelerator/`) — the master
  accelerator: one library entry point, `execute(payload)`, plus the `cpa`
  scaffold CLI.

## The entry point

```python
from project_accelerator import execute

result = execute({
    "process": "ticketClassification",
    "step": "classify",       # optional — omit to run every step in order
    "input": "some ticket text",
    "environment": "local",   # optional — falls back to .env's ENVIRONMENT
    "backend": "agent_sdk",   # "agent_sdk" | "messages_api"
})
```

Nothing about which process/step/model/backend runs is hardcoded anywhere
in this path — it is entirely driven by the payload and by
`process_registry.yaml`.

## Configuration

- `process_registry.yaml` is the single source of truth for a process's
  step order and per-step `{prompt, model, fallback}` configuration. This
  is the *only* place step flow is controlled — a payload can select a
  process and, optionally, narrow to one step, but it can never reorder,
  skip, or subset a process's `steps` list. Every step capability key
  (anything besides `prompt`/`model`/`fallback`/`system_prompt`) is
  checked against `capability_registry.yaml`'s per-backend whitelist
  before the model call.
- `capability_registry.yaml` is the whitelist of capability keys allowed
  per backend (`agent_sdk` / `messages_api`) — not environment-specific
  (unlike `.env`): the same keys must be valid on every environment a
  backend runs in.
- `.env` carries `ENVIRONMENT` (default resolved environment) and
  `DEFAULT_MODEL` (used by the built-in default configuration fallback
  when a `(process, step)` isn't defined in `process_registry.yaml`).
- `logger_config.json` configures the default logging wrapper (all 8
  scopes enabled by default).

## Running tests

```
pytest tests/test_sample_pipeline.py
```

See each sub-project's own README (`claude-orchestration-accelerator`,
`model-router/`, `project-accelerator/`) for install/usage detail.

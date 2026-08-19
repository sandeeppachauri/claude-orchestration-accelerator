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

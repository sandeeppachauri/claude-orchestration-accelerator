# claude-project-accelerator

The master accelerator. Composes `claude-auth-accelerator`,
`ClaudeSDKLoggerAccelerator`, `claude-orchestration-accelerator`, and
`claude-model-router-accelerator` behind one library call and one CLI.

## Library entry point

```python
from project_accelerator import execute

result = execute({
    "process": "ticketClassification",
    "step": "classify",        # optional -- omit to run every step in order
    "input": "some ticket text",
    "environment": "local",    # optional -- falls back to .env's ENVIRONMENT
    "backend": "agent_sdk",    # "agent_sdk" | "messages_api"
})
```

`execute()` resolves auth, resolves `(process, step)` from
`process_registry.yaml` (falling back to the built-in default
configuration when undefined), calls the model with fallback via the
model router, validates output against the prompt's format contract, and
logs the turn.

The payload's `"step"` field only narrows to one step -- it never
reorders/subsets a process's `steps` list. `process_registry.yaml` is the
only place step flow is controlled.

## CLI

```bash
pip install claude-project-accelerator
cpa new --project-name my-app --venv
cpa new --project-name my-app --path /some/other/dir --venv
cpa new --project-name my-app --python /path/to/existing/venv/bin/python
```

Generates a starter project: `prompts/*.yaml`, `process_registry.yaml`,
`.env`, `logger_config.json`, `pipeline/run_pipeline.py`, a README, the
full reference Claude Code project skeleton (one-time snapshot copy from
this repo's root), and `tests/test_sample_pipeline.py`. Installs all four
accelerators into the chosen venv (or the active environment with
`--no-venv`).

- `--path <dir>` -- parent directory to scaffold into (default: current
  directory). The project is created at `<dir>/<project-name>`.
- `--python <exe>` -- install into an existing interpreter/venv instead of
  creating a new one. Mutually exclusive with `--venv`.

## Tests

```bash
pytest tests -q
```

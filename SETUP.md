# Setup, Install & Test

Covers the full `claude-orchestration-accelerator` repo: three installable
packages (`claude-orchestration-accelerator`, `claude-model-router-accelerator`,
`claude-project-accelerator`) plus the two pre-existing accelerators they
depend on (`claude-auth-accelerator`, `claude-sdk-logger-accelerator`), which
live in the sibling repo `D:\Claude\Accelerators` and are **not** on PyPI.

## 1. Prerequisites

- Python >= 3.10 (developed/tested on 3.14)
- `pip`
- The sibling repo present at `D:\Claude\Accelerators` (source of
  `claude-auth-accelerator` and `claude-sdk-logger-accelerator` — installed
  via local path, since neither is published)
- An `ANTHROPIC_API_KEY` (or `claude login` ambient OAuth session) only
  needed for live model calls — everything else (install, unit tests,
  scaffold) works without one

## 2. One-time environment setup

From `D:\Claude\claude-orchestration-accelerator`:

```bash
python -m venv .venv
.venv\Scripts\activate        # PowerShell: .venv\Scripts\Activate.ps1
```

## 3. Install the two pre-existing accelerators (local path, editable)

```bash
pip install -e "D:\Claude\Accelerators\claude-auth-accelerator"
pip install -e "D:\Claude\Accelerators\ClaudeSDKLoggerAccelerator"
```

## 4. Install the three packages in this repo (editable, dependency order)

Order matters — each depends on the one before it:

```bash
pip install -e ".[dev]"                                   # claude-orchestration-accelerator (repo root)
pip install -e "model-router[dev,agent_sdk,messages_api]"  # claude-model-router-accelerator
pip install -e "project-accelerator[dev]"                  # claude-project-accelerator (also gives you the `cpa` CLI)
```

`claude-orchestration-accelerator`'s logging wrapper is an optional extra
(`pip install -e ".[dev,logging]"`) since `claude-sdk-logger-accelerator`
isn't a hard dependency — install it if you want tracing wired automatically.

## 5. Verify install

```bash
python -c "import orchestration_accelerator, model_router_accelerator, project_accelerator; print('ok')"
cpa --help
```

## 6. Run the test suite

Each package has its own tests; all mock network/API calls, so no
credential is required:

```bash
pytest                              # claude-orchestration-accelerator (repo root)
pytest model-router                 # claude-model-router-accelerator
pytest project-accelerator          # claude-project-accelerator (includes integration tests)
```

Or run everything from the repo root in one go:

```bash
pytest . model-router project-accelerator
```

Expected: 14 passed (root) + 10 passed (model-router) + 9 passed
(project-accelerator).

## 7. Scaffold a new project with the CLI

```bash
cpa new --project-name my-app --no-venv     # installs into the currently active env
# or
cpa new --project-name my-app --venv        # creates my-app/.venv and installs there
```

This generates, under `./my-app/`:

- `prompts/*.yaml`, `process_registry.yaml` (pre-populated with the
  `ticketClassification` and `onboarding` sample processes)
- `.env` (`ENVIRONMENT=local`, `DEFAULT_MODEL=claude-sonnet-5`)
- `logger_config.json`
- `pipeline/run_pipeline.py` (reads steps/config from `process_registry.yaml`
  — nothing hardcoded)
- the full reference Claude Code skeleton (`CLAUDE.md`, `.claude/settings.json`,
  `.claude/skills/`, `.claude/agents/`, `.claude/rules/`, etc.), copied as a
  one-time snapshot
- `tests/test_sample_pipeline.py`
- all four accelerator packages installed into the chosen environment

## 8. Test a scaffolded project

```bash
cd my-app
pytest tests/test_sample_pipeline.py
```

To actually run the pipeline end to end (needs a real credential —
`ANTHROPIC_API_KEY` env var or an ambient `claude login` OAuth session):

```bash
python pipeline/run_pipeline.py ticketClassification "sample ticket text"
```

## 9. Guided setup instead of steps 7–8 (optional)

Inside a Claude Code session in this repo, invoke the `setup-accelerator`
skill (`.claude/skills/setup-accelerator/SKILL.md`) — it interviews you
(project name/dir, venv choice, which processes, per-step prompt/model/
fallback, target environment), runs `cpa new` for you, writes the resulting
`process_registry.yaml`/`prompts/*.yaml` to match your answers, offers to
run a smoke test, and reports what was configured vs. left on the built-in
default.

## 10. Using the library entry point directly

```python
from project_accelerator import execute

result = execute({
    "process": "ticketClassification",
    "step": "classify",          # optional — omit to run the full process
    "input": "sample ticket text",
    "environment": "local",      # optional — falls back to .env's ENVIRONMENT
    "backend": "agent_sdk",      # "agent_sdk" | "messages_api"
})
```

## Troubleshooting

- **`ModuleNotFoundError: auth_accelerator` / `sdk_logger_accelerator`** —
  step 3 wasn't run, or the sibling `Accelerators` repo path is wrong for
  this machine.
- **`AuthResolutionError` at runtime** — no credential resolved; set
  `ANTHROPIC_API_KEY` or run `claude login`. Unit tests don't need this
  (all mocked); only live `execute()`/`run_pipeline.py` calls do.
- **`cpa: command not found`** after install — the venv that has
  `project-accelerator` installed isn't the active one; re-activate it.

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

Two setup paths exist — pick one:

- **Path A — Manual (local clone)**: you have both this repo and the
  sibling `D:\Claude\Accelerators` repo checked out; installs everything
  editable from local paths. Use this for active development on any of
  the four packages.
- **Path B — Zero-clone**: no local checkout of anything needed; `cpa`
  and everything it scaffolds pull straight from GitHub. Use this to just
  *use* the tooling (e.g. scaffold a new project) without cloning source.

Steps 2–5 below are forked by path; steps 6 onward apply to whichever path
you took (Path B skips straight to step 8).

## 2A. One-time environment setup — Manual path

Clone this repo, then run everything below from inside it:

```bash
git clone https://github.com/sandeeppachauri/claude-orchestration-accelerator.git D:\Claude\claude-orchestration-accelerator
cd D:\Claude\claude-orchestration-accelerator
python -m venv .venv
.venv\Scripts\activate        # PowerShell: .venv\Scripts\Activate.ps1
```

## 3A. Install the two pre-existing accelerators — Manual path

Requires the sibling repo checked out at `D:\Claude\Accelerators`:

```bash
pip install -e "D:\Claude\Accelerators\claude-auth-accelerator"
pip install -e "D:\Claude\Accelerators\ClaudeSDKLoggerAccelerator"
```

No local checkout of `Accelerators`? Install those two straight from git
instead (still Path A, just skip cloning that one repo):

```bash
pip install "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=claude-auth-accelerator"
pip install "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=ClaudeSDKLoggerAccelerator"
```

Pin a specific commit/tag/branch by appending `@<ref>` before the `#`, e.g.
`git+https://github.com/sandeeppachauri/Accelerators.git@v0.2.0#subdirectory=claude-auth-accelerator`.

## 4A. Install the three packages in this repo — Manual path

Editable install, in dependency order (each depends on the one before it):

```bash
pip install -e ".[dev]"                                   # claude-orchestration-accelerator (repo root)
pip install -e "model-router[dev,agent_sdk,messages_api]"  # claude-model-router-accelerator
pip install -e "project-accelerator[dev]"                  # claude-project-accelerator (also gives you the `cpa` CLI)
```

`claude-orchestration-accelerator`'s logging wrapper is an optional extra
(`pip install -e ".[dev,logging]"`) since `claude-sdk-logger-accelerator`
isn't a hard dependency — install it if you want tracing wired automatically.

## 5A. Verify install — Manual path

```bash
python -c "import orchestration_accelerator, model_router_accelerator, project_accelerator; print('ok')"
cpa --help
```

## 2B–5B. Zero-clone path

No venv, no clone, no manual pip sequence — jump straight to step 8's
"Zero-clone install" section, which covers installing/running `cpa` via
`pipx run` or a single `pip install` from GitHub. Everything it scaffolds
(the four accelerator packages) is pulled automatically. Come back to
steps 9–12 afterward.

## 6. Run the test suite (Manual path)

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

## 7. Run the examples (Manual path)

Each package ships a runnable example under its own `examples/` dir. The
registry/prompting example needs no credential; the other three make real
model calls, so they need `ANTHROPIC_API_KEY` set or an ambient
`claude login` OAuth session -- without one they print a message and exit
cleanly instead of crashing:

```bash
python examples/run_orchestration_accelerator_example.py           # orchestration_accelerator alone -- no credential needed
python examples/run_ticket_classification.py                       # full stack via project_accelerator.execute(), real model calls
python model-router/examples/run_router_example.py                 # model-router alone, real model call
python project-accelerator/examples/run_execute_example.py         # project_accelerator entry point, real model calls
```

## 8. Scaffold a new project with the CLI (both paths)

```bash
cpa new --project-name my-app --no-venv     # installs into the currently active env
# or
cpa new --project-name my-app --venv        # creates my-app/.venv and installs there
# or
cpa new --project-name my-app --path /some/other/dir --venv   # scaffold elsewhere
# or
cpa new --project-name my-app --python /path/to/existing/venv/bin/python  # reuse an existing env
```

`--path` defaults to the current directory. `--python` installs into an
existing interpreter/venv instead of creating one and cannot be combined
with `--venv`.

By default `cpa new` looks for the sibling `Accelerators` repo (containing
`claude-auth-accelerator` and `ClaudeSDKLoggerAccelerator`) at
`../Accelerators` relative to this repo. When that (or this repo itself)
isn't checked out locally, it falls back to installing each accelerator
straight from GitHub instead — so `cpa` works with no local clone at all
(see "Zero-clone install" below). `--accelerators-path <dir>` points at a
local checkout instead of the default, and `--allow-missing-accelerators`
tolerates a failed install of `claude-auth-accelerator`/
`ClaudeSDKLoggerAccelerator` specifically (this repo's own two packages
are never optional). See the root `requirements.txt` for the pip prereqs
needed to bootstrap a fresh environment before running `cpa new`.

### Zero-clone install

No local checkout needed — `cpa` itself, and everything it scaffolds, can
be installed straight from this GitHub repo:

```bash
# one-off, no persistent install (uses pipx; ephemeral venv):
pipx run --spec "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator" cpa new --project-name my-app

# or install cpa itself, then run it as usual:
pip install "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator"
cpa new --project-name my-app
```

Both pull `claude-orchestration-accelerator` and `claude-model-router-accelerator`
from this repo automatically (declared as git dependencies), and `cpa new`
installs `claude-auth-accelerator`/`ClaudeSDKLoggerAccelerator` from the
`Accelerators` repo the same way.

This generates, under `./my-app/` (or `<path>/my-app/` with `--path`):

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

## 9. Test a scaffolded project

```bash
cd my-app
pytest tests/test_sample_pipeline.py
```

To actually run the pipeline end to end (needs a real credential —
`ANTHROPIC_API_KEY` env var or an ambient `claude login` OAuth session):

```bash
python pipeline/run_pipeline.py ticketClassification "sample ticket text"
```

## 10. Guided setup instead of steps 8–9 (optional)

Inside a Claude Code session in this repo, invoke the `setup-accelerator`
skill (`.claude/skills/setup-accelerator/SKILL.md`) — it interviews you
(project name/dir, venv choice, which processes, per-step prompt/model/
fallback, target environment), runs `cpa new` for you, writes the resulting
`process_registry.yaml`/`prompts/*.yaml` to match your answers, offers to
run a smoke test, and reports what was configured vs. left on the built-in
default.

## 11. Using the library entry point directly

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

## 12. Deploying code changes

All four packages (step 4) are installed editable (`pip install -e`), so
most changes take effect immediately, with no reinstall:

- **Python source, `process_registry.yaml`, `prompts/*.yaml`,
  `logger_config.json`, `.env`** — picked up on next run automatically.
  A long-running process (e.g. a server importing these packages) must be
  restarted to pick up the change; a one-shot script (`pytest`,
  `run_pipeline.py`, the `examples/`) picks it up on its next invocation.
- **`pyproject.toml` dependency changes** (new/changed package deps in any
  of the four `pyproject.toml`s) — re-run the relevant install command from
  step 3/4 for that package only, in order if the change is in a package
  others depend on.
- **New/changed console-script entry points** (e.g. `cpa`) — re-run
  `pip install -e "project-accelerator[dev]"`.

After any change, re-verify before considering it deployed:

```bash
pytest . model-router project-accelerator   # step 6
python examples/run_ticket_classification.py  # or the relevant example from step 7
```

If the change is scaffold-facing (`project-accelerator/templates/`, the
`cpa` CLI), re-run `cpa new` (step 8) into a scratch dir to confirm
generated output still matches.

## Troubleshooting

- **`ModuleNotFoundError: auth_accelerator` / `sdk_logger_accelerator`** —
  step 3 wasn't run, or the sibling `Accelerators` repo path is wrong for
  this machine.
- **`AuthResolutionError` at runtime** — no credential resolved; set
  `ANTHROPIC_API_KEY` or run `claude login`. Unit tests don't need this
  (all mocked); only live `execute()`/`run_pipeline.py` calls do.
- **`cpa: command not found`** after install — the venv that has
  `project-accelerator` installed isn't the active one; re-activate it.

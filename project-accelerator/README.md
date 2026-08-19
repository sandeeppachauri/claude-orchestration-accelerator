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

No local checkout required -- `cpa` and everything it scaffolds installs
straight from GitHub:

```bash
# one-shot, no persistent install:
pipx run --spec "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator" cpa new --project-name my-app

# or install cpa once, then run it as usual:
pip install "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator"
cpa new --project-name my-app --venv
cpa new --project-name my-app --path /some/other/dir --venv
cpa new --project-name my-app --python /path/to/existing/venv/bin/python
```

Generates a starter project: `prompts/*.yaml`, `process_registry.yaml`,
`.env`, `logger_config.json`, `pipeline/run_pipeline.py`, a README, the
full reference Claude Code project skeleton, and
`tests/test_sample_pipeline.py`. The skeleton and sample config ship as
package data (`scaffold_data/`) inside this package, not read off a repo
checkout, so scaffolding works the same whether `cpa` itself came from a
local editable install or straight from git. Installs all four
accelerators into the chosen venv (or the active environment with
`--no-venv`) -- editable from a local checkout of this repo/`Accelerators`
if one is present next to it, otherwise straight from GitHub.

- `--path <dir>` -- parent directory to scaffold into (default: current
  directory). The project is created at `<dir>/<project-name>`.
- `--python <exe>` -- install into an existing interpreter/venv instead of
  creating a new one. Mutually exclusive with `--venv`.
- `--accelerators-path <dir>` -- path to a local checkout of the sibling
  `Accelerators` repo (`claude-auth-accelerator`, `ClaudeSDKLoggerAccelerator`),
  for when it's checked out somewhere other than the default `../Accelerators`
  relative to this repo. Without it, those two packages install from GitHub.
- `--allow-missing-accelerators` -- scaffold anyway even if
  `claude-auth-accelerator`/`ClaudeSDKLoggerAccelerator` fail to install
  (network unavailable, etc).

See the root [`requirements.txt`](../requirements.txt) for the pip
prereqs needed to bootstrap a brand-new environment before running `cpa
new` or this repo's own test suite.

## Tests

```bash
pytest tests -q
```

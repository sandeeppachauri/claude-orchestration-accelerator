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

`result` is `{step_name: {output, model_used, stop_reason, usage,
tool_calls, request_id, latency_ms}, ...}` -- `output` is the validated
text (what a bare `results[step_name]` string carried before this
field was added); the rest is metadata about that step's model call
(`tool_calls`/`session_id` agent_sdk-only, `request_id`
messages_api-only). See `../CHANGELOG.md` for the migration note.

The payload's `"step"` field only narrows to one step -- it never
reorders/subsets a process's `steps` list. `process_registry.yaml` is the
only place step flow is controlled.

## Environment configuration

`"environment"` (payload -> `.env`'s `ENVIRONMENT` -> `"local"`) picks
which credential `claude-auth-accelerator` resolves: `local`/`dev` allow
the ambient `claude login` OAuth session (agent_sdk only); any other
value (`staging`, `prod`, ...) requires a console `ANTHROPIC_API_KEY` set
in that environment's own `.env`/secret store, and works with either
backend.

```python
execute({"process": "ticketClassification", "input": "...",
         "environment": "local", "backend": "agent_sdk"})     # OAuth session
execute({"process": "ticketClassification", "input": "...",
         "environment": "staging", "backend": "messages_api"})  # console key
execute({"process": "ticketClassification", "input": "...",
         "environment": "prod", "backend": "agent_sdk"})        # console key
```

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
- `--sample-needed yes|no` (default `yes`) -- whether to include the
  `templatingDemo` example process (and its `dummyDemoSkill`) in the
  scaffold. `no` gives a clean project with just `ticketClassification`/
  `onboarding` and no `{{key}}`-placeholder example.
- `--docker-project yes|no` (default `no`) -- generate `Dockerfile`,
  `docker-compose.yml`, `.dockerignore`, a FastAPI wrapper
  (`examples/api_server.py`, `GET /health` + `POST /classify`), and
  `setupDocker.md` (build/run/push/Kubernetes-deploy steps) so the
  scaffolded project can be built into an image and deployed/tested in a
  container. Independent of `--sample-needed` -- works even with
  `--sample-needed no`, since `/classify` returns a clear error (not a
  crash) if `ticketClassification` isn't defined yet.

### Docker deployment (`--docker-project yes`)

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
`${HOME}/.claude.json` into the container by default (the container runs
as a non-root `agent` user matching that mount path) -- if the host has
already run `claude login`, the container inherits that OAuth session
with no raw key needed. Otherwise set `ANTHROPIC_API_KEY` in the
scaffolded project's `.env` -- `docker-compose.yml`'s `env_file` passes
it into the container. See the generated `docs/HOWTO.md`'s "Docker
deployment" section for full detail.

See the root [`requirements.txt`](../requirements.txt) for the pip
prereqs needed to bootstrap a brand-new environment before running `cpa
new` or this repo's own test suite.

## `process_registry.yaml` vs `batch_registry.yaml`

`process_registry.yaml` is the model invocation layer -- step order,
`prompt`, `model`, `fallback`, and any capability passthrough key. It is
the *only* place model/prompt config lives. `batch_registry.yaml` carries
only batch-run mechanics (`batch_id`, `process`/`step` reference,
`environment`, `poll_interval_seconds`, `poll_timeout_seconds`) -- it has
no model fields of its own and always resolves those through the
`process_registry.yaml` step it points at. See the root
[`README.md`](../README.md#process_registryyaml-vs-batch_registryyaml----what-goes-where)
for the side-by-side table, and `.claude/rules/process-registry.md` /
`.claude/rules/batch-registry.md` for full schemas.

## Tests

```bash
pytest tests -q
```

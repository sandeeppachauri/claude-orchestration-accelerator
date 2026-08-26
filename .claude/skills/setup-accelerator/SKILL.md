---
name: setup-accelerator
description: >
  Conversationally sets up a new project on the claude-orchestration-accelerator
  stack. Interviews the user (project name/location, venv, whether to include
  the templatingDemo example, which process(es) to configure, per-step
  prompt/model/fallback choices, target environment), runs `cpa new`
  (claude-project-accelerator), writes/edits the resulting process_registry.yaml
  and prompts/*.yaml to match the interview, optionally runs a smoke test, and
  reports back a summary. Use when a user wants to start a new project on this
  accelerator stack, wants a guided/interviewed setup instead of hand-editing
  config, or asks to run `cpa new` with help choosing processes/models.
---

# setup-accelerator

This skill is a conversational wrapper around `claude-project-accelerator`'s
`cpa new` CLI. It does not replace the CLI — it interviews the user, runs the
CLI, then edits the generated `process_registry.yaml` (and, if needed,
`prompts/*.yaml`) to match what the user asked for. Follow the steps below in
order, using `AskUserQuestion` for the interview and `Bash`/`Read`/`Write`/`Edit`
for the mechanical work.

## What you're driving

- `cpa new --project-name <name> [--venv|--no-venv] [--sample-needed yes|no]`
  scaffolds a directory named `<name>` under the current working directory.
  It always copies the shipped sample `process_registry.yaml` and
  `prompts/*.yaml`, writes a `.env` with `ENVIRONMENT=local` /
  `DEFAULT_MODEL=claude-sonnet-5`, copies the reference `.claude/` skeleton,
  `CLAUDE.md`, `CLAUDE.local.md`, writes `pipeline/run_pipeline.py`,
  `tests/test_sample_pipeline.py`, `README.md`, and installs all four
  accelerator packages (editable) into either a fresh `.venv` (default,
  `--venv`) or the currently active environment (`--no-venv`).
  `--sample-needed` (default `yes`) controls whether the `templatingDemo`
  example process and its `dummyDemoSkill` are included alongside
  `ticketClassification`/`onboarding` — pass `no` if the user wants a clean
  scaffold with no `{{key}}`-placeholder example. There is no flag to pick
  a process at scaffold time or to change the project's parent directory —
  the project always lands under wherever `cpa new` is invoked from, so
  `cd` there first if the user wants a specific target directory.
- The single source of truth for step order and per-step config is
  `process_registry.yaml` at the project root, per
  `.claude/rules/process-registry.md`:
  ```yaml
  <processName>:
    id: <processName>_01
    description: <text>
    steps: [<stepA>, <stepB>, ...]
    <stepA>:
      prompt: <file under prompts/>.yaml
      model: <model id>
      fallback: [<model id>, ...]
  ```
  Any `(process, step)` pair not defined there falls back at runtime to a
  built-in default (one model from `.env`'s `DEFAULT_MODEL`, one generic
  system prompt, no fallback chain, no output-format validation).
- The call shape callers use is `execute(payload)` from `project_accelerator`,
  where `payload` has required keys `process`, `input`, `backend`
  (`"agent_sdk"` or `"messages_api"`) and optional keys `step`, `environment`.

## Step 1 — Interview

Run this as a short back-and-forth using `AskUserQuestion` (batch related
questions where reasonable; don't interrogate one field at a time if the
user has already volunteered several answers in their initial request).

1. **Project name and target directory.** Ask for the project name (used
   verbatim as `--project-name`) and where it should be created. If a
   directory is given, `cd` there (creating it with `mkdir -p` if it doesn't
   exist) before running `cpa new` — remember `cpa new` always scaffolds
   under the *current* working directory.
2. **Virtual environment.** Ask whether to create a fresh venv (`--venv`,
   the default) or install into the currently active environment
   (`--no-venv`).
3. **Example process.** Ask whether to include the shipped `templatingDemo`
   example (`--sample-needed yes`, the default) or skip it for a clean
   scaffold (`--sample-needed no`). Skip asking if the user's request
   already implies one (e.g. "just give me a clean project" -> `no`).
4. **Process(es) to configure.** Offer three options:
   - Reuse `ticketClassification` as-is (steps: `classify`, `extract`,
     `respond`).
   - Reuse `onboarding` as-is (steps: `welcome`, `verify`, `finalize`).
   - Define a new process — ask for a process id/name, a one-line
     description, and its ordered list of step names.
   The user may pick more than one (e.g. keep `ticketClassification` and
   also define a new process); track this as a list.
5. **Per new/customized step**, for every step in a newly defined process
   (or any shipped-sample step the user wants to override), ask:
   - Prompt: reuse one of the six shipped prompt files
     (`classify.yaml`, `extract_v2.yaml`, `classify_soa.yaml`,
     `welcome.yaml`, `verify_kyc.yaml`, `finalize.yaml`) as a starting
     template, or write a new prompt from scratch (get: system prompt
     text, and optionally an output format contract — type/allowed
     values/wrapper — following the shape shown in `prompts/classify.yaml`).
   - Model for that step (a plain string, e.g. `claude-sonnet-5`).
   - Fallback chain (an ordered list of model strings, possibly empty).
   Steps left untouched from a reused sample process keep their existing
   prompt/model/fallback — don't re-ask about those.
6. **Target environment and default model.** Ask which of `local`/`dev`/`prod`
   this project's `.env` should default to, and what `DEFAULT_MODEL` should
   be (used both as the generic-default fallback and as a sensible answer
   if the user has no strong per-step model preference).

## Step 2 — Run `cpa new`

From the chosen target directory:

```bash
cpa new --project-name <name> --venv --sample-needed yes   # flags per the interview
```

If `cpa` isn't on PATH, fall back to
`python -m project_accelerator.cli new --project-name <name> [--venv|--no-venv] [--sample-needed yes|no]`
from within an environment that has `claude-project-accelerator` installed
(e.g. the repo's own root if this is being run from within
`claude-orchestration-accelerator` during development).

Confirm the scaffold succeeded (check the printed "Scaffolded project ..."
line and that `<name>/process_registry.yaml` exists) before continuing.

## Step 3 — Edit process_registry.yaml (and prompts/) to match the interview

Read `<name>/process_registry.yaml` (it currently holds the two shipped
samples, `ticketClassification` and `onboarding`, verbatim). Then:

- If the user did **not** want a shipped sample process, remove its
  top-level block from the YAML (and, optionally, delete its now-unused
  files under `prompts/` — only if nothing else references them).
- If the user wants a shipped sample **unmodified**, leave its block as-is.
- If the user wants a shipped sample **with overrides** on specific steps,
  edit just those steps' `prompt`/`model`/`fallback` values.
- For each **new process**, append a top-level block following the schema
  above: `id`, `description`, `steps` (the ordered list from the
  interview), and one sub-block per step with `prompt`/`model`/`fallback`.
- For each **new prompt file** the interview produced, write it under
  `<name>/prompts/<name>.yaml` following the structure in
  `prompts/classify.yaml` (`step`, `version`, optional `scope`/`format`/
  `constraints`, and always a `system_prompt`). If a step has no format
  contract, omit `format` — `PromptManager` treats that as "no output
  validation for this step," which is fine.
- Update `<name>/.env` to the interview's `ENVIRONMENT` and `DEFAULT_MODEL`
  if different from the scaffolded default (`local` / `claude-sonnet-5`).

### Validation depth (do exactly this, no more)

Before writing the final YAML, run plain structural checks yourself (no
schema library, no new validator script needed):

- Every step name listed in a process's `steps` has exactly one matching
  sub-block, and every sub-block key matches an entry in `steps` (no
  orphaned step configs, no step missing its config).
- Step names are unique within a process.
- Every step's `prompt` value, if present, names a file that exists (or
  that you are about to create) under that project's `prompts/` directory.
- Every step's `model` is a non-empty string, and `fallback` (if present) is
  a list of non-empty strings.

Do **not** attempt to validate that a model name is a real or currently
deployed Claude model. That is intentional: the accelerator trusts
whatever string the user supplies here, and `claude-model-router-accelerator`'s
runtime fallback/error handling is what catches a bad or retired model name
at call time (by falling through the chain, or surfacing a clear error).
Do not add model-name validation to this skill or to the generated project —
this is a deliberate scope boundary from the plan, not an oversight.

## Step 4 — Offer a smoke test (never force it)

After the registry and prompts are written, ask the user (a simple
yes/no is fine) whether they'd like to smoke-test the new project now.
If yes, from `<name>/` (using its venv's Python if one was created):

```bash
pytest tests/test_sample_pipeline.py
```

or, to exercise a specific process/step directly:

```bash
python -c "from project_accelerator import execute; print(execute({'process': '<name>', 'step': '<step>', 'input': 'sample text', 'backend': 'agent_sdk'}))"
```

The shipped test already skips itself gracefully
(`pytest.mark.skipif`) when no Claude credential is resolvable via
`auth_accelerator.resolve_auth`. If the smoke test is skipped or fails for
lack of credentials, tell the user plainly (don't treat it as a scaffold
failure) and point them at setting `ANTHROPIC_API_KEY` in `<name>/.env` or
their shell environment, or otherwise configuring `claude-auth-accelerator`
(ambient OAuth/OS session), then re-running the same command. If the user
says no, or has no credential handy, skip this step entirely — the project
is already usable without it.

## Step 5 — Report back

Summarize for the user:

1. **Folder layout** — the project root and its key files/dirs
   (`process_registry.yaml`, `prompts/`, `pipeline/run_pipeline.py`,
   `tests/test_sample_pipeline.py`, `.env`, `.claude/`, and the venv path if
   created).
2. **Which `(process, step)` pairs are explicitly configured** in
   `process_registry.yaml` (list each process's steps with their model),
   versus **which are running on the built-in default** (any process/step
   the user's own code might call that isn't in the registry at all — call
   out explicitly that those get one `DEFAULT_MODEL` call with a generic
   system prompt and no output validation).
3. **The `execute(payload)` call shape** for the user's own code, concretely
   filled in with one of their actual configured processes/steps, e.g.:
   ```python
   from project_accelerator import execute

   result = execute({
       "process": "<name>",
       "step": "<step>",       # optional — omit to run every step in order
       "input": "some input text",
       "backend": "agent_sdk", # or "messages_api"
   })
   ```
4. Whether the smoke test was run, skipped, or declined, and its outcome.

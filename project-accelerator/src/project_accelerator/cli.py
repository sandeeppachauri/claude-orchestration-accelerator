"""
cli.py

`cpa new --project-name <name> [--venv|--no-venv]` -- plain argparse +
venv/subprocess, no templating engine. Generates a starter project and
fully automates installing all four accelerators into the chosen
environment.
"""

from __future__ import annotations

import argparse
import importlib.resources
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# Local-checkout convenience only: when this repo (and its sibling
# Accelerators repo) are cloned on disk, _install_accelerators() prefers
# editable installs from these paths over fetching from git. Neither path
# needs to exist -- `cpa` works standalone via pip/pipx from git alone,
# since the scaffold template itself ships as package data (scaffold_data/)
# rather than being read from REPO_ROOT.
REPO_ROOT = Path(__file__).resolve().parents[3]
ACCELERATORS_ROOT = REPO_ROOT.parent / "Accelerators"

ORCHESTRATION_GIT_URL = "https://github.com/sandeeppachauri/claude-orchestration-accelerator.git"
ACCELERATORS_GIT_URL = "https://github.com/sandeeppachauri/Accelerators.git"

SKELETON_ENTRIES = [
    # CLAUDE.md ships inside .claude/ (below) -- both ./CLAUDE.md and
    # ./.claude/CLAUDE.md are supported by Claude Code; this repo uses the
    # latter. CLAUDE.local.md has no .claude/ variant, so it stays its own
    # top-level entry.
    "CLAUDE.local.md",
    ".claude",
    ".mcp.json",
    "docs",
    "scripts",
]


def _scaffold_data_dir() -> Path:
    return Path(str(importlib.resources.files("project_accelerator") / "scaffold_data"))


def _copy_reference_skeleton(dest: Path, include_samples: bool = True) -> None:
    """One-time snapshot copy of the packaged reference Claude Code project
    skeleton -- not a live link. A scaffolded project owns its own copy and
    can diverge afterward."""
    data_dir = _scaffold_data_dir()
    for entry in SKELETON_ENTRIES:
        src = data_dir / entry
        if not src.exists():
            continue
        target = dest / entry
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)

    if not include_samples:
        dummy_skill_dir = dest / ".claude" / "skills" / "dummyDemoSkill"
        if dummy_skill_dir.exists():
            shutil.rmtree(dummy_skill_dir)


def _copy_sample_config(dest: Path, include_samples: bool = True) -> None:
    data_dir = _scaffold_data_dir()
    config_dest = dest / "config"
    config_dest.mkdir(exist_ok=True)
    if include_samples:
        shutil.copy2(data_dir / "config" / "process_registry.yaml", config_dest / "process_registry.yaml")
        shutil.copy2(data_dir / "config" / "batch_registry.yaml", config_dest / "batch_registry.yaml")
    else:
        (config_dest / "process_registry.yaml").write_text(
            "# No processes configured yet -- scaffolded with --sample-needed no.\n"
            "# Add your own process here; see .claude/rules/process-registry.md for the schema.\n"
            "{}\n"
        )
        (config_dest / "batch_registry.yaml").write_text(
            "# No batch jobs configured yet -- scaffolded with --sample-needed no.\n"
            "# Add an entry here once config/process_registry.yaml has a process to batch;\n"
            "# see .claude/rules/batch-registry.md for the schema.\n"
            "{}\n"
        )
    shutil.copy2(data_dir / "config" / "capability_registry.yaml", config_dest / "capability_registry.yaml")
    shutil.copy2(data_dir / "config" / "guardrails.yaml", config_dest / "guardrails.yaml")
    prompts_dest = dest / "prompts"
    prompts_dest.mkdir(exist_ok=True)
    if include_samples:
        for prompt_file in (data_dir / "prompts").glob("*.yaml"):
            shutil.copy2(prompt_file, prompts_dest / prompt_file.name)


def _write_env_file(dest: Path) -> None:
    (dest / ".env").write_text(
        "# ENVIRONMENT gates which auth_accelerator provider resolves:\n"
        "#   local / dev  -> ambient `claude login` OAuth session, agent_sdk only\n"
        "#   anything else (staging, prod, ...) -> requires ANTHROPIC_API_KEY below,\n"
        "#                                          works with either backend\n"
        "ENVIRONMENT=local\n"
        "# ANTHROPIC_API_KEY=sk-ant-api...   # required once ENVIRONMENT != local/dev\n"
        "DEFAULT_MODEL=claude-sonnet-5\n"
        "# DEFAULT_TRIMMING_STRATEGY=none   # turn_count | token_budget | none -- fallback for a\n"
        "#   context_mode: session process that omits its own `trimming` block\n"
    )


def _write_logger_config(dest: Path) -> None:
    from orchestration_accelerator.logging import DEFAULT_LOGGER_CONFIG_PATH

    shutil.copy2(DEFAULT_LOGGER_CONFIG_PATH, dest / "logger_config.json")


def _write_readme(dest: Path, project_name: str, include_samples: bool = True) -> None:
    samples_line = (
        """Three sample processes ship out of the box: `ticketClassification`
(`classify` -> `extract` -> `respond`), `onboarding` (`welcome` ->
`verify` -> `finalize`), and `templatingDemo` (`triage` -> `escalate`,
demonstrating runtime `{{key}}` placeholders -- see "Runtime input" below).
Edit `config/process_registry.yaml` and `prompts/*.yaml` to add your own, or
remove the samples once you've replaced them."""
        if include_samples
        else """Scaffolded with `--sample-needed no`: `config/process_registry.yaml`
and `prompts/` ship empty, and no `examples/` directory is generated.
Add your own process to `config/process_registry.yaml` and a matching
prompt under `prompts/*.yaml` -- see `.claude/rules/process-registry.md`
for the schema, and that same doc's "Runtime input & {key} placeholders"
section if you need `{key}`-templated prompts."""
    )
    runtime_input_section = (
        """
## Runtime input (`{{key}}` placeholders)

`prompts/*.yaml`'s `system_prompt` and optional `user_prompt` fields may
contain `{{key}}` placeholders, filled at call time from `execute()`'s
payload `"input"`:

| Prompt has placeholders? | `input` must be | Example |
| --- | --- | --- |
| No | a plain string | `"input": "some ticket text"` |
| Yes | a dict covering every `{{key}}`, no extras | `"input": {{"ticket_id": "T-1", "body": "..."}}` |

Every placeholder needs a matching dict key and every dict key needs a
matching placeholder -- either mismatch raises immediately (fail fast,
never a silently blank or ignored value). Three worked examples ship in
`prompts/`:

1. `classify.yaml` -- static only, no placeholders (plain string input).
2. `ticket_triage.yaml` -- 4 placeholders in a static `user_prompt`
   (`templatingDemo.triage`).
3. `escalation_decision.yaml` -- placeholders in *both* `system_prompt`
   and `user_prompt`, paired with a full capability-key spread in
   `config/process_registry.yaml`'s `templatingDemo.escalate` step.

See `docs/HOWTO.md` for a full walkthrough and runnable snippets.
"""
        if include_samples
        else ""
    )
    batch_examples_note = (
        " Runnable examples: `examples/file_upload_example.py`,\n"
        "`examples/batch_processing_example.py`."
        if include_samples
        else ""
    )
    tests_section = (
        """```bash
pytest tests/test_sample_pipeline.py
```"""
        if include_samples
        else """```bash
pytest tests/test_sample_pipeline.py
```

Scaffolded with `--sample-needed no`, so this is a placeholder test with
no assertions against a sample process -- replace it once you've added a
process to `config/process_registry.yaml`."""
    )
    structure_examples_lines = (
        """- `examples/sample_usage.py` -- sample `TicketClassifier` class wrapping
  `execute()` the way docs/SETUP.md step 11 shows it used directly.
- `config/batch_registry.yaml` -- maps a `batch_id` to a `config/process_registry.yaml`
  process for batch jobs (see "File upload and batch processing" below).
- `examples/file_upload_example.py` / `examples/batch_processing_example.py`
  -- sample classes for `upload_file()` and `execute_batch()`.
"""
        if include_samples
        else """- `config/batch_registry.yaml` -- maps a `batch_id` to a `config/process_registry.yaml`
  process for batch jobs; ships empty (`--sample-needed no`) -- add an
  entry once you have a process to batch.
"""
    )
    run_example = (
        """result = execute({
    "process": "ticketClassification",  # any process defined in config/process_registry.yaml
    "input": "some ticket text",
    "backend": "agent_sdk",             # "agent_sdk" | "messages_api"
})"""
        if include_samples
        else """result = execute({
    "process": "yourProcess",  # a process you've added to config/process_registry.yaml
    "input": "some input text",
    "backend": "agent_sdk",    # "agent_sdk" | "messages_api"
})"""
    )
    env_example_process = "ticketClassification" if include_samples else "yourProcess"
    (dest / "README.md").write_text(
        f"""# {project_name}

Scaffolded by `cpa new --project-name {project_name}` from
`claude-project-accelerator`.

## Structure

- `config/process_registry.yaml` -- single source of truth for each process's step
  order and per-step `{{prompt, model, fallback}}` configuration.
- `config/capability_registry.yaml` -- whitelist of capability keys (e.g.
  `max_turns`, `temperature`) allowed per backend; a step's capability
  keys are checked against this before the model call.
- `prompts/*.yaml` -- prompt templates referenced by the registry.
- `pipeline/run_pipeline.py` -- sample script driving `execute()`.
{structure_examples_lines}- `.env` -- `ENVIRONMENT` (default environment) and `DEFAULT_MODEL`
  (fallback model when a `(process, step)` isn't in the registry).
- `logger_config.json` -- default logging wrapper config.
- `tests/test_sample_pipeline.py` -- smoke test for the sample process.

{samples_line}

## Run

```python
from project_accelerator import execute

{run_example}
```

The payload's `"process"` (and optional `"step"`) select what to run;
`config/process_registry.yaml` alone controls step order and per-step config --
the payload can never reorder, skip, or subset a process's `steps` list.

## Environment configuration

`"environment"` (payload -> `.env`'s `ENVIRONMENT` -> `"local"`) picks
which credential provider `claude-auth-accelerator` resolves:

| `environment` | Credential | Backend |
| --- | --- | --- |
| `local` / `dev` | ambient `claude login` OAuth session | `agent_sdk` only |
| anything else (`staging`, `prod`, ...) | `ANTHROPIC_API_KEY` (console key) | `agent_sdk` or `messages_api` |

```python
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "local", "backend": "agent_sdk"}})      # OAuth session
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "staging", "backend": "messages_api"}})  # console key
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "prod", "backend": "agent_sdk"}})        # console key
```

Set `ANTHROPIC_API_KEY` in each environment's own `.env`/secret store --
never share a prod key into a local `.env`. Omitting `"environment"`
falls back to this project's `.env`, so a deployed service typically sets
`ENVIRONMENT` once there and never passes `"environment"` per call.

## Capabilities (per-step model config)

A step block isn't limited to `prompt`/`model`/`fallback` -- any extra
key passes straight through to the model call, no code change needed:

| Capability | Backend | Example |
| --- | --- | --- |
| `max_turns` | `agent_sdk` | `max_turns: 1` |
| `thinking` (extended thinking) | `agent_sdk` | `thinking: {{type: enabled, budget_tokens: 4096}}` |
| `permission_mode` | `agent_sdk` | `permission_mode: acceptEdits` |
| `temperature` | `messages_api` | `temperature: 0.2` |
| `top_p` | `messages_api` | `top_p: 0.9` |
| `max_tokens` | `messages_api` | `max_tokens: 2048` |
| `cache_control` | `messages_api` | `cache_control: {{type: ephemeral, ttl: 5m}}` |

```yaml
classify:
  prompt: classify.yaml
  model: claude-haiku-4-5-20251001
  fallback: [claude-sonnet-5]
  max_turns: 1   # capability passthrough -- reaches build_options() untouched
```

See `.claude/rules/process-registry.md` for the full schema.

{runtime_input_section}
## File upload and batch processing

```python
from project_accelerator import upload_file, execute_batch

file_id = upload_file("invoice.pdf", backend="messages_api")

result = execute_batch({{
    "batch_id": "yourBatchJob",  # see config/batch_registry.yaml
    "inputs": ["item text 1", "item text 2"],
}})
```

`upload_file()` uploads via Anthropic's Files API (`messages_api`) or
returns a local path reference (`agent_sdk`). `execute_batch()` submits
every item in `"inputs"` as one real Anthropic Message Batches API job
(not a loop over `execute()`), polls until done, then validates each
result the same way `execute()` does. `config/batch_registry.yaml` maps a
`batch_id` to a `config/process_registry.yaml` process `id` (+ optional `step`)
-- see `.claude/rules/batch-registry.md` for the schema.{batch_examples_note}

### `config/process_registry.yaml` vs `config/batch_registry.yaml` -- what goes where

| | `config/process_registry.yaml` | `config/batch_registry.yaml` |
| --- | --- | --- |
| Owns | model invocation layer: step order, `prompt`, `model`, `fallback`, capability passthrough | batch-run mechanics only: `batch_id`, `process`/`step` reference, `environment`, `poll_interval_seconds`, `poll_timeout_seconds` |
| Model/prompt info | yes -- the only place it lives | no -- always resolved via the `process`/`step` it points at |

A batch entry never duplicates model config -- `execute_batch()` always
reads `prompt`/`model`/`fallback`/capabilities from the
`config/process_registry.yaml` step the batch's `process` (+ optional `step`)
reference resolves to.

## Tests

{tests_section}

See `docs/HOWTO.md` for a file-by-file breakdown and getting-started steps.
"""
    )


def _write_howto(dest: Path, project_name: str, include_samples: bool = True) -> None:
    docs_dest = dest / "docs"
    docs_dest.mkdir(exist_ok=True)

    templating_section = (
        """
## Runtime input: `{{key}}` placeholders end to end

A prompt's `system_prompt` and optional `user_prompt` fields can embed
`{{key}}` placeholders that get filled from `execute()`'s payload
`"input"` at call time -- static prose and dynamic values mixed freely in
the same string. This is enforced by `PromptManager.render()`, and the
match is mandatory in both directions:

- If the prompt has **no placeholders**, `input` must be a plain string.
  It's sent verbatim as the user turn; `system_prompt` is used as-is.
- If the prompt **has** `{{key}}` placeholders, `input` must be a dict.
  `user_prompt` becomes required (it's what the placeholders render
  into as the user turn). Every placeholder must have a matching dict
  key, and every dict key must be used by some placeholder -- either
  direction mismatching raises `PromptValidationError` immediately, so a
  config/call-site drift is caught at the call, not discovered later as
  a `{{literal_placeholder}}` leaking into a model call.

Three shipped examples, simplest to most complex:

1. **Static only -- `prompts/classify.yaml`** (`ticketClassification.classify`).
   No placeholders anywhere.
   ```python
   execute({{
       "process": "ticketClassification", "step": "classify",
       "input": "I was double charged", "backend": "agent_sdk",
   }})
   ```

2. **Multiple placeholders, static prompt around them -- `prompts/ticket_triage.yaml`**
   (`templatingDemo.triage`). `system_prompt` has one placeholder
   (`{{customer_tier}}`); `user_prompt` has all four.
   ```python
   execute({{
       "process": "templatingDemo", "step": "triage",
       "input": {{
           "ticket_id": "T-1",
           "customer_name": "Ada",
           "customer_tier": "gold",
           "body": "My invoice is wrong",
       }},
       "backend": "agent_sdk",
   }})
   ```

3. **Complex -- `prompts/escalation_decision.yaml`** (`templatingDemo.escalate`).
   Placeholders in *both* `system_prompt` (changes persona per
   `{{customer_tier}}`) and `user_prompt` (a 6-field case dossier), paired
   with a capability-key spread on the step in `config/process_registry.yaml`:
   `max_turns`, `permission_mode`, `thinking` -- all `agent_sdk` keys,
   since this step is called with `backend="agent_sdk"` below. A
   backend's capability keys are validated against
   `config/capability_registry.yaml`'s whitelist for that backend before the
   call happens; `messages_api`-only keys (`temperature`, `top_p`,
   `max_tokens`) would fail that check here, since the two backends'
   allowed sets are disjoint, not a shared superset.
   ```python
   execute({{
       "process": "templatingDemo", "step": "escalate",
       "input": {{
           "ticket_id": "T-9",
           "customer_name": "Grace",
           "customer_tier": "free",
           "account_history": "2 prior tickets",
           "sla_minutes_remaining": "15",
           "body": "Site is down",
       }},
       "backend": "agent_sdk",
   }})
   ```
"""
        if include_samples
        else """
## Runtime input: `{key}` placeholders

Prompts under `prompts/` may declare `{key}` placeholders in
`system_prompt`/`user_prompt`, filled at call time from `execute()`'s
payload `"input"` (which must then be a dict, not a plain string). This
scaffold was created with `--sample-needed no`, so the worked
`templatingDemo` example demonstrating this is not included here -- see
`.claude/rules/process-registry.md`'s "Runtime input & {key} placeholders"
section for the full pattern.
"""
    )

    advanced_features_section = (
        """
## Advanced step/process features

Three optional process/step features beyond static `{{key}}` templating,
each with a shipped worked config example (steps + prompt) and a
runnable driver script under `examples/`:

1. **`context_mode: session`** -- a real, accumulating `agent_sdk`
   conversation across steps instead of `{{<stepName>_output}}`
   templating (see `supportSession` in `config/process_registry.yaml`,
   `prompts/support_intake.yaml` / `prompts/support_diagnose.yaml`, and
   `examples/run_support_session.py`). Full mechanics, `trimming`, and
   `session_store` in `.claude/rules/context-mode.md`.

2. **`assistant_prompt`** -- a fixed few-shot assistant turn seeded
   before the user turn, `messages_api`-only (see `fewshotLabeling` in
   `config/process_registry.yaml`, `prompts/fewshot_seed.yaml`, and
   `examples/run_assistant_seed.py`). Schema in
   `.claude/rules/process-registry.md`.

3. **`stream: true`** -- emits chunks to `execute()`'s payload
   `on_chunk` callback as they arrive, on both backends (see
   `streamingDemo` in `config/process_registry.yaml`,
   `prompts/streaming_narrate.yaml`, and `examples/run_streaming.py`).
   Full mechanics in `.claude/rules/streaming.md`.
"""
        if include_samples
        else """
## Advanced step/process features

Three optional process/step features beyond static `{key}` templating --
`context_mode: session` (a real, accumulating `agent_sdk` conversation
across steps), `assistant_prompt` (a fixed few-shot assistant turn,
`messages_api`-only), and `stream: true` (chunk emission via
`execute()`'s payload `on_chunk` callback). This scaffold was created
with `--sample-needed no`, so the worked examples are not included here
-- see `.claude/rules/context-mode.md`, `.claude/rules/process-registry.md`
(`assistant_prompt` section), and `.claude/rules/streaming.md`.
"""
    )

    getting_started_steps = (
        """1. Create/activate a virtualenv and make sure the four accelerator
   packages are installed into it (`cpa new` already did this for the
   environment you scaffolded into -- re-run it with `--python` pointed
   at a different interpreter if you need another one).
2. Set a credential: `ANTHROPIC_API_KEY` env var, or run `claude login`
   for an ambient OAuth session. Not needed for `pytest` (everything is
   mocked) -- only for actually calling a model.
3. Run the smoke test: `pytest tests/test_sample_pipeline.py`.
4. Run the sample pipeline end to end:
   `python pipeline/run_pipeline.py ticketClassification "sample ticket text"`.
5. Open `config/process_registry.yaml` and `prompts/*.yaml` and start replacing
   the sample `ticketClassification`/`onboarding` processes with your own."""
        if include_samples
        else """1. Create/activate a virtualenv and make sure the four accelerator
   packages are installed into it (`cpa new` already did this for the
   environment you scaffolded into -- re-run it with `--python` pointed
   at a different interpreter if you need another one).
2. Set a credential: `ANTHROPIC_API_KEY` env var, or run `claude login`
   for an ambient OAuth session. Not needed for `pytest` (everything is
   mocked) -- only for actually calling a model.
3. Open `config/process_registry.yaml` (ships empty) and add your first
   process, then add a matching prompt file under `prompts/*.yaml` -- see
   `.claude/rules/process-registry.md` for the schema.
4. Run `pytest tests/test_sample_pipeline.py` -- it's a placeholder until
   you replace it with a real assertion against your own process.
5. Run your pipeline end to end:
   `python pipeline/run_pipeline.py <yourProcess> "some input text"`."""
    )

    examples_file_entries = (
        """- **`examples/sample_usage.py`** -- a `TicketClassifier` class showing
  `execute()` used directly from Python (as opposed to the CLI-style
  `run_pipeline.py`), including the optional `"step"` and `"environment"`
  keys. Copy this pattern when you need to call a process from your own
  application code.

- **`examples/run_support_session.py`** -- runnable `context_mode: session`
  walkthrough (`supportSession`): one open conversation across steps, plus
  cross-call `resume`. See "Advanced step/process features" above.

- **`examples/run_assistant_seed.py`** -- runnable `assistant_prompt`
  walkthrough (`fewshotLabeling`), `messages_api`-only. See "Advanced
  step/process features" above.

- **`examples/run_streaming.py`** -- runnable `stream: true` walkthrough
  (`streamingDemo`) with a real `on_chunk` callback. See "Advanced
  step/process features" above.

"""
        if include_samples
        else ""
    )
    batch_registry_note = (
        ""
        if include_samples
        else " Ships empty (`--sample-needed no`) -- add an entry once\n  `config/process_registry.yaml` has a process you want to batch."
    )
    batch_example_entries = (
        """
- **`examples/file_upload_example.py`** -- a `DocumentUploader` class
  showing `project_accelerator.upload_file()` used directly, then
  running the uploaded file's reference through `execute()`.

- **`examples/batch_processing_example.py`** -- a `BatchTicketClassifier`
  class showing `project_accelerator.execute_batch()` used directly,
  wired to the `ticketClassificationBatch_01` entry in
  `config/batch_registry.yaml`.
"""
        if include_samples
        else ""
    )
    test_file_entry = (
        """a smoke test for the sample
  process that mocks the model call, so it runs without any credential.
  Exists as a template for testing your own processes the same way."""
        if include_samples
        else """a placeholder test (scaffolded with
  `--sample-needed no`, so there's no sample process to assert against
  yet). Replace it with a real assertion once you've added a process to
  `config/process_registry.yaml`."""
    )

    env_example_process = "ticketClassification" if include_samples else "yourProcess"
    (docs_dest / "HOWTO.md").write_text(
        f"""# How to use {project_name}

What each generated file is for, and how to get from a fresh checkout to
a running pipeline.

## Getting started

{getting_started_steps}

## `execute()`'s return value

```python
result = execute({{"process": {env_example_process!r}, "input": "...", "backend": "agent_sdk"}})
```

`result` is `{{step_name: {{output, model_used, stop_reason, usage,
tool_calls, request_id, latency_ms}}, ...}}` -- one entry per step run.
`output` is the validated text for that step; the rest is metadata about
the model call that produced it (`tool_calls` is agent_sdk-only, empty
on `messages_api`; `request_id` is messages_api-only, `None` on
agent_sdk). Access a step's text as `result[step_name]["output"]`.

## File-by-file

- **`config/process_registry.yaml`** -- the single source of truth for every
  process's step order and per-step `{{prompt, model, fallback}}` config.
  It's here because nothing about which steps run, in what order, or with
  which model is allowed to be hardcoded in application code -- a payload
  can only select a process (and optionally narrow to one step), never
  reorder or subset the `steps` list. Edit this file to add a process or
  change a step's model/fallback. Any other key on a step (`max_turns`,
  `thinking`, `temperature`, `top_p`, `permission_mode`, ...) is a
  capability passthrough -- it flows untouched to the model call, so you
  can tune a step's behavior from this file alone, no code change. See
  `.claude/rules/process-registry.md` for the full schema.

- **`prompts/*.yaml`** -- the prompt templates each registry step points
  at by name. They're separate files (not inline in the registry) so
  prompt text can be reviewed/edited independently of step wiring.

{templating_section}
{advanced_features_section}
Full capability-passthrough key reference (any step key besides
`prompt`/`model`/`fallback`/`system_prompt` flows straight through to the
model call, after passing `config/capability_registry.yaml`'s per-backend
whitelist -- see `.claude/rules/process-registry.md` and
`.claude/rules/capability-registry.md`):

| Key | Backend | Meaning |
| --- | --- | --- |
| `max_turns` | `agent_sdk` | cap on agentic turns for the step |
| `permission_mode` | `agent_sdk` | e.g. `acceptEdits`, `bypassPermissions`, `default`, `plan` |
| `thinking` | `agent_sdk` | extended thinking, `{{type: enabled, budget_tokens: N}}` |
| `max_thinking_tokens` | `agent_sdk` | thinking token budget (alternate form) |
| `effort` | `agent_sdk` | reasoning effort level |
| `fallback_model` | `agent_sdk` | model to fall back to within one SDK call |
| `tools` | `agent_sdk` | native `ClaudeAgentOptions.tools` -- the built-in toolset available; `[]` forces a tool-free, text-only turn |
| `disallowed_tools` | `agent_sdk` | native `ClaudeAgentOptions.disallowed_tools` -- names to exclude from the built-in toolset |
| `mcp_servers` | `agent_sdk` | narrow which `.mcp.json`/global-settings MCP servers a step may reach |
| `allowed_tools` | `agent_sdk` | narrow to specific `mcp__server__tool` names (finer than `mcp_servers`) |
| `guardrails` | `agent_sdk` | names resolved against `config/guardrails.yaml` (redaction, rate-limiting, ...) |
| `skills` | `agent_sdk` / `messages_api` | native `ClaudeAgentOptions.skills` passthrough; translated to the beta client's `container.skills` shape on `messages_api` |
| `temperature` | `messages_api` | sampling temperature |
| `top_p` | `messages_api` | nucleus sampling cutoff |
| `max_tokens` | `messages_api` | response token cap |
| `stop_sequences` | `messages_api` | strings that stop generation |
| `cache_control` | `messages_api` | Anthropic prompt-cache breakpoint on the system prompt, e.g. `{{type: ephemeral, ttl: 5m}}`; agent_sdk caches automatically/opaquely and has no equivalent field |
| `resume` | `agent_sdk` | session id to resume -- only meaningful for `context_mode: session` processes, see `.claude/rules/context-mode.md` |
| `session_id` | `agent_sdk` | same as `resume`; session-management concern, agent_sdk-only |
| `stream` | `agent_sdk` / `messages_api` | emit chunks to `execute()`'s payload `on_chunk` callback as they arrive, see `.claude/rules/streaming.md` |

See `.claude/rules/mcp-scope.md` (`mcp_servers`/`allowed_tools`/`skills`)
and `.claude/rules/guardrails-registry.md` (`guardrails`) for full detail
on the last four rows above.

A step meant to run on both backends needs two different capability
blocks (or two different process entries) -- not one block mixing both
key sets, since a key valid for one backend fails the other's
whitelist.

- **`.env`** -- `ENVIRONMENT` (the default environment `execute()` resolves
  auth for when a payload doesn't specify one) and `DEFAULT_MODEL` (the
  model used for any `(process, step)` not explicitly listed in
  `config/process_registry.yaml`). Exists so environment/default-model changes
  don't require touching code.

### Environment configuration across `local` / `staging` / `prod`

`"environment"` (payload -> `.env`'s `ENVIRONMENT` -> `"local"`) decides
which `claude-auth-accelerator` credential provider resolves -- it's not
just a label:

| `environment` | Credential | Backend |
| --- | --- | --- |
| `local` / `dev` | ambient `claude login` OAuth session | `agent_sdk` only |
| `staging`, `prod`, or any other value | `ANTHROPIC_API_KEY` (console key) | `agent_sdk` or `messages_api` |

```python
# local -- no ANTHROPIC_API_KEY needed as long as `claude login` has run
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "local", "backend": "agent_sdk"}})

# staging -- ANTHROPIC_API_KEY set in staging's own .env/secret store
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "staging", "backend": "agent_sdk"}})
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "staging", "backend": "messages_api"}})

# prod -- ANTHROPIC_API_KEY set in prod's own .env/secret store
execute({{"process": {env_example_process!r}, "input": "...",
         "environment": "prod", "backend": "messages_api"}})
```

Each environment keeps its own `.env`/secret store -- never copy a prod
key into a local `.env`. A deployed service typically sets `ENVIRONMENT`
once via that environment's `.env` and omits `"environment"` from every
call, relying on the payload -> `.env` -> `"local"` fallback.

- **`logger_config.json`** -- turns the default JSON-line tracing wrapper's
  10 logging scopes on/off. Logging is on by default -- `execute()` loads
  this file automatically before its first log call, so editing
  `enabled_scopes` here takes effect with no code change. Trace lines
  land under `./logs/trace.log` (path/rotation also configurable here).

- **`pipeline/run_pipeline.py`** -- a runnable script that reads a process
  name and input off `sys.argv` and calls `execute()` with no `"step"` key,
  so every step in `config/process_registry.yaml`'s order runs. It's the
  fastest way to exercise a whole process from the command line:
  `python pipeline/run_pipeline.py <process> "<input text>"`.

{examples_file_entries}- **`config/batch_registry.yaml`** -- maps a `batch_id` to a
  `config/process_registry.yaml` process `id` (+ optional `step`), plus
  batch-specific `poll_interval_seconds`/`poll_timeout_seconds`. See
  `.claude/rules/batch-registry.md` for the full schema. `execute_batch()`
  reads this to know which process/step/model runs across every item in
  a batch job.{batch_registry_note}
{batch_example_entries}
- **`tests/test_sample_pipeline.py`** -- {test_file_entry}

- **`README.md`** -- short orientation: what got scaffolded and the
  minimal run/test commands. This file (`docs/HOWTO.md`) is the longer,
  file-by-file version.

- **`.claude/CLAUDE.md` / `CLAUDE.local.md` / `.claude/`** -- the reference
  Claude Code project skeleton (settings, hooks, skills, agents, rules,
  commands), copied as a one-time snapshot so this project has the same
  Claude Code conventions as `claude-orchestration-accelerator` itself.

- **`.claude/commands/`** -- slash commands for this project:
  `/test-all` (run the suite), `/run-pipeline` (drive `run_pipeline.py`),
  `/bootstrap` (add a new process).

- **`.claude/plugins/manifest.json`** -- empty plugin manifest; add
  entries here if you package project-specific skills/agents as an
  installable plugin later.

- **`.mcp.json`** -- empty MCP server registry. Add servers here (and to
  `.claude/settings.json`'s `allowedMcpServers`) as you wire in external
  tools.

- **`docs/architecture.md`** -- one-page summary of how `execute()`,
  the registry, and the two backends fit together; a shorter companion
  to this file's file-by-file detail.

- **`scripts/smoke_test.sh`** -- runs the unit test, then a real
  pipeline call if `ANTHROPIC_API_KEY` is set. Same steps as "Getting
  started" above, scripted.
"""
    )


def _write_pipeline_runner(dest: Path) -> None:
    pipeline_dir = dest / "pipeline"
    pipeline_dir.mkdir(exist_ok=True)
    (pipeline_dir / "__init__.py").write_text("")
    (pipeline_dir / "run_pipeline.py").write_text(
        '''"""
run_pipeline.py

Reads the step list and per-step config from config/process_registry.yaml --
nothing here is a hardcoded tuple or dict. Run: python pipeline/run_pipeline.py

Logging is on by default -- no setup needed. execute() logs every turn
via orchestration_accelerator's logging wrapper, configured from this
project's own logger_config.json (edit that file's "enabled_scopes" to
turn scopes on/off). Trace lines land under ./logs/trace.log.
"""

import sys

from orchestration_accelerator.registry import get_process
from project_accelerator import execute


def run(process_name: str, input_text: str, backend: str = "agent_sdk") -> dict:
    """Runs every step of `process_name` in the order config/process_registry.yaml
    defines, by simply not passing payload["step"] -- execute() reads the
    step order from the registry itself."""
    return execute({
        "process": process_name,
        "input": input_text,
        "backend": backend,
    })


def main() -> None:
    process_name = sys.argv[1] if len(sys.argv) > 1 else "ticketClassification"
    input_text = sys.argv[2] if len(sys.argv) > 2 else "Sample input text."

    process = get_process(process_name)
    print(f"Running process '{process_name}' -- steps: {process['steps']}")

    result = run(process_name, input_text)
    for step_name, step_result in result.items():
        print(f"[{step_name}] -> {step_result['output']!r}")
        print(f"    model_used={step_result['model_used']} usage={step_result['usage']}")
    print("Trace logged to ./logs/trace.log (see logger_config.json).")


if __name__ == "__main__":
    main()
'''
    )


_SAMPLE_USAGE_TEMPLATING_CLASSES = '''

class TicketTriager:
    """Thin wrapper around execute() for templatingDemo's `triage` step alone (dynamic/templated input)."""

    def __init__(self, environment: str = "local", backend: str = "agent_sdk") -> None:
        self.environment = environment
        self.backend = backend

    def triage(self, ticket_id: str, customer_name: str, customer_tier: str, body: str) -> dict:
        return execute({
            "process": "templatingDemo",
            "step": "triage",
            "input": {
                "ticket_id": ticket_id,
                "customer_name": customer_name,
                "customer_tier": customer_tier,
                "body": body,
            },
            "environment": self.environment,
            "backend": self.backend,
        })


class TicketEscalator:
    """Thin wrapper around execute() for templatingDemo's full process (triage + escalate, no step narrowing)."""

    def __init__(self, environment: str = "local", backend: str = "agent_sdk") -> None:
        self.environment = environment
        self.backend = backend

    def run(
        self,
        ticket_id: str,
        customer_name: str,
        customer_tier: str,
        body: str,
        account_history: str,
        sla_minutes_remaining: int,
    ) -> dict:
        return execute({
            "process": "templatingDemo",
            # no "step" -- runs triage then escalate, in the order
            # config/process_registry.yaml's `steps` list declares.
            "input": {
                "ticket_id": ticket_id,
                "customer_name": customer_name,
                "customer_tier": customer_tier,
                "body": body,
                "account_history": account_history,
                "sla_minutes_remaining": sla_minutes_remaining,
            },
            "environment": self.environment,
            "backend": self.backend,
        })
'''

_SAMPLE_USAGE_TEMPLATING_MAIN = '''
    print("--- Example 2: dynamic / templated input, single step ---")
    triager = TicketTriager()
    result = triager.triage(
        ticket_id="T-1",
        customer_name="Ada",
        customer_tier="gold",
        body="My invoice is wrong",
    )
    print(result)

    print("--- Example 3: dynamic / templated input, full process (triage + escalate) ---")
    escalator = TicketEscalator()
    result = escalator.run(
        ticket_id="T-1",
        customer_name="Ada",
        customer_tier="gold",
        body="My invoice is wrong",
        account_history="3 prior tickets, no refunds issued",
        sla_minutes_remaining=45,
    )
    print(result)
'''


def _write_sample_usage(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)

    doc_extra = (
        """

Example 1 (static input) -- TicketClassifier wraps the ticketClassification
process, whose classify.yaml prompt has no {{key}} placeholders, so
`input` is just a plain string.

Example 2 (dynamic / templated input, single step) -- TicketTriager
wraps templatingDemo's `triage` step alone (step is narrowed), whose
ticket_triage.yaml prompt has {{key}} placeholders. `input` here must
be a dict covering every placeholder triage.yaml declares --
PromptManager.render() fills them in at call time.

Example 3 (dynamic / templated input, full process) -- TicketEscalator
wraps templatingDemo with NO `step` narrowing, so both `triage` and
`escalate` run in order against the SAME `input` dict. `escalate`
needs two keys `triage` doesn't (account_history,
sla_minutes_remaining), so `input` here is the union of every
placeholder either step declares. Each step only consumes the subset
it needs from the shared dict -- a key destined for the other step is
present but simply unused for a given step, not an error.
"""
        if include_samples
        else "\n\nOne worked example -- TicketClassifier wraps the ticketClassification\nprocess (static input, no {key} placeholders).\n"
    )

    content = f'''"""
sample_usage.py

Worked example(s) of the library entry point, as shown in docs/SETUP.md
step 11 ("Using the library entry point directly"). Needs a real
credential (ANTHROPIC_API_KEY env var or an ambient `claude login` OAuth
session) to actually call a model. Run: python examples/sample_usage.py

Logging is on by default -- execute() logs every turn via
orchestration_accelerator's logging wrapper, configured from this
project's own logger_config.json. No setup needed; trace lines land
under ./logs/trace.log.{doc_extra}"""

from project_accelerator import execute


class TicketClassifier:
    """Thin wrapper around execute() for the ticketClassification process (static input)."""

    def __init__(self, environment: str = "local", backend: str = "agent_sdk") -> None:
        self.environment = environment
        self.backend = backend

    def classify(self, input_text: str) -> dict:
        return execute({{
            "process": "ticketClassification",
            "step": "classify",          # optional -- omit to run the full process
            "input": input_text,
            "environment": self.environment,  # optional -- falls back to .env's ENVIRONMENT
            "backend": self.backend,     # "agent_sdk" | "messages_api"
        }})
{_SAMPLE_USAGE_TEMPLATING_CLASSES if include_samples else ""}

def main() -> None:
    print("--- Example 1: static input ---")
    classifier = TicketClassifier()
    result = classifier.classify("sample ticket text")
    print(result)
{_SAMPLE_USAGE_TEMPLATING_MAIN if include_samples else ""}
    print("Trace logged to ./logs/trace.log (see logger_config.json).")


if __name__ == "__main__":
    main()
'''
    (examples_dir / "sample_usage.py").write_text(content)


def _write_file_upload_example(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "file_upload_example.py").write_text(
        '''"""
file_upload_example.py

Sample class wrapping project_accelerator.upload_file() alongside
execute(). Needs a real credential to actually call a model or upload a
file. Run: python examples/file_upload_example.py <path-to-file>
"""

import sys

from project_accelerator import execute, upload_file


class DocumentUploader:
    """Uploads a document, then runs it through the ticketClassification
    process's classify step."""

    def __init__(self, environment: str = "local", backend: str = "messages_api") -> None:
        self.environment = environment
        self.backend = backend

    def upload(self, path: str) -> str:
        return upload_file(path, environment=self.environment, backend=self.backend)

    def classify_document(self, path: str) -> dict:
        file_id = self.upload(path)
        return execute({
            "process": "ticketClassification",
            "step": "classify",
            "input": f"Uploaded file reference: {file_id}",
            "environment": self.environment,
            "backend": self.backend,
        })


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "README.md"
    uploader = DocumentUploader()
    result = uploader.classify_document(path)
    print(result)


if __name__ == "__main__":
    main()
'''
    )


def _write_batch_processing_example(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "batch_processing_example.py").write_text(
        '''"""
batch_processing_example.py

Sample class wrapping project_accelerator.execute_batch() -- submits a
list of inputs as a single Anthropic Message Batches API job (see
config/batch_registry.yaml and .claude/rules/batch-registry.md), not a loop
over execute(). Needs a real credential to actually submit a batch.
Run: python examples/batch_processing_example.py
"""

from project_accelerator import execute_batch


class BatchTicketClassifier:
    """Classifies many tickets in one batch job, wired to the
    ticketClassificationBatch entry in config/batch_registry.yaml."""

    def __init__(self, batch_id: str = "ticketClassificationBatch_01") -> None:
        self.batch_id = batch_id

    def classify_many(self, tickets: list[str]) -> dict:
        return execute_batch({
            "batch_id": self.batch_id,
            "inputs": tickets,
        })


def main() -> None:
    classifier = BatchTicketClassifier()
    result = classifier.classify_many([
        "I was double charged for my subscription.",
        "How do I reset my password?",
    ])
    print(result)


if __name__ == "__main__":
    main()
'''
    )


def _write_support_session_example(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "run_support_session.py").write_text(
        '''"""
run_support_session.py

Runnable example of context_mode: session (see .claude/rules/context-mode.md)
-- a real, accumulating agent_sdk conversation across steps and across
execute() calls, instead of the default context_mode: threaded's
{{<stepName>_output}} text-templating.

Demonstrates:
  1. Opening the supportSession process -- intake and diagnose share one
     open ClaudeSDKClient for the whole call; diagnose sees intake's turn
     as real conversation history.
  2. Cross-call resume -- a second, later execute() call passes back the
     first call's returned session_id to continue the same conversation
     from a brand-new call.
  3. session_store: {backend: memory} -- supportSession's process config
     mirrors the transcript to an in-memory SessionStore, which is what
     makes cross-host/cross-container resume possible in production
     (this example only demonstrates the wiring; a single local process
     doesn't need it since local disk already has the transcript).

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run: python examples/run_support_session.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        first = execute(
            {
                "process": "supportSession",
                "input": "My app crashes every time I try to log in.",
                "backend": "agent_sdk",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    for step, step_result in first.items():
        print(f"[{step}] {step_result['output']}")

    session_id = first["diagnose"]["session_id"]
    print(f"\\nsession_id from call 1: {session_id}")

    print("\\n--- resuming the same conversation in a new execute() call ---")
    second = execute(
        {
            "process": "supportSession",
            "step": "diagnose",
            "input": "It only happens on WiFi, not on cellular data.",
            "backend": "agent_sdk",
            "environment": "local",
            "session_id": session_id,
        }
    )
    print(f"[diagnose] {second['diagnose']['output']}")


if __name__ == "__main__":
    main()
'''
    )


def _write_assistant_seed_example(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "run_assistant_seed.py").write_text(
        '''"""
run_assistant_seed.py

Runnable example of `assistant_prompt` (see .claude/rules/process-registry.md's
"Runtime input & {{key}}" section) -- a canned prior assistant turn seeded
before the real user turn, for few-shot priming or "continue from this
canned response" patterns.

Deliberately messages_api, not agent_sdk (unlike every other example in
this directory, which default to agent_sdk): claude_agent_sdk's query()
takes a single string prompt, not a message array, so there is no SDK
surface to seed a prior assistant turn on agent_sdk. A step with
assistant_prompt set raises UnsupportedCapabilityError before any model
call if run with backend: agent_sdk -- this is not a config choice, it
is a hard backend limitation, so this example cannot be switched to
agent_sdk without breaking every run.

Needs a credential (ANTHROPIC_API_KEY env var) resolved via
claude-auth-accelerator -- messages_api has no ambient-OAuth path.

Run: python examples/run_assistant_seed.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def main() -> None:
    try:
        result = execute(
            {
                "process": "fewshotLabeling",
                "step": "label",
                "input": {"ticket_text": "The app crashes every time I try to log in."},
                "backend": "messages_api",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY.")
        return

    print(f"[label] {result['label']['output']}")


if __name__ == "__main__":
    main()
'''
    )


def _write_streaming_example(dest: Path, include_samples: bool = True) -> None:
    if not include_samples:
        return
    examples_dir = dest / "examples"
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "run_streaming.py").write_text(
        '''"""
run_streaming.py

Runnable example of `stream: true` (see .claude/rules/streaming.md) --
chunks emitted to execute()'s payload["on_chunk"] callback in real time
as the model produces them, instead of only returning the fully-buffered
text after the whole turn completes. Demonstrates agent_sdk's streaming
path (the SDK's own include_partial_messages mechanism); the same
on_chunk callback works unchanged on messages_api (its own
messages.stream() context manager instead).

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run: python examples/run_streaming.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from project_accelerator import execute


def print_chunk(step_name: str, chunk: str) -> None:
    print(chunk, end="", flush=True)


def main() -> None:
    print("Streaming chunks as they arrive:\\n")
    try:
        result = execute(
            {
                "process": "streamingDemo",
                "step": "narrate",
                "input": {"scenario": "a customer's login keeps failing on WiFi only"},
                "backend": "agent_sdk",
                "environment": "local",
                "on_chunk": print_chunk,
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    print("\\n\\n--- full accumulated output (identical whether streamed or not) ---")
    print(result["narrate"]["output"])


if __name__ == "__main__":
    main()
'''
    )


def _write_sample_test(dest: Path, include_samples: bool = True) -> None:
    tests_dir = dest / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")

    if not include_samples:
        (tests_dir / "test_sample_pipeline.py").write_text(
            '''"""
test_sample_pipeline.py

Placeholder test -- scaffolded with `--sample-needed no`, so
config/process_registry.yaml ships empty and there is no sample process
to exercise here. Once you've added a process to
config/process_registry.yaml, replace this with a real test that calls
execute() and asserts on the result (see docs/HOWTO.md and
.claude/rules/process-registry.md).
"""

import pytest


def test_project_accelerator_importable():
    """Trivial placeholder -- proves the scaffolded environment can
    import the library entry point. Replace with a real assertion once a
    process is configured."""
    from project_accelerator import execute  # noqa: F401


def test_no_sample_process_configured():
    pytest.skip(
        "no sample process configured -- see config/process_registry.yaml "
        "and replace this test once you've added one"
    )
'''
        )
        return

    (tests_dir / "test_sample_pipeline.py").write_text(
        '''"""
test_sample_pipeline.py

Exercises execute() against the shipped ticketClassification sample and
asserts the output satisfies PromptManager.validate_output()'s format
contract. Replaces prompt-description-demo's role as the "does this
actually work end to end" check -- see Master_Accelerator_Plan.md
Section 4.3.

Requires ANTHROPIC_API_KEY (or an ambient OAuth/OS session) to make a
real model call. If no credential is available, the test is skipped
rather than failing -- this file is runnable immediately after scaffold
without requiring credentials, but does not fabricate a passing result.
"""

import pytest

from orchestration_accelerator.prompting import PromptManager
from project_accelerator import execute


def _has_credential() -> bool:
    try:
        from auth_accelerator import resolve_auth

        resolve_auth("local")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_credential(), reason="no Claude credential available")
def test_ticket_classification_classify_step():
    result = execute({
        "process": "ticketClassification",
        "step": "classify",
        "input": "I was charged twice for my subscription this month.",
        "backend": "agent_sdk",
    })

    assert "classify" in result
    category = result["classify"]["output"]

    pm = PromptManager()
    cfg = pm.get("classify", filename="classify.yaml")
    # Re-validating here proves the returned value already satisfies the
    # format contract -- execute() validates internally too.
    assert pm.validate_output("classify", cfg, category) == category
'''
    )


def _install_accelerators(
    python_exe: str, accelerators_root: Path, allow_missing_accelerators: bool
) -> list[str]:
    """Installs each accelerator package into python_exe. Prefers an editable
    install from a local checkout (accelerators_root / REPO_ROOT) when
    present -- convenient for contributors -- and otherwise falls back to
    installing straight from GitHub, so `cpa new` works standalone from a
    pip/pipx install with no repo cloned locally. Returns the list of
    packages that could not be installed either way (only possible for the
    two accelerators_root packages when allow_missing_accelerators is set)."""
    local_packages = [
        accelerators_root / "claude-auth-accelerator",
        accelerators_root / "ClaudeSDKLoggerAccelerator",
    ]
    git_specs = [
        f"git+{ACCELERATORS_GIT_URL}#subdirectory=claude-auth-accelerator",
        f"git+{ACCELERATORS_GIT_URL}#subdirectory=ClaudeSDKLoggerAccelerator",
    ]

    missing = []
    for local_path, git_spec in zip(local_packages, git_specs):
        if local_path.exists():
            subprocess.run(
                [python_exe, "-m", "pip", "install", "-e", str(local_path), "--quiet"],
                check=True,
            )
            continue
        try:
            subprocess.run(
                [python_exe, "-m", "pip", "install", git_spec, "--quiet"],
                check=True,
            )
        except subprocess.CalledProcessError:
            if not allow_missing_accelerators:
                raise
            missing.append(git_spec)

    # This repo's own packages: editable install if cloned locally,
    # otherwise install straight from GitHub. project-accelerator itself
    # must be installed too -- the scaffolded pipeline/examples import
    # `project_accelerator`, not just its dependencies.
    if REPO_ROOT.exists() and (REPO_ROOT / "pyproject.toml").exists():
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-e", f"{REPO_ROOT}[batch]", "--quiet"], check=True
        )
        subprocess.run(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                "-e",
                f"{REPO_ROOT / 'model-router'}[agent_sdk,messages_api]",
                "--quiet",
            ],
            check=True,
        )
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-e", str(REPO_ROOT / "project-accelerator"), "--quiet"],
            check=True,
        )
    else:
        subprocess.run(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                f"claude-orchestration-accelerator[batch] @ git+{ORCHESTRATION_GIT_URL}",
                "--quiet",
            ],
            check=True,
        )
        subprocess.run(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                f"claude-model-router-accelerator[agent_sdk,messages_api] @ "
                f"git+{ORCHESTRATION_GIT_URL}#subdirectory=model-router",
                "--quiet",
            ],
            check=True,
        )
        subprocess.run(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                f"git+{ORCHESTRATION_GIT_URL}#subdirectory=project-accelerator",
                "--quiet",
            ],
            check=True,
        )
    return missing


def cmd_new(args: argparse.Namespace) -> None:
    if not args.project_name:
        print("Error: --project-name is required.", file=sys.stderr)
        sys.exit(1)

    if args.python and args.venv:
        print("Error: --python cannot be combined with --venv.", file=sys.stderr)
        sys.exit(1)

    base = Path(args.path).expanduser().resolve() if args.path else Path.cwd()
    base.mkdir(parents=True, exist_ok=True)
    dest = base / args.project_name
    dest.mkdir(parents=True, exist_ok=True)

    include_samples = getattr(args, "sample_needed", "yes") == "yes"

    _copy_reference_skeleton(dest, include_samples)
    _copy_sample_config(dest, include_samples)
    _write_env_file(dest)
    _write_logger_config(dest)
    _write_readme(dest, args.project_name, include_samples)
    _write_howto(dest, args.project_name, include_samples)
    _write_pipeline_runner(dest)
    _write_sample_usage(dest, include_samples)
    _write_file_upload_example(dest, include_samples)
    _write_batch_processing_example(dest, include_samples)
    _write_support_session_example(dest, include_samples)
    _write_assistant_seed_example(dest, include_samples)
    _write_streaming_example(dest, include_samples)
    _write_sample_test(dest, include_samples)

    if args.python:
        python_exe = str(Path(args.python).expanduser().resolve())
        if not Path(python_exe).exists():
            print(f"Error: --python interpreter not found: {python_exe}", file=sys.stderr)
            sys.exit(1)
        print(f"Using existing interpreter at {python_exe}")
    elif args.venv:
        venv_dir = dest / ".venv"
        venv.create(venv_dir, with_pip=True)
        python_exe = str(
            venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / (
                "python.exe" if sys.platform == "win32" else "python"
            )
        )
        print(f"Created virtual environment at {venv_dir}")
    else:
        python_exe = sys.executable

    accelerators_root = (
        Path(args.accelerators_path).expanduser().resolve()
        if args.accelerators_path
        else ACCELERATORS_ROOT
    )
    print("Installing accelerator packages...")
    try:
        missing = _install_accelerators(python_exe, accelerators_root, args.allow_missing_accelerators)
    except subprocess.CalledProcessError as exc:
        print(f"\nError: failed to install accelerator packages: {exc}", file=sys.stderr)
        print(
            "Pass --accelerators-path to use a local checkout, or "
            "--allow-missing-accelerators to scaffold without them.",
            file=sys.stderr,
        )
        sys.exit(1)
    if missing:
        print(
            "\nWarning: the following accelerator packages could not be installed "
            "(from local checkout or GitHub):",
            file=sys.stderr,
        )
        for spec in missing:
            print(f"  - {spec}", file=sys.stderr)

    print(f"\nScaffolded project '{args.project_name}' at {dest}")
    print("Created:")
    if include_samples:
        print("  prompts/*.yaml, config/process_registry.yaml, config/capability_registry.yaml, config/batch_registry.yaml, config/guardrails.yaml, .env, logger_config.json")
        print("  pipeline/run_pipeline.py, examples/sample_usage.py, tests/test_sample_pipeline.py")
        print("  examples/file_upload_example.py, examples/batch_processing_example.py")
    else:
        print("  prompts/ (empty), config/process_registry.yaml (empty), config/capability_registry.yaml, config/batch_registry.yaml (empty), config/guardrails.yaml, .env, logger_config.json")
        print("  pipeline/run_pipeline.py, tests/test_sample_pipeline.py (placeholder, no examples/ dir)")
    print("  README.md, docs/HOWTO.md")
    print("  CLAUDE.local.md, .claude/ (reference skeleton, incl. .claude/CLAUDE.md)")
    print("  .mcp.json, docs/architecture.md, scripts/smoke_test.sh")


def main() -> None:
    parser = argparse.ArgumentParser(prog="cpa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Scaffold a new accelerator-based project")
    new_parser.add_argument("--project-name", required=True, help="Name of the new project")
    new_parser.add_argument(
        "--path",
        help="Parent directory to scaffold into (default: current directory)",
    )
    venv_group = new_parser.add_mutually_exclusive_group()
    venv_group.add_argument(
        "--venv", dest="venv", action="store_true", help="Create a fresh virtual environment"
    )
    venv_group.add_argument(
        "--no-venv",
        dest="venv",
        action="store_false",
        help="Install into the currently active environment",
    )
    new_parser.add_argument(
        "--python",
        help="Path to an existing python interpreter (e.g. an existing venv) to install into; "
        "cannot be combined with --venv",
    )
    new_parser.add_argument(
        "--accelerators-path",
        help="Path to the sibling 'Accelerators' repo containing claude-auth-accelerator and "
        "ClaudeSDKLoggerAccelerator (default: '../Accelerators' next to this repo)",
    )
    new_parser.add_argument(
        "--allow-missing-accelerators",
        action="store_true",
        help="Scaffold even if claude-auth-accelerator/ClaudeSDKLoggerAccelerator can't be found",
    )
    new_parser.add_argument(
        "--sample-needed",
        choices=["yes", "no"],
        default="yes",
        help="Include the templatingDemo example process and dummyDemoSkill in the scaffold "
        "(default: yes)",
    )
    new_parser.set_defaults(venv=True, func=cmd_new)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

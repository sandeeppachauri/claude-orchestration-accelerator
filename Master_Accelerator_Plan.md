# Master Accelerator — Plan for Review

Prepared for: Sandeep Pachauri
Source project (existing, unaffected): `Accelerators` (D:\Claude\Accelerators)
New root (this plan): `claude-orchestration-accelerator` (D:\Claude\claude-orchestration-accelerator) — a fresh folder and fresh git repo, **not** linked to the existing `Accelerators` git repo
Status: **Draft for review — no implementation yet**

## 1. Goal

Create a single master accelerator that any team can pull in when starting a new project **built on either the Claude Agent SDK or the raw Claude (Messages) API** — not Agent SDK projects only. Composing capabilities that today are either separate packages or ad hoc code:

- Authentication (already an accelerator)
- Logging / tracing (already an accelerator)
- Process/pipeline orchestration — prompt resolution + the process registry (currently a demo plus a hardcoded dict, not yet a package)
- Model routing with fallback (currently a hardcoded dict, not yet a package; depends on the orchestration accelerator's registry once built)

Note: what started as "prompt management" and "model management" as two separate future packages consolidated during planning into `claude-orchestration-accelerator` (owns prompt resolution + the process registry) plus `claude-model-router-accelerator` (owns fallback execution, depending on the registry above) — three new packages total feeding the master accelerator, not four. See Section 4 for the resolved structure.

This plan covers two phases: **Phase 1** builds the accelerator stack itself (Sections 4–6); **Phase 2** (Section 7) builds a Claude Skill that lets any team set up and configure the Phase 1 accelerator conversationally, rather than by reading docs and editing files by hand.

## 2. Current state (what exists today)

| Project | Status | Notes |
|---|---|---|
| `claude-auth-accelerator` | Installable package | Credential resolution: API key -> ambient OAuth -> OS-mounted session, via `build_options()`. Already the "how to authenticate" answer for any consumer. |
| `ClaudeSDKLoggerAccelerator` | Installable package | Opt-in JSON-line tracing via `PreToolUse`/`PostToolUse` hooks. Standalone, no coupling to auth. Has a companion tester project. |
| `prompt-description-demo` | Demo only, not a package — **confirmed to be retired, not carried forward** | `PromptManager` treats prompts as versioned YAML (`scope` / `format` / `constraints`), enforces the format contract in code, hot-reloads from disk. Proved the auth + prompt separation works end to end in `run_pipeline.py`. Its `PromptManager` code is promoted into `claude-orchestration-accelerator` (4.1), but the demo repo itself is not part of this accelerator going forward — once `claude-project-accelerator` exists, "does the accelerator work end to end" is verified by scaffolding a real project with the CLI and testing that, not by maintaining a separate demo. See 4.3 for the generated sample/test class that replaces this role. |
| Model routing | Not a package — inline dict | `MODEL_ROUTING = {"classify": ..., "extract": ..., "respond": ...}` hardcoded in `run_pipeline.py`. No fallback/retry behavior today. |
| Pipeline step list | Not a package — inline tuple | `for step in ("classify", "extract", "respond")` hardcoded in `run_pipeline.py`. |

The existing three packages already prove the key design property worth preserving: **each piece is independently installable and knows nothing about the others.** A prompt change never touches auth; auth's resolution order never touches logging. The master accelerator should extend this property, not collapse it.

## 3. Gaps to close before a master accelerator makes sense

Each gap below is stated as originally identified, followed by your direction on how it should be closed. These decisions are carried forward into Section 4.

1. **Gap:** Prompt management has no installable package — it only exists inside a demo project.
   **Direction:** Prompt management and model management are always bound together — anyone using this accelerator uses both by default, never one without the other. If a consumer hasn't supplied their own configuration for a given `(process, step)`, a default master configuration (shipped with the accelerator) is used instead. This is why 4.1 merges prompt and model config into a single `process_registry.yaml` block per step, rather than two separately optional configs.

2. **Gap:** Model management doesn't exist as a concept beyond one hardcoded dict — no external config, no fallback/retry.
   **Direction:** A common, reusable call into the Claude SDK should be triggered that takes all prompt and model configuration together — i.e. the resolved `(process, step)` config (prompt + model + fallback chain) feeds one generic execution call, rather than the caller separately wiring a prompt call and a model choice.

3. **Gap:** The step list a pipeline runs is hardcoded in Python, not config.
   **Direction:** Nothing should be hardcoded. All decisions — which process, which step, in what order — are driven by user input at call time, not assumed by the code or iterated from a fixed list anywhere in the accelerator stack. **Confirmed refinement:** rather than a separate env file or a second config file, `process_registry.yaml` itself controls the step order/sequence too, alongside the per-step prompt/model/fallback it already carries — since (per your direction) these are all connected and belong in the one file a team already edits. See the updated schema in 4.1.

4. **Gap:** There is currently no single entry point — a consuming app must know to import three (soon four) separate packages and wire them together by hand, as `run_pipeline.py` does.
   **Direction:** Each prompt execution should go through one generic method/call where the user feeds in the input. The call takes a single generic JSON/dict payload (confirmed) — e.g. `{process, step, input, environment, ...}` — rather than a fixed set of typed parameters, so new optional fields can be added later without changing the call signature.

## 4. Proposed structure — Phase 1 (the accelerator itself)

**Repo/folder note:** `D:\Claude\Accelerators` already has its own linked git remote and stays exactly as-is — `claude-auth-accelerator` and `ClaudeSDKLoggerAccelerator` continue to live there, unchanged. Everything below is new work and lives in a brand-new folder, `D:\Claude\claude-orchestration-accelerator`, which becomes its own git repo (not connected to the `Accelerators` remote) and serves as the root for all packages built as part of this plan — `claude-orchestration-accelerator` itself, `claude-model-router-accelerator`, and eventually the master `claude-project-accelerator` — arranged as nested sub-project folders under that root, the same monorepo-style layout `Accelerators` uses today, just in a new, separately-versioned repo. Consuming projects still `pip install claude-auth-accelerator` / `ClaudeSDKLoggerAccelerator` from the old repo location and the new packages from the new repo — the split is purely about git history/ownership, not a functional change to either.

**Root README:** `D:\Claude\claude-orchestration-accelerator\README.md` — a root-level README at the repo root, same role as the existing `Accelerators/README.md`: a short overview of the repo plus a linked list of its nested sub-projects (`claude-orchestration-accelerator` itself, `claude-model-router-accelerator`, and eventually `claude-project-accelerator`), each pointing to that sub-project's own README for install/usage details. Created as part of step 0/1 in Section 5, before any sub-project code is written.

**Reference Claude Code project skeleton (revised — corrected against real Claude Code conventions, verified via current documentation on 2026-08-19):** beyond the Python packages, the repo root also carries a complete, working Claude Code project structure with one sample in each category, so it doubles as the reference skeleton every scaffolded project inherits from.

The earlier draft of this section guessed at `.claude/mcp/`, `.claude/hooks/`, and `.claude/tools/` as folder names without checking them against actual Claude Code documentation. Verified research found three of those four guesses wrong, and two real, commonly-used pieces (`settings.json`/`settings.local.json`, already present and load-bearing in the existing `Accelerators` repo; `.claude/agents/` and `.claude/rules/` as genuine optional conventions) were missing from the list entirely. Corrected skeleton:

- `CLAUDE.md` — project-level instructions, sample content specific to an accelerator-based project (how to run, where config lives, etc.). Confirmed real, current convention.
- `CLAUDE.local.md` — the local/untracked counterpart (gitignored), sample content showing what belongs here vs. in the tracked `CLAUDE.md` (e.g. developer-specific paths or preferences). Confirmed real, current convention.
- `.claude/settings.json` — **added; was missing from the earlier draft entirely.** Confirmed real and already in active use in `Accelerators` (holds a `permissions.allow` list and `additionalDirectories` there today). Full schema includes `permissions`, `env`, `hooks`, `model`, `additionalDirectories`, `allowedMcpServers`/`deniedMcpServers`, and more. **This is also where MCP server registration and hook configuration actually live** — see the corrected `.claude/mcp/` and `.claude/hooks/` entries below.
- `.claude/settings.local.json` — **added; was missing.** The untracked, machine-local counterpart to `settings.json` (gitignored), same pattern already used in `Accelerators` today.
- `.claude/skills/<skill-name>/SKILL.md` — confirmed correct as originally drafted. The Phase 2 setup skill (Section 7) lives here as the working sample; this is also where a scaffolded project would add its own project-specific skills later.
- **MCP server registration — corrected.** There is no `.claude/mcp/` folder and no root `.mcp.json` as the primary mechanism (a root `.mcp.json` is supported for compatibility only, not the primary convention). MCP servers are registered inside `.claude/settings.json` via `allowedMcpServers`/`deniedMcpServers` (or `claude mcp add`). The skeleton's one sample MCP registration lives as an entry in the default `.claude/settings.json`, not a separate file/folder.
- **Hooks — corrected.** There is no auto-loaded `.claude/hooks/` folder. Hooks are configured via a `hooks` key inside `.claude/settings.json` (keyed by event name — `PreToolUse`, `PostToolUse`, `SessionStart`, etc.), each entry pointing to a command/script. A hook's actual script file can still live under `.claude/hooks/<script>.sh` as a helper file the settings.json entry references — so the skeleton keeps one sample script there, but the registration itself is in `settings.json`, not implied by the folder's existence.
- **Custom commands/tools — corrected.** There is no `.claude/tools/` folder; that name doesn't exist in Claude Code. The real options are `.claude/commands/<name>.md` (legacy) or `.claude/skills/<name>/SKILL.md` (current, preferred — supports frontmatter and bundled supporting files). The skeleton uses the skills path for its one sample rather than inventing a tools folder; a project can still add `.claude/commands/` if it wants the legacy slash-command style for something trivial.
- `.claude/agents/` — **added; genuine optional convention, missing from the earlier draft.** Custom subagent definitions. Not required in the default skeleton, but worth including one minimal sample given the accelerator stack's own multi-step process model maps naturally onto subagent delegation later.
- `.claude/rules/` — **added; genuine optional convention, missing from the earlier draft.** Modular, path-scoped instruction files that supplement `CLAUDE.md`. Optional; one sample rule file included to illustrate the pattern (e.g. a rule scoped to `process_registry.yaml` explaining the schema, so an editor opening that file gets contextual guidance).

Each sample is meant to be a working, minimal example a team can extend, not just a placeholder comment — someone opening a freshly scaffolded project should see one real instance of each convention already wired up.

**Sample file contents (added per your direction — "based on our master accelerator, put some dummy information, as master accelerator will be used so claude configuration for master accelerator will also be needed"):** every sample below is written *about the accelerator stack itself*, not generic placeholder text, since the skeleton's whole purpose is to be the reference a scaffolded project inherits from:

- `CLAUDE.md` (dummy content direction): explains the project is built on `claude-project-accelerator`; documents the `execute(payload)` entry point and its `{process, step, input, environment, backend}` shape; points to `process_registry.yaml` as the single source of truth for step order/config; notes `.env`'s `ENVIRONMENT`/`DEFAULT_MODEL` keys; tells a reader "run tests via `pytest tests/test_sample_pipeline.py`."
- `CLAUDE.local.md` (dummy content direction): sample shows what's developer-local vs. tracked — e.g. a note like "my local `ANTHROPIC_API_KEY` is set via `claude login`, not committed here" and a placeholder for a developer's own scratch notes on which `(process, step)` they're actively editing.
- `.claude/settings.json` (dummy content direction): one sample `permissions.allow` entry scoped to this project (e.g. `Bash(python -m pytest tests -q)`, mirroring the pattern already used in the existing `Accelerators` repo's own settings.json), one sample `hooks` entry wiring the default logging wrapper's `pre_tool_use_hook`/`post_tool_use_hook` (4.1), and one sample `allowedMcpServers` entry left as an illustrative placeholder (no real MCP server required by the accelerator itself).
- `.claude/settings.local.json` (dummy content direction): mirrors the existing `Accelerators` repo's pattern — a machine-local `additionalDirectories` entry and any locally-approved Bash permissions not meant to be shared/committed.
- `.claude/skills/setup-accelerator/SKILL.md` (dummy content direction): this *is* the real Phase 2 skill (Section 7) once it exists — in the skeleton shipped ahead of Phase 2, this sample is a minimal stub describing what the skill will do, superseded once Phase 2 actually ships it.
- `.claude/agents/registry-reviewer.md` (dummy content direction, sample subagent): a small subagent definition scoped to reviewing `process_registry.yaml` changes — e.g. "check that every step in `steps: [...]` has a matching `{prompt, model, fallback}` block, and that referenced prompt files exist" — illustrating how the accelerator's own multi-step model maps onto subagent delegation, per the rationale already noted for including `.claude/agents/` at all.
- `.claude/rules/process-registry.md` (dummy content direction, sample rule): path-scoped to `process_registry.yaml`, explaining the schema inline (per-process `id`/`description`/`steps`, per-step `{prompt, model, fallback}`) so an editor opening that file gets contextual guidance without leaving the IDE — this is the exact example already referenced when `.claude/rules/` was first introduced above.
- Sample hook script under `.claude/hooks/` (dummy content direction): a minimal shell script the `hooks` entry in `settings.json` points to, e.g. logging a line to stdout when a `PreToolUse` event fires — illustrative, not the real logging wrapper itself (the real wrapper is Python, wired via 4.1's `orchestration_accelerator/logging/`, not this shell script).

**Inheritance mechanism (confirmed):** `claude-project-accelerator`'s scaffold command (4.3) copies this entire corrected structure — `CLAUDE.md`, `CLAUDE.local.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/skills/`, `.claude/agents/`, `.claude/rules/`, plus the samples inside each (including the one sample hook script referenced from `settings.json`'s `hooks` key, and the one sample MCP entry inside `settings.json`) — into every new project it generates, using the same copy mechanism already planned for `prompts/*.yaml` and `process_registry.yaml`. This is a one-time copy at scaffold time, not a live reference back to the root repo — a scaffolded project owns its own copy and can diverge from the root skeleton afterward, the same way it can already diverge from the sample `process_registry.yaml` content.

### 4.0 `claude-auth-accelerator` — required change to an existing package (in the existing `Accelerators` repo) — ✅ COMPLETE

Verified live against the actual repo on 2026-08-19: `build_api_credential(environment)` is shipped, in a new `api_credential.py` module, exported from `__init__.py`, and documented in the README. See the separate pre-req plan document for full verification detail. Step 0.5 (Section 5) is done — `claude-model-router-accelerator` (4.2) can now be built against a real function rather than a planned one.

Original scoping, kept for context:

Verified against the actual code (`providers.py`, `resolver.py`, `options.py`, `__init__.py`): today, `resolve_auth()` returns a plain, SDK-independent `ResolvedCredential`, but the package's only public high-level entry point, `build_options()`, hard-imports `claude_agent_sdk` and returns a `ClaudeAgentOptions` object — unusable by a raw Messages API caller. Of the three auth providers, only `ApiKeyAuth` produces a credential a Messages API caller could actually use (`credential.env["ANTHROPIC_API_KEY"]`); `OAuthSessionAuth` and `OsSessionAuth` are explicitly documented in the code as SDK-subprocess-only and return an empty `env`, which is not usable directly.

**Confirmed fix:** add a new function to `claude-auth-accelerator`, `build_api_credential(environment)` — no `claude_agent_sdk` import, safe for any Python project including raw Messages API callers. It calls `resolve_auth()` internally, and:
- returns the resolved API key directly when `ApiKeyAuth` is what resolved;
- raises a clear error when `OAuthSessionAuth` or `OsSessionAuth` resolved instead (e.g. "an ambient OAuth/OS session was found but cannot be used with the raw Messages API — set ANTHROPIC_API_KEY instead"), rather than returning an empty/unusable credential silently.

This keeps authentication ownership exactly where it already is — one function added to the existing `claude-auth-accelerator` package, not a new package and not auth logic duplicated inside the model router. `claude-model-router-accelerator`'s pluggable backend (4.2) calls `build_options()` when running against the Agent SDK backend and `build_api_credential()` when running against the Messages API backend — the model router never resolves credentials itself.

**Where this sits in scope:** this is a small, backward-compatible addition to a package that already exists and is out-of-scope for the rest of this plan's "new work" framing — but it's a hard prerequisite for the pluggable-backend design in 4.2, so it's called out here rather than left implicit.

### 4.1 `claude-orchestration-accelerator` (new package, root of the new `D:\Claude\claude-orchestration-accelerator` repo)

Renamed from the original working name `claude-prompt-accelerator` — once the process registry (below) absorbed model routing and fallback config alongside prompt resolution, "prompt accelerator" no longer described what the package does. It's the layer that defines and resolves a process's steps: which prompt, which model, which fallback chain, per step. `claude-auth-accelerator` and `ClaudeSDKLoggerAccelerator` stay as pure infra concerns (how to authenticate, how to trace); this package is the "what runs, and how it's configured" layer above them.

One installable package (own `pyproject.toml`, `src/`, tests, README, same shape as the other accelerators), containing two internal sub-packages so the two concerns stay separable in code even though they ship together:

- `orchestration_accelerator/prompting/` — `PromptManager`, `validate_output()`, hot-reload-from-disk behavior. Promoted as-is out of the `prompt-description-demo`.
- `orchestration_accelerator/registry/` — loads `process_registry.yaml`, resolves `(process, step)` lookups, and exposes the `model`/`fallback` fields for the model router to consume (see 4.2).

Both sub-packages are importable independently (`from orchestration_accelerator.prompting import PromptManager`, `from orchestration_accelerator.registry import get_process`), but ship as one package with one version — so a consuming project does one `pip install claude-orchestration-accelerator` rather than tracking two release cadences for two things that are always used together in practice.

**New addition — centralized process manifest (`process_registry.yaml`):**

Per your latest direction, this single file is no longer prompt-only — each step's block carries its prompt file, its model, and its model fallback chain together, all in one place, and **the file also now controls the step execution order for the process (confirmed, new)** via an explicit `steps` list, rather than order being implicit from dict-key order or hardcoded anywhere in Python. A single file, keyed by process name; each process block carries `id`, `description`, and `steps` (the ordered list of step names to run) as metadata, plus one entry per step name giving that step's `{prompt, model, fallback}`. A step's `prompt` can point to any prompt file — not just one named after itself — which lets teams reuse or swap prompt variants without renaming files or touching code. `fallback` is an ordered list — on a rate-limit/overload error from `model`, the model router accelerator retries each entry in order until one succeeds.

```yaml
ticketClassification:
  id: ticketClassification_01
  description: ticketClassification description
  steps: [classify, extract, respond]
  classify:
    prompt: classify.yaml
    model: claude-haiku-4-5-20251001
    fallback: [claude-sonnet-5, claude-opus-4-8]
  extract:
    prompt: extract_v2.yaml
    model: claude-sonnet-5
    fallback: [claude-haiku-4-5-20251001]
  respond:
    prompt: classify_soa.yaml
    model: claude-opus-4-8
    fallback: [claude-sonnet-5]

onboarding:
  id: onboarding_01
  description: onboarding description
  steps: [welcome, verify, finalize]
  welcome:
    prompt: welcome.yaml
    model: claude-haiku-4-5-20251001
    fallback: [claude-sonnet-5]
  verify:
    prompt: verify_kyc.yaml
    model: claude-sonnet-5
    fallback: [claude-haiku-4-5-20251001]
  finalize:
    prompt: finalize.yaml
    model: claude-opus-4-8
    fallback: [claude-sonnet-5]
```

- Confirmed: `id`, `description`, and now `steps` (the ordered step-name list) are per-process metadata; every other key matching a name in `steps` is that step's `{prompt, model, fallback}`.
- Confirmed: one global `process_registry.yaml`, not one file per process — multiple processes live side by side in the same file, distinguished by their top-level key.
- Confirmed: model routing is merged into this same file rather than kept in a separate `model_routing.yaml` — one file to edit per step, prompt and model configured together.
- Confirmed: **step order/selection is also controlled by this same file, and only by this file (revised — no payload override, see 4.3):** no separate env file, no hardcoded tuple anywhere in the pipeline template, and no second source of step-flow truth. A team changes `steps: [...]` to reorder, add, or drop steps for a process without touching code — that is the *only* way step order/selection changes. A caller's execution payload can pick which process to run and, optionally, a single step to target within it (see 4.3), but cannot reorder, skip, or subset a process's step list — that would create two competing sources of flow, which this design explicitly avoids.
- **Explicit design property (confirmed, stated for the record):** a process's `steps` list may contain any number of steps, with any names — one process can have a single step, another five, another twenty. Nothing in the registry loader, the pipeline runner, or the model router's per-step lookup assumes a fixed count or fixed step names anywhere; each reads `steps` as a plain list and iterates whatever it finds. The sample `ticketClassification` (3 steps) and `onboarding` (3 differently-named steps) blocks above are illustrative sample content, not a schema constraint.
- Confirmed: fallback is an ordered chain (try `model`, then each entry in `fallback` in order), not a single fallback model.
- Confirmed: the accelerator ships this exact file (with at least the two sample processes above) as a working example/test fixture, **and this sample content ships as the default `process_registry.yaml` in every installation/scaffolded project (confirmed)** — not just an internal test fixture. A freshly scaffolded project has working sample processes out of the box, without needing to write config before anything runs.
- Lookup shape: `get_process("ticketClassification")` (in `registry/`) returns `{id, description, steps: ["classify", "extract", "respond"], step_config: {classify: {prompt, model, fallback}, ...}}`. `prompting.PromptManager` uses the `prompt` field from each step's config; `claude-model-router-accelerator` (4.2) uses the `model`/`fallback` fields; the pipeline runner (4.3) uses the top-level `steps` list to decide execution order.
- **Resolved design question:** merging prompt + model config into one file meant a standalone model router would otherwise have needed to re-implement `process_registry.yaml` parsing independently, risking drift. Folding the registry loader into `claude-orchestration-accelerator` (as the `registry/` sub-package) resolves this: `claude-model-router-accelerator` now depends on `claude-orchestration-accelerator` for registry lookups instead of parsing the file itself. This is a one-directional dependency (router depends on orchestration, not the reverse), so the router still stays out of prompt/auth/logging concerns — it just no longer owns its own copy of manifest-parsing logic.
- Resolved: the *shipped example* `process_registry.yaml` lives in **both** places, by design — it's `claude-orchestration-accelerator`'s test fixture *and* the default file every scaffolded project starts with (see the confirmed bullet above). No either/or; the same file serves both roles.

**Default configuration fallback (revised — confirmed simpler shape):** the earlier draft described this as a rich fallback (a full default *process* with its own model/prompt/fallback structure), but since the source of truth for it is the project's `.env` file — flat key=value, not structured YAML — the actual default is narrower and simpler: one default model, named by a single `.env` key (see "Environment source" below — e.g. `DEFAULT_MODEL=claude-sonnet-5`), paired with one generic, non-process-specific system prompt shipped in code inside the `registry/` sub-package. When a consumer's `process_registry.yaml` doesn't define a given `(process, step)`, `registry.get_process()`/the lookup used by the generic execution call (see 4.3) falls back to this single default model + generic prompt rather than raising an error — so the accelerator works out of the box even before a consuming team writes any configuration of their own. This default is intentionally generic (one model, one prompt, no fallback chain, no per-process tailoring) — it's a safety net for "this step isn't configured yet," not a substitute for actually defining a process properly in `process_registry.yaml`.

**Default logging wrapper (confirmed, new):** verified against `ClaudeSDKLoggerAccelerator`'s actual README/behavior: nothing is auto-instrumented today — a consumer must call `logger.configure({...})` themselves and manually wire `logger.pre_tool_use_hook`/`logger.post_tool_use_hook` into their own `ClaudeAgentOptions.hooks`, and `enabled_scopes` must be explicitly omitted (or list all 8) to get every scope — `TOOL_CALL, ASSISTANT_TEXT, USER_INPUT, FULL_TURN, ERROR, INFO, WARNING, DEBUG`. Because every orchestration-accelerator consumer needs logging by default (not opt-in per project), `claude-orchestration-accelerator` adds a small wrapper class (a new third sub-package, e.g. `orchestration_accelerator/logging/`) that:
- Ships a default `logger_config.json` with all 8 scopes enabled ("dummy"/starter config — a working default, not a placeholder), rotation defaults matching `ClaudeSDKLoggerAccelerator`'s own size-based default.
- Calls `sdk_logger_accelerator.configure()` with that default config automatically, and internally wires `pre_tool_use_hook`/`post_tool_use_hook` into whatever `ClaudeAgentOptions` the accelerator stack builds — so a consumer gets full tracing without ever importing `sdk_logger_accelerator` directly or writing hook-wiring code themselves.
- Still depends on `ClaudeSDKLoggerAccelerator` as a package (no logic duplicated) — this wrapper only removes the manual wiring step, it doesn't reimplement tracing.

Open question not yet settled here: does this wrapper live in `claude-orchestration-accelerator` (as drafted above) or in `claude-project-accelerator`, since the master accelerator is the thing that ultimately assembles auth + logging + prompt + model for the final consumer. Flagged in Section 6 for your confirmation.

**Environment source (confirmed, new):** every sketch so far (`build_options(environment=...)`, `build_api_credential(environment)`, the execution payload's `"environment"` field) had `environment` as just a Python parameter with a hardcoded `"local"` default — no stated source of truth for where the value actually comes from in a real project. Confirmed fix:

- A common `.env` file (e.g. `ENVIRONMENT=local`) is the source of truth for a project's default environment. `claude-project-accelerator`'s scaffold command (4.3) generates a default `.env` (with `ENVIRONMENT=local`) as part of every new project, alongside `process_registry.yaml`, `logger_config.json`, etc.
- The accelerator stack reads this file at startup (via `python-dotenv` or equivalent) to determine the default `environment` used everywhere it's needed — `build_options()`/`build_api_credential()` calls, default backend selection, etc. — rather than each call site hardcoding or being passed `"local"` directly.
- **Override behavior (confirmed):** the `.env` value is the project-wide default, but a caller can still override it per call by setting `"environment"` in the `execute(payload)` call (4.3) — useful for testing against a different environment without editing the file. Precedence is: payload value (if present) → `.env` value → hardcoded fallback (`"local"`) only if neither is set.
- This applies uniformly to every place `environment` appears in this plan — `claude-auth-accelerator`'s two functions, the model router's backend resolution, and the generic execution payload all read from the same resolved value, not independent defaults.
- **`.env` file location (confirmed):** not a global, machine-wide file and not baked into any installed package — it's per-project, at the root of whatever project the accelerator was scaffolded into (i.e. wherever the accelerator-based project is actually running), read relative to that project's working directory at runtime. This is already how the scaffold command (4.3) generates it; this note makes the placement explicit rather than implicit.
- **`.env` also carries the default-model fallback (confirmed, new):** alongside `ENVIRONMENT`, the same `.env` file carries `DEFAULT_MODEL` (e.g. `DEFAULT_MODEL=claude-sonnet-5`) — the single model used by the built-in default configuration fallback described above, when a `(process, step)` isn't defined in `process_registry.yaml`. One project-local file now sources both the default `environment` and the default fallback model.

### 4.2 `claude-model-router-accelerator` (new package, nested inside the new `claude-orchestration-accelerator` repo alongside the orchestration package)

- Depends on `claude-orchestration-accelerator` for `(process, step)` registry lookups (via `registry/`) — reads that block's `model` and `fallback` fields. No separate `model_routing.yaml`, and no independent YAML parsing of `process_registry.yaml`.
- Executes the ordered fallback chain: calls `model` first; on a rate-limit/overload error, retries each entry in `fallback` in order (with basic backoff) until one succeeds or the chain is exhausted.
- **Pluggable execution backend (confirmed — new requirement, backend selection confirmed):** the accelerator stack must serve both Claude Agent SDK projects and raw Claude (Messages) API projects, not Agent SDK only. `claude-model-router-accelerator`'s execution call takes a `backend` parameter — a fixed enum defined by the accelerator (`"agent_sdk"` | `"messages_api"`), which the caller sets in the execution payload (4.3); the accelerator's job is purely to route to the matching underlying client call based on whichever value the caller sends, never to auto-detect or infer it. Same registry lookup, same prompt resolution, same fallback-chain logic either way — only the underlying client call differs (an Agent SDK `query()`/session call vs. a direct Messages API `client.messages.create()` call). This is one execution layer with two backends, not two separate accelerators.
- Own test suite exercising the fallback chain with simulated rate-limit/overload errors at each position in the chain, run against both backends.

### 4.3 `claude-project-accelerator` (new — the "master accelerator")

Per your latest direction, this also nests inside the new `D:\Claude\claude-orchestration-accelerator` repo as a third sub-project, alongside 4.1 and 4.2, rather than being yet another separate repo. (This supersedes the earlier plan draft, which had proposed a fully separate repo for the master accelerator — everything discussed in this session now consolidates under the one new root.) It depends on `claude-auth-accelerator` and `ClaudeSDKLoggerAccelerator` (pip installs from the existing, untouched `Accelerators` repo) plus `claude-orchestration-accelerator` and `claude-model-router-accelerator` (its own repo siblings).

- **Library entry point (confirmed shape):** one generic call taking a single JSON/dict payload — e.g. `execute(payload)` where `payload = {"process": ..., "step": ..., "input": ..., "environment": ..., "backend": "agent_sdk" | "messages_api"}` — rather than a fixed set of typed keyword arguments. `environment` is optional in the payload — if omitted, it resolves from the project's `.env` file (see 4.1's "Environment source"; payload value overrides `.env` when both are present). `backend` selects which of 4.2's two execution paths runs. Internally it: resolves auth via `claude-auth-accelerator` (`build_options()` for `agent_sdk`, `build_api_credential()` for `messages_api` — see 4.0), resolves the `(process, step)` block from `process_registry.yaml` (falling back to the accelerator's built-in default entry if the consumer hasn't defined one — see 4.1), calls the model with fallback via the model router, validates output against the prompt's format contract, and logs the turn — so a consuming app makes one call instead of hand-wiring four imports (as `run_pipeline.py` currently does). Nothing about which process/step/model/backend runs is hardcoded anywhere in this path — it's entirely driven by the payload the caller supplies.
- **Payload scope and step-order precedence — resolved (confirmed):** `process_registry.yaml` is the single source of truth for a process's step order and step selection — there is no second, competing source of flow. Concretely:
  - The payload's `"process"` field picks which process to run; the payload's `"step"` field, when supplied, picks a single starting step (or a single step to run in isolation — e.g. for testing/debugging one step of a pipeline without running the whole thing).
  - The payload **cannot** reorder a process's steps, skip steps, or run an arbitrary subset in a custom sequence. If a team wants different step behavior, they edit `steps: [...]` in `process_registry.yaml` — that is the only place step flow is controlled, by design, so there is never a case where the YAML says one order and a caller's payload silently produces another.
  - When `"step"` is omitted from the payload, the full `steps` list for that process runs start to finish, in the order `process_registry.yaml` defines.
- **Payload schema:** the field-level shape above (`process`, `step` optional, `input`, `environment` optional, `backend`) is confirmed; whether a formal JSON Schema enforces this at runtime (vs. plain dict-key checks) remains an open item (see Section 6).
- **Scaffold command implementation (decided):** plain Python — `argparse` for CLI parsing, a `console_scripts` entry in `pyproject.toml`, `venv`/`subprocess` for optional environment creation and `pip install`. No `copier`/`cookiecutter` dependency — the copying involved (a folder tree of samples) doesn't need a templating engine, and staying plain-Python keeps this consistent with the rest of the stack. After `pip install claude-project-accelerator`, the user has a real command on PATH (e.g. `cpa new` — exact command name still TBD, everything after `new` is confirmed below). Running it:
  - **Requires the project name as a mandatory CLI parameter (confirmed, flag name confirmed):** `--project-name` (your exact wording), e.g. `cpa new --project-name my-app`; if omitted, the CLI refuses to proceed and errors clearly rather than defaulting to a placeholder name or falling back to an interactive prompt only.
  - **Venv choice (confirmed):** asks the user at run time — via `--venv`/`--no-venv` flags (your confirmed wording) — whether to create a fresh virtual environment for the project or install into the currently active environment.
  - Generates the starter project folder: `prompts/*.yaml`, `process_registry.yaml` (pre-populated with the sample processes — now shipped as the default, see 4.1 — carrying prompt/model/fallback per step), `.env` (default `ENVIRONMENT=local` and `DEFAULT_MODEL=claude-sonnet-5` — see 4.1's "Environment source"), `logger_config.json`, a `pipeline/run_pipeline.py` template that reads the step list and per-step config from `process_registry.yaml` instead of a hardcoded tuple and dict, a README, and the full corrected reference Claude Code project skeleton from 4.1 (`CLAUDE.md`, `CLAUDE.local.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/skills/`, `.claude/agents/`, `.claude/rules/`, each with its working sample) copied in as a one-time snapshot.
  - **Fully automates dependency installation (confirmed):** `pip install`s `claude-auth-accelerator`, `ClaudeSDKLoggerAccelerator`, `claude-orchestration-accelerator`, and `claude-model-router-accelerator` into whichever environment was chosen (fresh venv or active), so the user has a project that's actually runnable at the end of one command, not just correctly configured pending a manual install step.
  - Reports what was created and where, same as the Phase 2 skill's reporting step (Section 7) — in fact, the Phase 2 skill's guided setup is really a conversational wrapper around this same CLI, not a separate implementation of scaffolding logic.
  - **Generates a sample test class in the new project (decided, replaces `prompt-description-demo`'s role):** since `prompt-description-demo` is retired (see Section 2), the way the whole accelerator stack gets exercised end-to-end going forward is by scaffolding a real project and testing it, not by maintaining a separate demo repo. The scaffold command includes `tests/test_sample_pipeline.py`, which calls `execute({"process": "ticketClassification", "step": "classify", "input": <sample text>, ...})` against the shipped default `ticketClassification` sample process, asserting the call completes without raising and that its output satisfies `PromptManager.validate_output()`'s format contract — so a freshly scaffolded project is verifiable immediately, and this same generated test doubles as Phase 1's own "does this actually work" integration check during development.
  - **No Messages-API-specific skeleton variant (decided):** `CLAUDE.md`, `.claude/settings.json`, and the rest of the reference skeleton describe the *project* and its conventions — they don't change based on which backend a given call happens to use, since `backend` is a per-call/per-step runtime choice (4.2), not a project-wide fork. One skeleton serves both backends unchanged.
- **Integration tests:** an end-to-end suite exercising all four accelerators together (analogous to `ClaudeSDKLoggerAcceleratorTester`), so a breaking change in any sub-accelerator is caught here first.
- **Versioning:** depends on the four accelerators via compatible version ranges (not exact pins), so patch/minor updates in a sub-accelerator flow through without a release here, while the integration suite guards against breakage.

## 5. Phase 1 sequencing

0. Create the new folder and git repo: `D:\Claude\claude-orchestration-accelerator` (fresh `git init`, no link to the `Accelerators` remote), plus its root-level `README.md` (overview + links to each nested sub-project) and the corrected reference Claude Code project skeleton with samples (`CLAUDE.md`, `CLAUDE.local.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/skills/`, `.claude/agents/`, `.claude/rules/` — see 4.1). This becomes the root all three sub-projects below nest under, and the source the scaffold command (step 3) copies from.
0.5. ✅ **DONE.** `claude-auth-accelerator` (existing package, existing `Accelerators` repo) — added `build_api_credential(environment)` per 4.0. Verified live in the repo on 2026-08-19.
1. `claude-orchestration-accelerator` (root-level package) — build the `prompting/` and `registry/` sub-packages (promoted `PromptManager` + new `process_registry.yaml` loader) as one installable package.
2. `claude-model-router-accelerator`, at folder path `claude-orchestration-accelerator/model-router/` (decided) — fallback/retry execution logic with the pluggable `agent_sdk`/`messages_api` backend (4.2), depending on step 1's `registry/` sub-package for lookups and on step 0.5's `build_api_credential()` for the Messages API backend's credential.
3. `claude-project-accelerator`, at folder path `claude-orchestration-accelerator/project-accelerator/` (decided — the master accelerator) — library entry point + scaffold command + integration tests, once 1 and 2 exist as installable packages, plus depending on the existing `claude-auth-accelerator`/`ClaudeSDKLoggerAccelerator` from the old `Accelerators` repo.

The master accelerator can't sensibly wrap packages that don't exist yet, so this order is a hard dependency, not just a preference. Step 2 has a hard dependency on step 1 (registry lookups) and step 0.5 (Messages API credential), not just a sequencing preference.

## 6. Open items — Phase 1 — ALL RESOLVED

All items previously open here are now confirmed:

- **Logging wrapper location (confirmed):** lives in `claude-orchestration-accelerator` (`orchestration_accelerator/logging/`, as drafted in 4.1) — not in `claude-project-accelerator`.
- **CLI command name (confirmed):** `cpa` — e.g. `cpa new --project-name my-app`.
- **`.env` reader (confirmed):** `python-dotenv`.
- **Payload validation (confirmed):** plain dict-key checks — no formal JSON Schema.

No open items remain for Phase 1. Section 5's sequencing can proceed as-is.

## 7. Phase 2 — a Claude Skill for accelerator setup

Once Phase 1 exists and is installable, a Claude Skill (`SKILL.md`, invocable e.g. as `/setup-accelerator`) lets anyone starting a new project set it up conversationally instead of reading the repo's README and wiring things by hand.

**Skill vs. plugin (confirmed):** a Claude Skill is instructions Claude follows within a session, using whatever tools that session already has — well suited to a guided conversation that ends in files being written (interview, run the scaffold command, edit `process_registry.yaml`). A plugin bundles one or more skills plus other capabilities (e.g. MCP servers) as a single installable unit, which pays off once there's more than one capability to distribute together (setup + a registry linter + a validation tool, for example). Since today's scope is exactly one guided setup flow, a **skill** is the right choice for Phase 2. If Phase 2 later grows into a multi-capability toolkit, the existing skill can be wrapped inside a plugin at that point without needing to be rewritten.

**Confirmed scope — full guided setup, not just documentation:**

- Interviews the user: project name/location, which process(es) they need (new vs. reusing a sample like `ticketClassification`), target environment (`local`/`dev`/`prod`), and any known model preferences.
- Runs `claude-project-accelerator`'s scaffold command (4.3) to generate the starter project.
- Writes/edits `process_registry.yaml` in the new project based on the interview answers — adding process/step blocks with prompt/model/fallback, rather than leaving the user to hand-edit YAML from a blank template.
- Reports back what was created: folder layout, which processes/steps are configured, which are still running on the built-in default (see 4.1), and the entry-point call shape (4.3) for the user's own code to invoke.

**Confirmed location:** lives inside the `claude-orchestration-accelerator` repo itself (e.g. a `skills/setup-accelerator/` folder at the repo root), versioned alongside the code it sets up — so a skill update ships in the same repo/release as the accelerator changes it needs to stay in sync with, rather than drifting as a separately-maintained artifact.

**Dependency on Phase 1:** this skill orchestrates the scaffold command and registry file built in Phase 1 — it has nothing to invoke until `claude-project-accelerator` (3, in Section 5) exists. Phase 2 work starts only after Phase 1 is functional, not in parallel.

**Open items for Phase 2 (not yet resolved):**

- Exact interview flow/questions the skill asks — not yet drafted.
- How much the skill validates before writing `process_registry.yaml` (e.g. checking a chosen model name is valid) vs. trusting the user's answers and letting the accelerator's own error handling catch problems at run time.
- Whether the skill also offers to run a smoke-test call through the new project's entry point after scaffolding, to confirm the setup actually works end to end, or stops once files are generated.

## 8. Public documentation — tracker item, deferred to implementation

You raised wanting a solid `README.md` and `INSTALLATION.md` so this repo can be posted publicly on GitHub for others to use. Given that none of Phase 1 or Phase 2 has been implemented yet, writing full documentation now would either describe behavior that doesn't exist or lock in a spec ahead of actually building it — so **per your direction, these documents are deferred to implementation time**, tracked here rather than drafted now:

- `README.md` (repo root) and `INSTALLATION.md` get authored once `claude-orchestration-accelerator`, `claude-model-router-accelerator`, `claude-project-accelerator`, and its CLI actually exist and work — documenting verified, working behavior rather than this plan's design intent.
- **License (confirmed):** match the existing `Accelerators` repo — MIT License, copyright Sandeep Pachauri. The new repo's `LICENSE` file should carry the same terms (with its own copyright year at creation time) for consistency across your public repos.
- This is tracked as a deliverable of the implementation phase, not a Phase 1/Phase 2 design item — revisit once there's working code to document.

## 9. What happens after this plan is approved

No code, files, or packages will be created until you confirm this plan. Once approved, Phase 1 proceeds in the sequence in Section 5, and any open item in Section 6 will be raised for a decision at the point it's actually being built, not assumed. Phase 2 (Section 7) begins only once Phase 1 is complete and its own open items are resolved at that time.
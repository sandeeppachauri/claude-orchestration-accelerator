# Multi-turn session context management — implementation plan

## Part A: session context management

## Context

`CONTEXT_MANAGEMENT_PLAN.md` flagged a real gap: today's `{{<stepName>_output}}`
threading is text-templating a prior step's raw output into a fresh
single-turn prompt — not a real accumulating conversation, and
`resume`/`session_id` are deliberately excluded from
`config/capability_registry.yaml` as "session-management concerns."

User feedback (this session) resolved every open question that doc left
unanswered, driven by one architectural insight: a process should pick
**one** context strategy, not mix both. output-threading is a
fixed-shape data pipe (explicit fields flow step to step); session_id is
the model's own memory of its prior turns. Mixing them on one process
would make it ambiguous which one governs a given step's context. Each
process must declare exactly one.

Decisions locked in this session:

1. New top-level process key `context_mode: "threaded" | "session"`.
   Default (omitted) = `"threaded"`, i.e. today's behavior — fully
   backward compatible, no existing process needs edits.
2. `session_id`/`resume` whitelisted in `capability_registry.yaml` for
   `agent_sdk` **only**. `messages_api` has no native session concept
   (`messages.create()` is stateless) — a `context_mode: "session"`
   process must run on `backend: "agent_sdk"`; selecting it with
   `backend: "messages_api"` is a config error, raised the same way
   `UnsupportedCapabilityError` is raised today.
3. Trimming policy is process-configurable, not hardcoded to one
   strategy — a `trimming: {strategy: "turn_count"|"token_budget"|"none", ...}`
   block on the process, `.env`'s `DEFAULT_TRIMMING_STRATEGY` (new key,
   same tier as `DEFAULT_MODEL`) is the fallback when a process omits it.
4. Persistence is **caller-held** for the session *id* — `execute()`
   returns `session_id` in its result; the caller stores it externally
   and passes it back in on the next call via `payload["session_id"]`.
   This repo does not take on a persistence responsibility for the id
   itself.
   **Superseded/extended by decision 6 below**: the *transcript* behind
   that id can now optionally be persisted through the SDK's own
   `SessionStore` mechanism (confirmed against
   `https://code.claude.com/docs/en/agent-sdk/hosting` and
   `.../session-storage` this session) rather than relying solely on
   local disk, which is lost on container restart/scale-down. Decision 4
   still holds for the *id* (caller-held, no id-lookup db in this repo);
   decision 6 covers the *transcript*.
5. Within one `execute()` call spanning multiple steps of a
   `context_mode: "session"` process, session continuation across steps
   is **automatic** — `core.py`'s step loop resumes the same agent_sdk
   session for every step of that run, no per-step opt-in flag needed.
6. **New this session**: a `session_store` process key, config-selectable
   by backend name (`"memory"` | `"s3"` | `"redis"` | `"postgres"` |
   `"custom"`), lets a `context_mode: "session"` process mirror its
   `ClaudeSDKClient` transcript to durable storage via the SDK's native
   `SessionStore` interface (`append`/`load` required, `listSessions`/
   `listSessionSummaries`/`delete`/`listSubkeys` optional) — this is what
   makes a session resumable from a *different host/container*, not just
   a caller holding onto an id against the same machine's local disk.
   Only the SDK's built-in `InMemorySessionStore` ships in this repo;
   S3/Redis/Postgres reference adapters are documented as
   copy-in-yourself (per user decision — avoids forcing `aws-sdk`/
   `ioredis`/`pg` as dependencies on every user of this accelerator).
   `context_mode: "threaded"` processes never touch `session_store` —
   it's meaningless without a `ClaudeSDKClient` to mirror.

## Design

### `process_registry.yaml` schema addition

```yaml
supportSession:
  id: supportSession_01
  description: ...
  context_mode: session          # new key, optional, default "threaded"
  trimming:                      # optional, only meaningful when context_mode: session
    strategy: turn_count         # "turn_count" | "token_budget" | "none"
    max_turns: 20                # strategy-specific param(s)
  session_store:                 # optional, only meaningful when context_mode: session
    backend: memory               # "memory" | "s3" | "redis" | "postgres" | "custom"
    # backend-specific params below, e.g. for "custom":
    # factory: "myproject.stores:build_session_store"   # dotted path, called with no args
  steps: [intake, diagnose, resolve]
  intake: {prompt: ..., model: ..., fallback: [...]}
  ...
```

- `context_mode` validated at process-load time (in
  `orchestration_accelerator.registry`): must be `"threaded"` or
  `"session"`; anything else raises immediately, same fail-fast style as
  existing schema checks.
- `context_mode: "session"` + `backend: "messages_api"` at execute time
  raises `UnsupportedCapabilityError` (reuse the existing exception
  type — same "config says X, backend can't do X" shape as capability
  passthrough validation) before any model call.
- `trimming` is only read/applied when `context_mode: "session"`. Ignored
  (or should raise? — recommend: ignored with a log line, not an error,
  to avoid punishing a leftover key on mode switch) under `"threaded"`.
- `session_store` is only read/applied when `context_mode: "session"` —
  same ignored-under-`"threaded"` treatment as `trimming`. Omitted under
  `"session"` = no store attached, `ClaudeSDKClient` behaves exactly as
  it does today (local-disk-only transcript, lost on container
  restart) — this key is additive, not required to use session mode.

### `session_store` resolution

- `backend: "memory"` resolves to the SDK's built-in
  `InMemorySessionStore`, constructed fresh per `execute()` call unless
  the caller wants cross-call reuse — confirm at implementation time
  whether an in-memory store surviving only one call has any real use
  beyond testing (probably: mostly testing/dev, since decision 4's
  caller-held `session_id` is only useful across calls if *something*
  durable backs it).
- `backend: "s3" | "redis" | "postgres"` are **not** vendored into this
  repo. `.claude/rules/context-mode.md` (new doc, per the "Docs"
  section below) documents copying the matching reference adapter from
  `https://github.com/anthropics/claude-agent-sdk-typescript/tree/main/examples/session-stores/`
  (S3/Redis/Postgres subdirectories) into the consuming project and
  wiring it via `backend: "custom"` + `factory` (see below) — this repo
  does not take on `aws-sdk`/`ioredis`/`pg` as dependencies.
- `backend: "custom"` + `factory: "<dotted.path>:<callable>"` — the
  registry imports and calls that zero-arg callable to get a
  `SessionStore`-conforming object. This is the escape hatch for a
  project-authored adapter (including a copied-in reference adapter)
  without inventing a new registry entry per backend name.
- Whichever store is resolved gets passed as `session_store=` to the
  `ClaudeSDKClient` construction in the new agent_sdk session code path
  (Part A's `model-router` change below) — the SDK's dual-write
  behavior (local disk first, store mirrored, best-effort with
  `mirror_error` system messages on failure) applies automatically;
  this accelerator does not reimplement any of that, only wires the
  store object through.
- **Interacts with decision 4's cross-call `resume`**: when a caller's
  payload supplies `session_id` for a new `execute()` call AND the
  process has `session_store` configured, the `ClaudeSDKClient` is
  constructed with both `resume=<session_id>` and `session_store=<resolved
  store>` — this is what actually enables resuming on a *different*
  host/container, not just a different process on the same machine.
  Without a store, cross-call `resume` only works if the new call lands
  on a host that still has the original run's local transcript on disk
  — worth calling out explicitly in `context-mode.md` since it's an easy
  footgun (works in local dev on one machine, silently fails to resume
  once deployed across multiple hosts/replicas).
- `mirror_error` handling: when a step's `ClaudeSDKClient` yields a
  `{type: "system", subtype: "mirror_error"}` message, log it at
  `Scope.WARNING` (ties into Part B's observability work — same
  `log()` call site) rather than letting it pass through silently in
  the message stream. Store durability failures should be visible to
  whoever's operating this accelerator, not just discoverable by a
  failed resume later.

### `capability_registry.yaml` change

Move `resume`/`session_id` out of the "deliberately excluded" comment in
`agent_sdk.allowed` and into the actual list. Update
`.claude/rules/capability-registry.md`'s comment that currently lists
them as excluded-on-purpose — that comment becomes stale and must be
edited alongside the code change, not left contradicting the new
behavior.

### `core.py` step-loop change — two distinct mechanisms, not one

Correction (this session): the SDK actually offers two different tools
for two different scopes of "session," and the original draft above
conflated them into a single manual `resume`/`session_id`-threading
design. Both are needed:

- **Intra-call continuation (steps 2+ of the same `execute()` call)** —
  use `ClaudeSDKClient` (Python) kept open across the whole step loop,
  rather than manually capturing and re-passing a `session_id` string
  between steps. `ClaudeSDKClient` tracks the conversation itself once
  opened — no id handling needed in `core.py` at all for this case. This
  replaces the "capture id, pass to next step as resume" plumbing
  originally drafted below decision 5 — that plumbing is unnecessary
  when steps stay within one open client.
- **Cross-call continuation (caller re-enters a brand-new `execute()`
  call later, e.g. a different HTTP request handling the same support
  ticket an hour later)** — the first call's `ClaudeSDKClient` is
  already closed by then, so this case still needs the `resume`/
  `session_id` string mechanism, whitelisted per decision 2. This is
  the only place `resume`/`session_id` as an explicit value actually
  gets used.

Revised design:

- New helper (e.g. `_resolve_context_mode(process_cfg)`) reads
  `context_mode`, defaults to `"threaded"`.
- When `"session"`:
  - `core.py`'s step loop opens one `ClaudeSDKClient` for the whole
    `execute()` call (instead of one `query()` call per step as today)
    when no caller-supplied `session_id` is present — seeding a fresh
    session. Every step in `steps_to_run` calls `.query()`/equivalent on
    that same open client, in order; the client's own turn tracking
    supplies the "remembers its own prior turns" behavior, no
    `{{<stepName>_output}}` substitution involved.
  - If the caller's payload *does* supply a `session_id` (continuing a
    previous, now-closed `execute()` call), the client is opened with
    `resume=<that id>` instead of fresh — this is the one place the
    string mechanism is actually exercised.
  - `execute()`'s return payload gains a `session_id` field, read off
    the client after the last step, so the caller can persist it
    externally for a *future* `execute()` call — decision 4 unchanged.
  - Client lifecycle: opened once at the top of the session-mode branch
    of the step loop, closed (or context-managed) once after the last
    step runs — confirm at implementation time whether `ClaudeSDKClient`
    is itself an async context manager or needs explicit `.disconnect()`.
- When `"threaded"`: entirely unchanged — today's per-step `query()`
  call and `{{<stepName>_output}}` substitution path, no client/session
  concept anywhere.
- Trimming: a small pluggable dispatcher
  (`orchestration_accelerator.trimming` module, new) with one function
  per strategy (`turn_count`, `token_budget`, `none`). Applied before
  each step's turn on the open `ClaudeSDKClient` when in session mode,
  trimming/summarizing the accumulated context per the process's (or
  `.env` default's) configured strategy — exact trim mechanics depend
  on what `ClaudeSDKClient` exposes for inspecting/mutating its own
  turn history; confirm at implementation time. `token_budget` needs a
  token-counting helper — reuse whatever the `anthropic`/
  `claude_agent_sdk` package already exposes rather than writing a new
  tokenizer.

### `model-router` / backend change

`model-router/src/model_router_accelerator/backends.py` needs a new
code path (or a variant of `call_agent_sdk()`) that opens/reuses a
`ClaudeSDKClient` instead of calling the stateless `query()` helper,
for `context_mode: "session"` steps — check the installed
`claude_agent_sdk` version's exact `ClaudeSDKClient` API (constructor
args, `resume` support, `session_store` support, how it surfaces its
own session id after a turn) before finalizing this. `context_mode:
"threaded"` steps keep using today's `query()` call, unchanged.

The `ClaudeSDKClient` construction takes the resolved `session_store`
object (per the "`session_store` resolution" design section above)
alongside `resume` — confirmed from the SDK docs this session that
`session_store`/`resume` combine at construction time, not as separate
calls. Also watch the message stream for `{type: "system", subtype:
"mirror_error"}` and surface it up to `core.py`'s logging call site
rather than swallowing it.

### Docs

- New `.claude/rules/context-mode.md` describing the schema (mirror the
  style of `process-registry.md` and `batch-registry.md`) — since this
  is a new cross-cutting concept, it deserves its own rule doc rather
  than being folded into `process-registry.md`.
- `CLAUDE.md`'s "Configuration" section gets a short pointer to the new
  rule doc, same pattern as its existing pointers to `mcp-scope.md`/
  `guardrails-registry.md`.
- `CONTEXT_MANAGEMENT_PLAN.md`'s "Status" section updated from "Not
  started" once this lands, or removed if this plan doc fully supersedes
  it.

### Scaffold sync

Per `CLAUDE.md`'s "Keeping the scaffold in sync" rule:
`project-accelerator/src/project_accelerator/scaffold_data/` must mirror
this change — the new `context_mode`/`trimming`/`session_store` keys,
the updated `capability_registry.yaml`, and (if a worked example is
added) a `context_mode: session` example process alongside
`templatingDemo`. Run
`python project-accelerator/scripts/check_scaffold_sync.py` after
implementation, before considering this done.

## Files to touch

- `config/process_registry.yaml` — add `context_mode`/`trimming`/
  `session_store` to at least one example process (new, don't retrofit
  existing ones unless demonstrating the feature).
- `config/capability_registry.yaml` — whitelist `resume`/`session_id`
  under `agent_sdk.allowed`.
- `.claude/rules/capability-registry.md` — remove the now-stale
  "deliberately excluded" language for `resume`/`session_id`.
- New `.claude/rules/context-mode.md` — also documents `session_store`
  backend resolution and the copy-in-yourself S3/Redis/Postgres adapter
  workflow.
- `orchestration_accelerator/registry.py` (or wherever process schema
  validation lives) — validate `context_mode`, wire trimming strategy
  resolution + `.env` fallback; new `session_store` resolution
  (`memory` → `InMemorySessionStore`, `custom` + `factory` → import and
  call the dotted-path callable, `s3`/`redis`/`postgres` → clear error
  pointing at the docs since no adapter ships in this repo).
- New `orchestration_accelerator/trimming.py` (or similar) — strategy
  dispatcher.
- `orchestration_accelerator/core.py` — step-loop opens/reuses a
  `ClaudeSDKClient` across all steps of a `context_mode: "session"`
  call; seeds it with caller-supplied `session_id` via `resume` when
  present; passes the resolved `session_store` object through when
  configured; reads the final session id off the client for
  `execute()`'s return payload; logs `mirror_error` system messages at
  `Scope.WARNING`.
- `model-router/src/model_router_accelerator/backends.py` — new
  `ClaudeSDKClient`-based code path (alongside, not replacing,
  `call_agent_sdk()`'s existing stateless `query()` path used by
  `context_mode: "threaded"` steps).
- `.env.example` (or equivalent) — add `DEFAULT_TRIMMING_STRATEGY`.
- `project-accelerator/src/project_accelerator/scaffold_data/...` —
  mirror all of the above.
- `CLAUDE.md` — pointer to new rule doc.
- `CONTEXT_MANAGEMENT_PLAN.md` — status update.

## Verification

- Unit test: a `context_mode: "session"` process on `agent_sdk` across
  2+ steps — assert every step's turn went through the *same* open
  `ClaudeSDKClient` instance (not a fresh `query()` call each time), and
  `execute()`'s final result includes a `session_id` read off that
  client.
- Unit test: same process re-invoked in a new `execute()` call with a
  caller-supplied `session_id` in the payload — assert the new
  `ClaudeSDKClient` is opened with `resume=<that id>`, not a fresh
  session (this is the only test exercising the `resume` string path).
- Unit test: `context_mode: "session"` + `backend: "messages_api"` raises
  `UnsupportedCapabilityError` before any model call.
- Unit test: `context_mode: "threaded"` (or omitted) — existing
  `{{stepName}_output}}` tests (`tests/test_sample_pipeline.py`) keep
  passing unmodified, proving no regression to default behavior.
- Trimming: one test per strategy (`turn_count`, `token_budget`, `none`)
  confirming context is actually shortened/untouched as expected.
- Unit test: `session_store: {backend: memory}` — `execute()` call 1
  populates the store; `execute()` call 2 with `resume: <session_id>`
  and the *same store instance* resumes with full context, proving the
  transcript came from the store rather than local disk (e.g. by
  running call 2 against a fresh local config dir / temp
  `CLAUDE_CONFIG_DIR` so there is no local transcript to fall back to).
- Unit test: `session_store: {backend: custom, factory: "..."}` —
  registry resolves and calls the dotted-path factory, resulting object
  gets passed through to `ClaudeSDKClient` construction.
- Unit test: `session_store: {backend: s3}` (or `redis`/`postgres`) with
  no adapter installed — raises a clear config error pointing at the
  docs, not an `ImportError` deep in a missing dependency.
- Unit test: a mocked `mirror_error` system message in the
  `ClaudeSDKClient` stream — asserts it's logged at `Scope.WARNING` and
  the query continues (matches documented SDK behavior: mirror failures
  don't interrupt the agent).
- Run `pytest tests/test_sample_pipeline.py` plus new tests.
- Run `python project-accelerator/scripts/check_scaffold_sync.py`.

## Part B: model-call observability (token/cache/latency/stop_reason logging)

### Context

Confirmed by investigation this session: today, only tool calls made
during an `agent_sdk` turn get logged (`PreToolUse`/`PostToolUse` hooks
in `orchestration_accelerator/logging/wrapper.py:44-56`, producing
`TOOL_CALL` records). The model call itself — the actual response from
Claude — logs **nothing**. `MODEL_CALL_START`/`MODEL_CALL_END` scopes
exist in the `Scope` enum and are enabled in `logger_config.json`, but
`backends.py`'s `call_agent_sdk()`/`call_messages_api()` never call
`log()`/`log_event()` for them.

This means every debugging session today is blind to: token usage
(input/output/cache read/cache creation), which model in the fallback
chain actually served a request, `stop_reason` (silently truncated
output looks identical to a complete one in current logs), request
latency, and the Anthropic request id needed for support escalations.
This is a real, separate gap from Part A's session-context work — same
call sites (`backends.py`), different concern (observability, not
context) — folded into this plan file per user preference rather than a
standalone doc.

### Design

- **`messages_api`** (`model-router/src/model_router_accelerator/backends.py:186-192`):
  wrap `client.messages.create()` with a timer; after the call, capture
  `response.usage.input_tokens`, `.output_tokens`,
  `.cache_creation_input_tokens`, `.cache_read_input_tokens`,
  `response.stop_reason`, `response.model` (actual model served —
  matters because of the fallback chain), `response.id`.
- **`agent_sdk`** (`backends.py:96-106`): currently only pattern-matches
  `AssistantMessage`. Also match `ResultMessage` (and check the
  installed `claude_agent_sdk` types module for where usage/session_id
  actually live on SDK message types before finalizing field names) —
  confirm this doesn't silently no-op if the SDK's usage shape differs
  from messages_api's.
- **Return shape**: both `call_agent_sdk()`/`call_messages_api()`
  currently return a bare `text: str` (`backends.py:123`, `:202`) — no
  path exists today to carry usage/latency/stop_reason up to
  `execute_with_fallback()`. Change both to return a small result object
  (e.g. `{text, model_used, usage: {...}, stop_reason, request_id,
  latency_ms}`) and update `execute_with_fallback()`'s callers in
  `core.py` accordingly.
- **Logging call site**: `orchestration_accelerator/logging/wrapper.py`'s
  `log()` already accepts arbitrary `**fields` (`:59-66`) — no wrapper
  code change needed. Add one `log(Scope.MODEL_CALL_END, ...)` call
  right after each backend call returns, passing the new fields.
- **Schema**: per user decision, **no** `TraceRecord` dataclass change —
  all new fields (`input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_creation_tokens`, `stop_reason`, `request_id`, `model_used`,
  `latency_ms`) go into the existing catch-all `metadata: dict` field
  (`ClaudeSDKLoggerAccelerator/src/sdk_logger_accelerator/schema.py:26-41`).
  Zero cross-repo schema change, ships independently of
  `ClaudeSDKLoggerAccelerator` release cadence. Tradeoff accepted:
  untyped/unindexed for anyone querying logs later — revisit as
  first-class fields if log-querying tooling is ever built against this.
- **Fallback-chain transition logging**: when a step falls back from
  `model` to a `fallback` entry, log that transition explicitly (e.g.
  `Scope.WARNING` or a dedicated metadata flag
  `metadata: {fallback_from: ..., fallback_to: ..., reason: ...}`) — not
  just the final serving model on the eventual success. Currently that
  transition is invisible even if the final model gets logged.

### `execute()`'s return shape also gets enriched (not log-only)

User decision (this session): a caller building custom logic around a
step's result (branch on `stop_reason`, retry when tool budget was
exhausted instead of a real answer, inspect which tool the model called
and why it stopped) can't be expected to grep the JSONL trace log at
runtime just to get that — it must be in the value `execute()` hands
back, in addition to the log entry. Both surfaces get the data, not one
or the other.

This is a **breaking change** to `execute()`'s contract — today's
docstring (`project-accelerator/src/project_accelerator/core.py:367-369`)
promises `{step_name: validated_output}` (bare string per step); every
existing caller (`examples/sample_usage.py`, `tests/test_sample_pipeline.py`,
any scaffolded project built on `cpa new`) reads that value as a string
and will break the moment it becomes a dict. Treat this as a deliberate,
called-out breaking change — update every in-repo caller in the same
change, and call it out prominently in whatever changelog/release note
this project keeps, since it will break scaffolded projects on upgrade
too if they don't re-pull scaffold_data.

New shape per step, replacing the bare string:

```python
{
    "output": "<validated text, same value today's bare string was>",
    "model_used": "claude-haiku-4-5-20251001",   # actual model that served, post-fallback
    "stop_reason": "end_turn",                    # or "max_tokens", "tool_use", etc.
    "usage": {
        "input_tokens": ...,
        "output_tokens": ...,
        "cache_creation_tokens": ...,             # messages_api only; agent_sdk if SDK exposes it
        "cache_read_tokens": ...,
    },
    "tool_calls": [{"name": "...", "count": ...}],  # agent_sdk only; empty list on messages_api
    "request_id": "...",                           # messages_api only; None on agent_sdk if unavailable
    "latency_ms": ...,
    "session_id": "...",                            # agent_sdk + context_mode: session (Part A) only
}
```

- `output` carries exactly what today's bare string carried — anything
  reading `results[step_name]` today and treating it as text needs to
  change to `results[step_name]["output"]`, but no information is lost
  in the change, only relocated.
- Fields that only exist on one backend (`tool_calls` on agent_sdk,
  `request_id` on messages_api) are present with an empty/`None` value on
  the other backend, not omitted — so caller code can check a key
  without a `KeyError` regardless of which backend ran.
- `validate_output` (wherever JSON-shape validation of a step's raw text
  happens today) validates `output`, unchanged — the new fields are
  metadata about the call, not part of what gets JSON-parsed.

### Files to touch

- `model-router/src/model_router_accelerator/backends.py` — capture
  usage/stop_reason/model/request_id/latency in both `call_*` functions;
  change return shape to the structured dict above; log fallback
  transitions.
- `model-router/src/model_router_accelerator/router.py` —
  `execute_with_fallback()` passes the structured result through
  unchanged (it already just forwards whatever the backend call
  returns — confirm this at implementation time).
- `orchestration_accelerator/core.py` — `_run_one_step()`/`_execute_async()`
  store the structured dict as `results[step_name]` instead of a bare
  string; update the `{{<stepName>_output}}` threading logic
  (`_execute_async()` around line 337-350) to pull `results[name]["output"]`
  when building `f"{name}_output"` placeholders — **this is the one spot
  where the breaking change could silently corrupt output** if missed,
  since today it does `out for name, out in results.items()` assuming
  `out` is already a string; add the `MODEL_CALL_END` `log()` call here
  too, reusing the same captured fields for both surfaces.
- `examples/sample_usage.py`, `tests/test_sample_pipeline.py` — update
  every place that reads `results[step]` as a string to read
  `results[step]["output"]`.
- `project-accelerator/src/project_accelerator/scaffold_data/...` —
  mirror the `backends.py`/`core.py`/example changes (scaffold-sync rule
  in `CLAUDE.md`) — scaffolded projects' own examples must match too.
- No changes needed to `logger_config.json`, `TraceRecord` schema, or
  `ClaudeSDKLoggerAccelerator` itself — logging side is additive use of
  existing surfaces only; only the return-value side is breaking.

### Verification

- Unit test: `call_messages_api()` returns usage/stop_reason/model/id
  fields matching a mocked `response.usage`/`.stop_reason`/etc.
- Unit test: `call_agent_sdk()` captures usage/session data from
  `ResultMessage` (confirm exact SDK field names against the installed
  package first).
- Unit test: a forced fallback (first model errors) produces a logged
  transition record before the successful call's `MODEL_CALL_END`.
- Unit test: `execute()` on a multi-step process returns
  `results[step]["output"]` equal to what today's `results[step]` bare
  string would have been — proves no information loss, only relocation.
- Unit test: `{{<stepName>_output}}` threading (existing
  `tests/test_sample_pipeline.py` coverage of `extract_v2.yaml`/
  `classify_soa.yaml`) still substitutes the correct text — proves the
  `results[name]["output"]` extraction in the threading logic didn't
  silently thread a dict/repr into a later step's prompt instead of the
  text.
- Manual: run a sample pipeline, inspect the JSONL log output, confirm
  `metadata` contains token counts/cache counts/stop_reason/model_used/
  latency_ms per model call, and that cache_read vs cache_creation
  numbers actually move between first and cached calls on a
  `cache_control`-enabled step (`templatingDemo.triage`).
- Run `pytest tests/test_sample_pipeline.py`.
- Run `python project-accelerator/scripts/check_scaffold_sync.py`.

## Part C: optional `assistant_prompt` seed turn in prompt YAML

### Context

Confirmed by reading `prompt_manager.py`: today a prompt YAML has exactly
two content fields, `system_prompt` and optional `user_prompt`
(`PromptConfig` dataclass, `prompt_manager.py:58-66`). Both backends
build a single-turn `messages` array —
`[{"role": "user", "content": user_content}]`
(`backends.py:181`/`:190`) — there is no way today for a process author
to seed a canned prior assistant turn (few-shot priming, "continue from
this canned response" patterns). This gap is separate from Part A
(real session/turn history from `resume`) — this is a *static, per-call*
seed turn declared in config, not a live conversation.

### Design

- `PromptConfig` gains an optional `assistant_prompt: str | None = None`
  field (`prompt_manager.py:66`), same tier as `user_prompt`.
- `PromptManager.render()`'s placeholder set
  (`prompt_manager.py:174-176`) also unions
  `_PLACEHOLDER_RE.findall(cfg.assistant_prompt)` when present, and the
  final `_sub()` pass (`:227-230`) resolves it the same way as
  `system_prompt`/`user_prompt` — same required-match validation, one
  code path, per user decision (no separate templating rules for this
  field).
- `render()`'s return signature extends from
  `(cfg, rendered_system_prompt, rendered_user_content)` to
  `(cfg, rendered_system_prompt, rendered_assistant_content, rendered_user_content)`
  — every caller of `render()` needs updating (currently only
  `core.py`'s `_run_one_step()`, per earlier exploration).
- Message array construction in both backends: when
  `assistant_prompt` is present, prepend
  `{"role": "assistant", "content": rendered_assistant_content}` before
  the user turn — `messages: [{"role": "assistant", ...}, {"role": "user", ...}]`.
  When absent, unchanged single-turn array — fully backward compatible,
  no existing prompt YAML needs edits.
- `agent_sdk`'s `query(prompt=user_content, options=options)` call
  (`backends.py:96`) takes a single string prompt, not a message array —
  confirm at implementation time whether `claude_agent_sdk` exposes any
  way to seed a prior assistant turn before the first real query call,
  or whether this feature is `messages_api`-only. If agent_sdk has no
  such surface, `assistant_prompt` on an agent_sdk-backed step should
  raise clearly (same "config says X, backend can't do X" pattern as
  Part A's `context_mode: session` + `messages_api` restriction) rather
  than silently no-opping.

### Files to touch

- `src/orchestration_accelerator/prompting/prompt_manager.py` —
  `PromptConfig.assistant_prompt` field; `has_placeholders()` and
  `render()` include it; `render()`'s return tuple grows by one value.
- `project-accelerator/src/project_accelerator/core.py` —
  `_run_one_step()` unpacks the new `render()` tuple, passes the
  assistant seed through to the backend call.
- `model-router/src/model_router_accelerator/backends.py` — both
  `call_agent_sdk()`/`call_messages_api()` accept the optional assistant
  seed content and build the message array accordingly (or raise, per
  the agent_sdk caveat above).
- A new example prompt YAML demonstrating `assistant_prompt` (e.g.
  added to `templatingDemo` alongside `triage`/`escalate`, or its own
  step) — `.claude/rules/prompt-yaml.md` (if it exists) or
  `process-registry.md`'s "Runtime input & `{{key}}` placeholders"
  section gets a short addition documenting the field.
- `project-accelerator/src/project_accelerator/scaffold_data/...` —
  mirror `prompt_manager.py`/`core.py`/`backends.py` changes and the new
  example (scaffold-sync rule in `CLAUDE.md`).

### Verification

- Unit test: a prompt YAML with `assistant_prompt` (no placeholders) —
  `render()` returns the literal text unchanged, and the constructed
  `messages_api` message array has the assistant turn before the user
  turn.
- Unit test: `assistant_prompt` with `{{key}}` placeholders — same
  required-match validation as `user_prompt` (missing key raises
  `PromptValidationError`; extra unrelated keys in a shared multi-step
  input dict are ignored, per existing `user_prompt` behavior).
- Unit test: existing prompt YAML files with no `assistant_prompt` —
  `render()`'s 4-tuple has `None`/empty for the assistant slot, message
  array construction stays single-turn, zero behavior change — proves
  backward compatibility.
- Unit test (or explicit skip + doc note, depending on what agent_sdk's
  `query()` actually supports): `assistant_prompt` on an agent_sdk step
  either works or raises a clear config error, not a silent no-op.
- Run `pytest tests/test_sample_pipeline.py` plus new tests.
- Run `python project-accelerator/scripts/check_scaffold_sync.py`.

## Part D: streaming (`stream: true` per-step capability)

### Context

Confirmed by reading `backends.py`: no streaming exists anywhere today.
`call_agent_sdk()` already iterates `query()` as an async generator
(`backends.py:96-106`) but fully concatenates every `TextBlock` before
returning; `call_messages_api()` makes a single blocking
`messages.create()` call (`:186`/`:192`) with no `stream=True`. Both
underlying SDKs are already stream-capable at the wire level — this gap
is purely that the accelerator buffers everything before the caller
sees any of it, once per step, for every step, regardless of whether
that step's output is meant for real-time display.

This is independent of Parts A–C (context/session, observability,
assistant-seed turns) but touches the same call sites in the same files,
so — per user decision — it's folded into this plan rather than a
separate doc, to close every open gap in one pass instead of scattering
follow-ups.

### Design

- New optional step key `stream: true` in `process_registry.yaml`,
  capability-passthrough tier (same as `max_turns`/`thinking`) —
  whitelisted per backend in `capability_registry.yaml`. Omitted =
  today's fully-buffered behavior, byte-for-byte unchanged.
- `execute()`'s payload gains an optional `on_chunk` callback (sync or
  async callable, `(step_name: str, chunk: str) -> None`). When a
  step has `stream: true` and the caller supplied `on_chunk`, `core.py`
  invokes it once per chunk as the backend call yields them. When a
  step has `stream: true` but the caller supplied no `on_chunk`, chunks
  are simply accumulated (same end result as non-streaming, minus the
  real-time emission) — `stream: true` with no callback must not raise,
  since a caller might enable it only for some steps or add the
  callback later.
- **Cross-step wiring stays simple, per user decision**: step 2 always
  waits for step 1's stream to fully complete before starting, and
  receives the same complete assembled text via `{{step1_output}}` as
  today — streaming is purely an emission/observability channel to the
  caller, not a new data shape flowing between steps. This keeps Part
  D fully orthogonal to the `{{<stepName>_output}}` threading mechanism
  (`process-registry.md`'s existing rule) — no change needed there.
- `call_agent_sdk()`: when `stream=True` extra kwarg is set, invoke
  `on_chunk` per `TextBlock.text` inside the existing
  `async for message in query(...)` loop (`:96-102`) instead of only
  concatenating — no new SDK call shape needed, since it already
  streams internally; this is just exposing what's already flowing.
- `call_messages_api()`: when `stream=True`, switch to
  `client.messages.stream(...)` (or `messages.create(..., stream=True)`
  per whatever the installed `anthropic` SDK version's streaming
  helper is — confirm exact API at implementation time) and invoke
  `on_chunk` per text delta event, accumulating the same way for the
  final `output` value Part B's structured return still needs.
- Interacts with Part B's structured return shape: the final
  `results[step_name]["output"]` is identical whether or not
  `stream: true` was set — streaming only adds a side-channel emission
  during the call, never changes what's returned after it.

### Files to touch

- `config/process_registry.yaml` — add a `stream: true` example (e.g.
  a new step, or documented as a comment like `cache_control`'s worked
  example).
- `config/capability_registry.yaml` — whitelist `stream` for both
  `agent_sdk` and `messages_api`.
- `model-router/src/model_router_accelerator/backends.py` — both
  `call_*` functions accept `stream` + an internal chunk-emission
  callback, forward chunks when set.
- `orchestration_accelerator/core.py` — thread the caller's `on_chunk`
  from `execute()`'s payload down to the backend call for whichever
  step(s) have `stream: true`; no-op accumulation path when no callback
  supplied.
- `.claude/rules/` — new short doc (or a section in
  `capability-registry.md`) documenting `stream`/`on_chunk`, mirroring
  the `cache_control` documentation style.
- `project-accelerator/src/project_accelerator/scaffold_data/...` —
  mirror all of the above (scaffold-sync rule in `CLAUDE.md`).

### Verification

- Unit test: a `stream: true` step with a fake `on_chunk` collecting
  chunks — assert concatenated chunks equal `results[step]["output"]`
  exactly (proves no data loss between the streaming and buffered
  paths).
- Unit test: a `stream: true` step with no `on_chunk` supplied — runs
  without error, `results[step]["output"]` unchanged from non-streaming
  behavior.
- Unit test: a multi-step process where step 1 has `stream: true` and
  step 2 does not — step 2's `{{step1_output}}` placeholder receives
  the full text, proving cross-step wiring is unaffected (per the
  "full text only" decision).
- Unit test: `stream: false`/omitted — existing behavior, zero
  regression (`tests/test_sample_pipeline.py` unmodified, still green).
- Run `pytest tests/test_sample_pipeline.py` plus new tests.
- Run `python project-accelerator/scripts/check_scaffold_sync.py`.

## Cross-cutting: keep docs and examples aligned (applies to Parts A–D)

Per user instruction, every part of this plan must ship with its docs
and examples updated in the same change, not as a follow-up:

- Every new/changed schema key (`context_mode`, `trimming`,
  `session_store`, the new `execute()`/`results[step]` return shape,
  `assistant_prompt`, `stream`) must be reflected in:
  - `CLAUDE.md` (root) — its "Configuration" section already lists
    `process_registry.yaml`/`capability_registry.yaml`/`.env` as the
    controlling files; add pointers the same way it currently points to
    `.claude/rules/mcp-scope.md`/`guardrails-registry.md`.
  - The relevant `.claude/rules/*.md` file for each key
    (`process-registry.md`, `capability-registry.md`, new
    `context-mode.md`, etc.) — these are the authoritative schema docs
    referenced throughout this plan and must not drift from the shipped
    YAML.
  - `config/process_registry.yaml`'s own inline comments (its existing
    style — see `templatingDemo.escalate`'s heavily-commented worked
    example) for at least one example process per new feature.
  - `examples/sample_usage.py` (or wherever the worked runnable example
    lives) — must call `execute()` using the **new** return shape
    (Part B) and demonstrate at least one of the newer capabilities
    where it fits naturally, not left calling the old bare-string
    contract.
  - `tests/test_sample_pipeline.py` — kept green against the new
    contract, not just left passing by accident.
- `project-accelerator/src/project_accelerator/scaffold_data/` must
  mirror every one of the above — per `CLAUDE.md`'s existing "Keeping
  the scaffold in sync" rule, this is not optional or a follow-up; a
  project scaffolded via `cpa new` after this change must demonstrate
  the same current state as this repo, not a stale pre-change snapshot.
  Run `python project-accelerator/scripts/check_scaffold_sync.py` as
  the final check across every part, not per-part.
- `CONTEXT_MANAGEMENT_PLAN.md`'s "Status" section (currently "Not
  started") gets updated once implementation begins/completes, or the
  file is removed if this plan document fully supersedes it as the
  living reference.

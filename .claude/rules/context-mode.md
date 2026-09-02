# `context_mode` schema (`process_registry.yaml`)

A new top-level process key, alongside `id`/`description`/`steps`:

```yaml
supportSession:
  id: supportSession_01
  description: ...
  context_mode: session          # "threaded" | "session", optional, default "threaded"
  trimming:                      # optional, only meaningful when context_mode: session
    strategy: turn_count         # "turn_count" | "token_budget" | "none"
    max_turns: 20                # strategy-specific param(s)
  session_store:                 # optional, only meaningful when context_mode: session
    backend: memory               # "memory" | "custom" | "s3" | "redis" | "postgres"
    # factory: "myproject.stores:build_session_store"   # required for backend: custom
  steps: [intake, diagnose]
  intake: {prompt: ..., model: ..., fallback: [...]}
  diagnose: {prompt: ..., model: ..., fallback: [...]}
```

A process must pick **one** context strategy, not mix both:
`context_mode: threaded` (default, today's behavior) threads a prior
step's output into a fresh single-turn prompt via
`{{<stepName>_output}}` placeholders (see `.claude/rules/process-registry.md`).
`context_mode: session` gives steps a real, accumulating agent_sdk
conversation instead -- a later step sees an earlier step's turn as
actual conversation history, no `{{<stepName>_output}}` templating
involved.

## Which SDK call each mode actually makes

Mapping onto the SDK's own two interfaces (`query()` one-shot vs.
`ClaudeSDKClient` conversational) -- these are not equally close matches:

- **`context_mode: session` is a direct match to `ClaudeSDKClient`.**
  `run_session_turn()` (`model_router_accelerator/backends.py`) calls
  `client.query(user_content)` on one already-open, connected
  `ClaudeSDKClient` shared across every step -- the same stateful,
  context-accumulating interface the SDK's own docs describe. Nothing
  added on top; the client's native turn history *is* the mechanism.
- **`context_mode: threaded` is NOT the same interface with app-level
  bookkeeping layered on -- it is literally the raw one-shot call.**
  `call_agent_sdk()` calls the module-level `claude_agent_sdk.query(prompt=user_content,
  options=options)` per step -- stateless, fresh context every
  invocation, no memory of any prior call, exactly like the SDK's own
  one-shot column. `{{<stepName>_output}}` templating is this repo's
  *own* addition on top of that stateless primitive: `core.py` copies a
  prior step's `output` string into the next step's rendered prompt
  text before the call, so the model sees continuity as plain text in
  its single turn -- not because the SDK call itself remembers
  anything. A threaded step's `query()` call is exactly as blind to
  prior turns as any other `query()` call; the illusion of continuity is
  built entirely in `core.py`, not in the SDK layer.

**Practical takeaway**: if a multi-step process needs the model to
literally see its own earlier turns (native conversation history, tool
results carried forward, etc.), use `context_mode: session` -- it is the
real `ClaudeSDKClient` conversation. `context_mode: threaded` only
carries forward whatever text `core.py` explicitly copies via
`{{<stepName>_output}}`; anything not captured in that placeholder
(intermediate reasoning, tool calls, discarded draft text) does not
survive to the next step, because each step's `query()` call has no
memory of the previous one.

## `context_mode: session` mechanics

- **agent_sdk only.** `messages_api` has no native session concept
  (`messages.create()` is stateless) -- selecting `context_mode: session`
  with `backend: "messages_api"` raises `UnsupportedCapabilityError`
  before any model call, the same "config says X, backend can't do X"
  shape as capability-passthrough validation.
- **Intra-call continuation is automatic.** Within one `execute()` call,
  `core.py`'s step loop opens one `claude_agent_sdk.ClaudeSDKClient` for
  the whole call and runs every step's turn on that same open client, in
  order -- no per-step opt-in flag needed. The client's own turn
  tracking supplies "remembers its prior turns," not
  `{{<stepName>_output}}` substitution.
- **Cross-call continuation uses `resume`.** The first call's
  `ClaudeSDKClient` is closed by the time a caller re-enters a brand-new
  `execute()` call later (e.g. a different HTTP request handling the
  same support ticket an hour later). Pass the earlier call's returned
  `session_id` back in as `payload["session_id"]` -- the new client is
  constructed with `resume=<that id>` instead of starting fresh. This is
  the only place `resume`/`session_id` as an explicit string value gets
  used; see `config/capability_registry.yaml`'s `agent_sdk.allowed` list.
- **`ClaudeAgentOptions.resume` and `.continue_conversation` are mutually
  exclusive** per the SDK's own docstring -- this accelerator never sets
  `continue_conversation`, only `resume`, so this is a non-issue as long
  as you don't hand-construct `ClaudeAgentOptions` yourself outside
  `open_agent_sdk_session()`.
- **`execute()`'s return value carries the session id per step**, under
  `results[step_name]["session_id"]` (same field every step already
  carries -- see the observability contract in
  `project_accelerator.core.execute`'s docstring), read off the last
  `ResultMessage`/`AssistantMessage` the client returned. Persist it
  externally (this repo does not take on an id-lookup database) and pass
  it back in via `payload["session_id"]` for a later call.
- **Two different `session_id`s appear in `logs/trace.log` -- they are
  not the same thing, and it is easy to misread one for the other.**
  Every `TraceRecord`'s top-level `session_id` field (`core.py:566`,
  `str(uuid.uuid4())`) is a **fresh trace-correlation id generated once
  per `execute()` call** -- it groups every log line belonging to that
  one call together and always changes call to call, resumed session or
  not. It is unrelated to conversation identity. The **actual SDK
  conversation id** -- the one that must stay identical across a
  resume for continuity to be real -- is nested instead, under each
  `MODEL_CALL_END` record's `metadata.usage.session_id` (and returned to
  the caller as `results[step_name]["session_id"]`, per the point
  above). To confirm a `resume` call actually continued the same
  conversation, compare `metadata.usage.session_id` across calls, not
  the trace record's own top-level `session_id` -- the latter changing
  on every call is expected and does not indicate a new/failed resume.
- **`metadata.claude_session_id`** -- for `context_mode: session`
  processes only, every `MODEL_CALL_START`/`MODEL_CALL_END`/`FULL_TURN`/
  `WARNING`/`ERROR` trace record also carries this field under
  `metadata`, set to the actual `claude_agent_sdk` conversation id (the
  same value as `metadata.usage.session_id` on `MODEL_CALL_END`, and as
  `results[step_name]["session_id"]`). It exists purely to make
  `grep`/log-search easy: filter `logs/trace.log` on one
  `claude_session_id` value to see every trace line belonging to one
  real conversation, across turns *and* across a `resume`'d later
  `execute()` call -- something the per-call top-level `session_id`
  cannot do. On a resumed call it is populated from `payload["session_id"]`
  from the very first record (known upfront); on a fresh call it is
  `null`/absent on turn 0's `MODEL_CALL_START` (not known until the
  first turn's result comes back) and populated from that point on. A
  session-rotation trim event (see `trimming` below) resets it to
  `null` until the rotated client's first turn resolves, since rotation
  opens a brand-new conversation. `context_mode: "threaded"` never sets
  this field -- there is no single continuous SDK conversation to name,
  since each step is its own stateless `query()` call (see "Which SDK
  call each mode actually makes" above).
- **System prompt / model / max_turns are fixed for the client's whole
  lifetime.** `ClaudeAgentOptions` is set once at `ClaudeSDKClient`
  construction -- there is no per-turn override. The client is built
  from the *first* step's `model`/`max_turns`/rendered `system_prompt`;
  later steps' own prompt YAML `system_prompt` is still rendered and
  used as that step's query text/context, but the client-level system
  prompt does not change turn to turn. Give every step in a
  `context_mode: session` process the same `model` if this matters to
  you.

## `session_store` -- durable, cross-host resumability

Without a `session_store`, cross-call `resume` only works if the new
`execute()` call lands on a host that still has the original run's local
transcript on disk -- **an easy footgun**: it works in local dev on one
machine, and silently fails to resume once deployed across multiple
hosts/replicas. `session_store` mirrors the transcript to durable
storage via the SDK's native `SessionStore` interface
(`append`/`load` required; `list_sessions`/`list_session_summaries`/
`delete`/`list_subkeys` optional), so a *different* host/container can
materialize and resume the same session.

- `backend: "memory"` resolves to `claude_agent_sdk`'s built-in
  `InMemorySessionStore` -- mostly useful for local dev/testing, since an
  in-memory store doesn't survive past the current process anyway.
- `backend: "custom"` + `factory: "dotted.module.path:callable_name"` --
  the registry imports that module and calls the named zero-arg callable
  to get a `SessionStore`-conforming object. This is the escape hatch for
  a project-authored adapter, including a copied-in reference adapter
  (see below).
- `backend: "s3" | "redis" | "postgres"` are **not vendored into this
  repo** -- this avoids forcing `aws-sdk`/`ioredis`/`pg` as dependencies
  on every user of this accelerator. Selecting one of these three names
  directly raises `SessionStoreResolutionError` with a message pointing
  back here, not a bare `ImportError` from a missing dependency. Copy the
  matching reference adapter from
  `https://github.com/anthropics/claude-agent-sdk-typescript/tree/main/examples/session-stores/`
  (the S3/Redis/Postgres subdirectories) into your project, then wire it
  in via `backend: custom` + `factory` pointing at your adapter's
  builder function.
- Whichever store resolves gets passed to `ClaudeSDKClient` construction
  as `session_store=`, combined with `resume=` at the same construction
  call. The SDK's own dual-write behavior (local disk first, store
  mirrored, best-effort) applies automatically -- this accelerator only
  wires the store object through, it does not reimplement any of that.
- **Mirror failures are visible, not silent.** When the client yields a
  `MirrorErrorMessage` (a `SessionStore.append()` call failed), it is
  logged at `Scope.WARNING` via the same `log()` call site Part B's
  observability work uses, carrying the mirror error text and the
  `SessionKey` it failed on. A store durability failure should be
  discoverable in the trace log, not only as a failed resume later.
- `context_mode: "threaded"` processes never touch `session_store` -- it
  is meaningless without a `ClaudeSDKClient` to mirror, and is silently
  ignored (with a log line, not an error) if present on a threaded
  process, to avoid punishing a leftover key on a mode switch.

## `trimming` -- no in-place SDK primitive, so this is session-rotation

`ClaudeSDKClient` exposes no API to inspect or mutate its own turn
history mid-session (confirmed against the installed SDK source --
`get_context_usage()` is read-only, and `ConversationResetMessage`
starts an entirely fresh conversation rather than selectively dropping
old turns). Trimming here is therefore implemented as **session
rotation**, not in-place history surgery: when a strategy's threshold is
crossed, the step loop closes the current `ClaudeSDKClient` and opens a
new one, seeded with a synthesized system-prompt-level summary of the
turns being dropped, rather than a raw resume of the same session.

- `strategy: "turn_count"` -- rotate every `max_turns` steps (default 20).
- `strategy: "token_budget"` -- rotate once `get_context_usage()`'s
  running total crosses `max_tokens` (default 100000).
- `strategy: "none"` -- no rotation, ever (matches today's behavior on a
  process with no `trimming` block at all).
- `.env`'s `DEFAULT_TRIMMING_STRATEGY` is the fallback when a
  `context_mode: session` process omits `trimming` entirely (defaults to
  `"none"` if `.env` doesn't set it either).
- **Trimming a session process is not free** -- rotation costs a real
  session boundary (a fresh `resume` cycle, with the associated
  `session_store` mirror round-trip when one is configured). Set
  `trimming`'s thresholds generously, not aggressively, to avoid
  unnecessary session churn.
- `trimming` is ignored (with a log line, not an error) on a
  `context_mode: "threaded"` process, same fail-open treatment as
  `session_store` above.

See `orchestration_accelerator.trimming` for the strategy dispatcher, and
`config/process_registry.yaml`'s `supportSession` process +
`examples/run_support_session.py` for a worked example (intake/diagnose
sharing one session, plus a cross-call resume demonstrating
`payload["session_id"]`).

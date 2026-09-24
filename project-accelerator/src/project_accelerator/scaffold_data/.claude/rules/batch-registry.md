# batch_registry.yaml schema

Batch-processing counterpart to `config/process_registry.yaml` (see
`.claude/rules/process-registry.md`). Structure:

```yaml
<batchName>:
  batch_id: <batchName>_01
  process: <processId>          # fk -> config/process_registry.yaml <process>.id (the id field, not the top-level key)
  step: <stepName>               # optional -- narrows to one step, same rule as execute()'s payload
  environment: local             # optional, same resolution as execute()
  poll_interval_seconds: 5
  poll_timeout_seconds: 86400    # default bumped from 3600 -- a real batch job can legitimately run up to 24h
  max_requests_per_batch: 10000  # optional, default 10000 (the provider's own per-batch item cap) --
                                  # submit_batch() chunks `items`/`inputs` into multiple
                                  # messages.batches.create() calls above this, one BatchHandle either way
  retry_failed_with_fallback: true  # optional, default true -- descriptive metadata; resubmit_failed()
                                     # can always be called regardless of this flag
  state_store:                   # optional, default omitted -> BatchStateStore backend "none"
    backend: file                # "none" (default) | "file" | "custom"
    path: .batch_state/handles.json  # only meaningful for backend: file
    # factory: "myproject.stores:build_batch_state_store"  # required for backend: custom
```

Rules:

- `process` references a process by its `id` field (e.g.
  `ticketClassification_01`), not by the process's top-level key
  (`ticketClassification`) -- resolved via
  `orchestration_accelerator.registry.get_process_by_id()`.
- `step` is optional only when the referenced process has exactly one
  step; a multi-step process requires `step` to pick which one runs
  across the batch. It can never reorder or subset a process's `steps`
  list beyond that one selection, same rule as `config/process_registry.yaml`.
- **Why `step` lives here instead of in `execute_batch()`'s payload
  (deliberate, reviewed design choice):** `execute()`'s payload carries
  `step` because each call is one-shot and self-contained. A
  `batch_registry.yaml` entry is different -- `poll_interval_seconds`/
  `poll_timeout_seconds` are tuned for *that specific step's* expected
  latency (a slow step legitimately needs a longer timeout than a fast
  one). If `step` were a payload argument instead, one entry's poll
  timeout could silently apply to whichever step a caller passes at
  runtime -- e.g. a `poll_timeout_seconds: 300` tuned for a fast
  `classify` step, called instead against a slow `respond` step, timing
  out before the batch actually finishes. Keeping `process` + `step` +
  `poll_*` together in one named entry makes each `batch_registry.yaml`
  block a complete, self-consistent job recipe -- not just a step
  reference -- so the poll timing can never drift out of sync with the
  step it was tuned for. `execute_batch()`'s payload intentionally stays
  `{batch_id, inputs, environment?}` -- no `step` override -- for this
  reason.
- Batches are `messages_api` only -- there is no agent_sdk batch surface,
  so a batch job always resolves auth via
  `auth_accelerator.build_api_credential(environment)`.
- Any step capability key from `config/process_registry.yaml` (aside from
  `prompt`/`model`/`fallback`/`system_prompt`) passes through into each
  batch request's `params`, same passthrough rule as the text path -- and
  is checked against `config/capability_registry.yaml`'s `messages_api`
  whitelist before submission, same as the text path (previously missing
  -- see A5-3 below).

## Split API: `submit_batch`/`get_batch_status`/`collect_batch`/`cancel_batch`/`resubmit_failed`

`orchestration_accelerator.batch` exposes five functions instead of one
blocking `execute_batch()` call, so a batch job's lifetime is no longer
tied to one process staying alive for the whole poll duration:

- **`submit_batch(payload)`** -- `payload` is
  `{batch_id, items|inputs, correlation?, environment?}` (`items`: list of
  `{custom_id, input, attachments?}`; legacy `inputs`: bare list,
  `custom_id` auto-generated as `f"{batch_id}-{i}"` -- exactly one of the
  two). Renders every item via the same `PromptManager` the text path
  uses, submits one (or more, chunked by `max_requests_per_batch`) real
  `messages.batches.create(...)` call(s), and **returns immediately** --
  no polling inside this call. Returns a JSON-serializable **BatchHandle**:
  `{handle_version, batch_job, provider_batch_ids, process_id, step,
  model, fallback_remaining, prompt_file, prompt_version, environment,
  custom_ids, correlation, submitted_at, expires_at}`. The caller
  persists this (directly, or via the entry's `state_store`) and passes
  it to the other four functions later, even from a different process --
  this is what makes a batch survive a process restart or timeout
  without losing a paid job (previously the provider's own batch id was
  used internally but never returned -- see A5-1 below).
- **`get_batch_status(handle)`** -- one non-blocking `batches.retrieve(...)`
  call per `provider_batch_id` in the handle. Returns
  `{batch_job, provider_batch_ids, statuses, all_ended}`.
- **`collect_batch(handle) -> BatchResult`** -- idempotent (safe to call
  more than once; always retrieves fresh). Reads full `usage`/`model`/
  `stop_reason` per item (previously only `content[0].text` was read --
  see A5-2 below), joining **every** `type == "text"` content block
  (not just index 0 -- required when `thinking` is enabled, since block 0
  is then a thinking block and the answer lands in a later text block).
  Returns `{batch_job, provider_batch_ids, status, totals, results}` --
  `totals` sums `input_tokens`/`output_tokens`/`cache_creation_tokens`/
  `cache_read_tokens` plus `succeeded`/`errored`/`expired`/`canceled`
  counts across every item, for metering. Each `results[i]` is
  `{custom_id, status, output, raw_output, model_used, stop_reason,
  request_id, usage, error}`.
- **`cancel_batch(handle)`** -- cancels every `provider_batch_id` in the
  handle. Returns `{batch_job, provider_batch_ids, canceled: [bool, ...]}`.
- **`resubmit_failed(handle, batch_result)`** -- re-submits only the items
  whose `collect_batch()` result was `"errored"`, against the next model
  in `handle["fallback_remaining"]`. Returns a new BatchHandle for the
  retry, or `None` if nothing errored or no fallback model remains.
  **Requires the original in-process `submit_batch()`/prior
  `resubmit_failed()` handle object** (its in-memory item inputs are
  never persisted) -- a handle round-tripped through a `BatchStateStore`/
  JSON loses this and raises `BatchJobError`; re-call `submit_batch()`
  with just the failed items' original inputs in that case instead.
- **`execute_batch(payload)`** stays as a thin backward-compatible
  wrapper: `submit_batch()` -> poll (`poll_interval_seconds`/
  `poll_timeout_seconds` from the registry entry) -> `collect_batch()`,
  returning the pre-split `{"batch_id": ..., "results": [{"input",
  "output", "error"}, ...]}` shape unchanged. Existing callers are
  unaffected; new code should prefer the split functions for
  resumability.

## `state_store` -- BatchStateStore, the batch counterpart to `session_store`

Mirrors `.claude/rules/context-mode.md`'s `session_store` pattern exactly:
`backend: "none"` (default, including when `state_store` is omitted
entirely) means the caller persists the BatchHandle dict themselves --
this accelerator does nothing extra. `backend: "file"` is a JSON-on-disk
store at `path` (default `.batch_state/handles.json`), mostly useful for
local dev/single-host setups (no file locking, not safe for concurrent
writers). `backend: "custom"` + `factory: "dotted.module.path:callable_name"`
imports and calls that zero-arg callable for a `BatchStateStore`-conforming
object (`save`/`load`/`mark_collected`/`list_open`) -- the escape hatch
for a project-authored durable, cross-host adapter (e.g. a MySQL table),
same shape as `session_store`'s `custom` backend. Selecting an
unrecognized backend, or `custom` with a missing/invalid `factory`,
raises `BatchStateStoreResolutionError` immediately, not a bare
`ImportError`.

## A5 fixes this split addresses

- **A5-1** (provider batch id never exposed, so a restart/timeout loses a
  paid batch): fixed by `submit_batch()` returning the id(s) in a
  BatchHandle immediately, with no polling in that call.
- **A5-2** (no usage/model/stop_reason; output read from `content[0].text`,
  wrong with `thinking`): fixed by `collect_batch()` reading full
  usage/model/stop_reason and joining every text block.
- **A5-3** (batch path skipped `validate_capabilities()`,
  `prompt_guardrails_path`, and all logging; no chunking; failed items
  never retried): `validate_capabilities()` and `prompt_guardrails_path`
  are now wired into `submit_batch()`'s prompt rendering, exactly as the
  text path does; `max_requests_per_batch` adds real chunking;
  `resubmit_failed()` adds per-item retry against the fallback chain.

See `config/batch_registry.yaml` (repo root) for the worked
`ticketClassificationBatch` example, wired to the `ticketClassification`
process's `classify` step, plus `ticketClassificationBatchStaging` /
`ticketClassificationBatchProd` showing the same job pointed at
`staging`/`prod` -- only `environment` changes, since `process`/`step`
selection is independent of which environment resolves the credential.
Because batches are `messages_api` only, every `environment` value
(`local` included) needs `ANTHROPIC_API_KEY` -- the `local`/`dev`
ambient-OAuth path `resolve_auth()` offers is agent_sdk-only and gets
rejected by `build_api_credential()`.

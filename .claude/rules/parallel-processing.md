---
description: Schema guidance for parallel_processing (process_registry.yaml)
paths:
  - "**/config/process_registry.yaml"
---

# `parallel_processing` schema (`process_registry.yaml`)

A new top-level process key, alongside `id`/`description`/`steps`:

```yaml
parallelAnalysisDemo:
  id: parallelAnalysisDemo_01
  description: ...
  parallel_processing: true      # optional, default false
  steps: [branchA, branchB, synthesis_step]
  branchA: {prompt: ..., model: ..., fallback: [...]}
  branchB: {prompt: ..., model: ..., fallback: [...]}
  synthesis_step:                 # name MUST be "synthesis_step" or "reconcile_step"
    prompt: ...                   # sees {{branchA_output}}, {{branchB_output}}
    model: ...
    fallback: [...]
```

`parallel_processing: false`/omitted = today's fully sequential behavior,
byte-for-byte unchanged. `parallel_processing: true` runs every step in
`steps` **except the last** concurrently, then runs the last step (once
every other step has resolved) as a mandatory reconciliation step.

There is no `parallel_steps` subset key -- the split is always "everything
but the last step runs in parallel," nothing more configurable than that.

## Validation (at registry-load time, in `get_process()`)

- `parallel_processing` must be a bool if present.
- When `true`, `steps` must have at least 2 entries, and the **last**
  entry must be literally named `synthesis_step` or `reconcile_step` --
  otherwise `MissingSynthesisStepError` is raised immediately, naming the
  process, the actual last-step name found, and the two accepted names.
  This is caught at load time, not discovered later as a step silently
  running with no reconciliation.

## Execution semantics

- All steps but the last launch concurrently via `asyncio.gather()`. Each
  branch receives the **same original payload `input`** -- no branch can
  see another branch's output, since none has run yet (same rule as "the
  first step of a sequential process has no `<stepName>_output`
  available").
- Once every branch resolves, the synthesis step runs through the exact
  same `{{<stepName>_output}}` templating threaded-mode steps already
  use (see `.claude/rules/process-registry.md`) -- `results` now holds
  every branch's output under `<stepName>_output`, so a synthesis
  prompt referencing `{{branchA_output}}`/`{{branchB_output}}` works with
  zero new templating code.
- `execute()`'s payload `step` narrowing still works exactly as before --
  narrowing to any single step (including the synthesis step itself)
  collapses back to the normal single-step call path, since there is
  nothing to parallelize with only one step selected.
- **Backend scope: both `agent_sdk` and `messages_api`.** Concurrent
  branches map to concurrent `query()` calls (agent_sdk) or concurrent
  `messages.create()` calls (messages_api) via `asyncio.gather()` --
  neither call is inherently stateful, so no backend restriction is
  needed for the threaded (default `context_mode`) case.
- **`context_mode: session` + `parallel_processing: true` is allowed**,
  unlike a single shared `ClaudeSDKClient` (which cannot safely serve
  concurrent turns) -- each parallel branch instead opens and closes its
  **own** `ClaudeSDKClient` for its one turn, run concurrently with the
  other branches' own clients. The synthesis step then runs on its own
  fresh client the same way. This combination is `agent_sdk`-only (same
  restriction `context_mode: session` already has on its own) --
  `parallel_processing: true` + `context_mode: session` +
  `backend: messages_api` raises `UnsupportedCapabilityError` before any
  model call, naming the unsupported combination.
- A `stream: true` parallel branch still invokes the caller's
  `on_chunk(step_name, chunk)` per delta -- since branches run
  concurrently, chunks from different branches can interleave in
  arrival order; `on_chunk` already receives `step_name`, so a caller can
  disambiguate which branch a given chunk belongs to.

See `config/process_registry.yaml`'s `parallelAnalysisDemo` process
(`parallel_sentiment` + `parallel_risk` branches, `synthesis_step`
reconciling both) and `examples/run_parallel_processing.py` for a worked
example.

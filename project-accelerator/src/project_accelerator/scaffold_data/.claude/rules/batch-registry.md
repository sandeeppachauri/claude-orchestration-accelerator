# batch_registry.yaml schema

Batch-processing counterpart to `process_registry.yaml` (see
`.claude/rules/process-registry.md`). Structure:

```yaml
<batchName>:
  batch_id: <batchName>_01
  process: <processId>          # fk -> process_registry.yaml <process>.id (the id field, not the top-level key)
  step: <stepName>               # optional -- narrows to one step, same rule as execute()'s payload
  environment: local             # optional, same resolution as execute()
  poll_interval_seconds: 5
  poll_timeout_seconds: 3600
```

Rules:

- `process` references a process by its `id` field (e.g.
  `ticketClassification_01`), not by the process's top-level key
  (`ticketClassification`) -- resolved via
  `orchestration_accelerator.registry.get_process_by_id()`.
- `step` is optional only when the referenced process has exactly one
  step; a multi-step process requires `step` to pick which one runs
  across the batch. It can never reorder or subset a process's `steps`
  list beyond that one selection, same rule as `process_registry.yaml`.
- Batch processing submits every item in `execute_batch()`'s
  `payload["inputs"]` as a single Anthropic Message Batches API job
  (`messages.batches.create`), polls `poll_interval_seconds` apart until
  `processing_status == "ended"` or `poll_timeout_seconds` elapses, then
  retrieves and validates results per item. This is real batch
  submission, not a loop over `execute()`.
- Batches are `messages_api` only -- there is no agent_sdk batch surface,
  so a batch job always resolves auth via
  `auth_accelerator.build_api_credential(environment)`.
- If the whole batch submission fails for one model, it is resubmitted
  once per entry in the step's `fallback` chain (from
  `process_registry.yaml`) -- there is no per-item fallback mid-flight.
- Any step capability key from `process_registry.yaml` (aside from
  `prompt`/`model`/`fallback`/`system_prompt`) passes through into each
  batch request's `params`, same passthrough rule as the text path.

See `batch_registry.yaml` (repo root) for the worked
`ticketClassificationBatch` example, wired to the `ticketClassification`
process's `classify` step, plus `ticketClassificationBatchStaging` /
`ticketClassificationBatchProd` showing the same job pointed at
`staging`/`prod` -- only `environment` changes, since `process`/`step`
selection is independent of which environment resolves the credential.
Because batches are `messages_api` only, every `environment` value
(`local` included) needs `ANTHROPIC_API_KEY` -- the `local`/`dev`
ambient-OAuth path `resolve_auth()` offers is agent_sdk-only and gets
rejected by `build_api_credential()`.

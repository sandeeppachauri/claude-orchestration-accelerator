# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Fixed (0.1.1)

- `FileManager.upload()`/`retrieve()` called anthropic's pre-GA
  `files.create`/`files.retrieve` methods, which don't exist on installed
  anthropic 1.8.0 GA (Files API moved from beta to
  `client.files.{upload,retrieve_metadata,list,delete,download}`).
  `upload()` also passed a `purpose` kwarg the real GA `files.upload()`
  signature doesn't accept at all -- would have raised `TypeError` even
  after a straight method rename. Fixed both; `retrieve()` kept as a
  deprecated alias for the new `retrieve_metadata()`.
- Pinned `anthropic>=1.8,<2` (was unbounded `>=0.40.0`) in the root and
  `model-router` `pyproject.toml`, and in the `--docker-project`
  Dockerfile generator's previously-unpinned install line. Pinned
  `claude-agent-sdk>=0.2.140,<0.3` (was unbounded `>=0.1.0`) the same way.
- `tests/test_file_manager.py`/`project-accelerator/tests/test_files.py`
  now autospec against the real `anthropic.resources.files.Files` class
  instead of a hand-rolled `FakeClient`/`FakeFiles` fake -- a future
  method rename/signature change now fails the test instead of silently
  passing.

### Added (0.2.0)

- **`attachments`** -- a new optional payload key on `execute()` and a
  `submit_batch()` item, letting a call attach file/image/text content to
  a model turn as real content blocks (not just a `file_id` string pasted
  into text, which the model can't act on). See
  `.claude/rules/attachments.md`. Deliberately a payload key, not a
  `process_registry.yaml` capability, since it varies per call and must
  bypass `validate_capabilities()`'s per-step whitelist. `messages_api`
  supports `file_id`/`path`(auto-uploaded)/`text` as document/image
  blocks; `agent_sdk` has no Files API, so `path`/`text` are inlined as
  extra text via `query()`'s streaming-input form and `file_id` raises a
  friendly `AttachmentError`. No attachments -> byte-identical request to
  before this change (regression-tested on both backends).
- **Split batch API** -- `submit_batch()`/`get_batch_status()`/
  `collect_batch()`/`cancel_batch()`/`resubmit_failed()` replace the old
  single blocking `execute_batch()` call (kept as a thin backward-
  compatible wrapper over the new functions). `submit_batch()` returns a
  JSON-serializable `BatchHandle` immediately -- no polling inside the
  call -- so a batch job survives a process restart or timeout instead of
  silently losing the provider's batch id. `collect_batch()` is
  idempotent and now reads full `usage`/`model`/`stop_reason` per item
  (previously only `content[0].text` was read, which silently returned
  the wrong/no text when `thinking` was enabled). New optional
  `batch_registry.yaml` keys: `max_requests_per_batch` (chunks large
  batches into multiple provider jobs under one handle),
  `retry_failed_with_fallback`, `state_store` (a `BatchStateStore`
  protocol mirroring `context-mode.md`'s `session_store` pattern --
  `none`/`file`/`custom` backends). `submit_batch()` now also runs
  `validate_capabilities()` and resolves `prompt_guardrails_path`, which
  the batch path previously skipped entirely. See
  `.claude/rules/batch-registry.md`.
- `project_accelerator` now exports `submit_batch`/`get_batch_status`/
  `collect_batch`/`cancel_batch`/`resubmit_failed` alongside the existing
  `execute_batch`/`upload_file`/`execute`.

### Breaking

- `execute()`'s return shape changed. Each step's value in the returned
  `{step_name: ...}` dict was a bare string (the validated model output);
  it is now a dict:

  ```python
  {
      "output": "<validated text, same value the old bare string was>",
      "model_used": "claude-haiku-4-5-20251001",
      "stop_reason": "end_turn",
      "usage": {"input_tokens": ..., "output_tokens": ..., "cache_creation_tokens": ..., "cache_read_tokens": ...},
      "tool_calls": [{"name": "...", "count": ...}],  # agent_sdk only; [] on messages_api
      "request_id": "...",                             # messages_api only; None on agent_sdk
      "latency_ms": ...,
  }
  ```

  **Migration**: anywhere reading `results[step_name]` as text, change it
  to `results[step_name]["output"]`. No information was removed, only
  relocated -- the new fields (`model_used`, `stop_reason`, `usage`,
  `tool_calls`, `request_id`, `latency_ms`) are additive.

  If you scaffolded a project with `cpa new` before this change, re-run
  `cpa new` (or manually re-pull `scaffold_data/`) to pick up the updated
  example scripts and `test_sample_pipeline.py`, and update any of your
  own code that reads `execute()`'s return value.

### Added

- `model-router`'s `call_agent_sdk()`/`call_messages_api()` now capture
  and return token usage, stop reason, serving model, request id, and
  latency for every model call.
- Fallback-chain transitions (falling back from one model to the next)
  are now logged at `Scope.WARNING`, not just the final serving model.
- New `cpa new --docker-project yes|no` (default `no`) flag: generates
  `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and a FastAPI
  wrapper (`examples/api_server.py` -- `GET /health` + `POST /classify`)
  so a scaffolded project can be built into an image and deployed/tested
  in a container. Works independently of `--sample-needed`. The
  generated `docs/HOWTO.md` gains a matching "Docker deployment" section
  with request examples. This repo's own root now ships the same
  `Dockerfile`/`docker-compose.yml`/`.dockerignore`/`examples/api_server.py`
  as a live reference, wired to the existing `ticketClassification`
  process.

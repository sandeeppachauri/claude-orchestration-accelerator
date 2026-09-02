# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

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

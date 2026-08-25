---
description: Schema guidance for capability_registry.yaml
paths:
  - "**/config/capability_registry.yaml"
---

# capability_registry.yaml schema

Whitelist of `config/process_registry.yaml` step capability keys (see
`.claude/rules/process-registry.md`'s "capability passthrough" rule),
per backend. Structure:

```yaml
agent_sdk:
  allowed: [max_turns, thinking, max_thinking_tokens, effort, permission_mode, fallback_model]
messages_api:
  allowed: [temperature, top_p, max_tokens, thinking, stop_sequences]
```

Rules:

- A step's capability keys (every key besides
  `prompt`/`model`/`fallback`/`system_prompt`) are validated against this
  file's `allowed` list for the payload's `backend` before the model
  call happens, via
  `orchestration_accelerator.registry.validate_capabilities()`. A key not
  in the matching backend's `allowed` list raises
  `UnsupportedCapabilityError` immediately -- naming the exact bad
  key(s) and backend -- instead of a `TypeError` raised several layers
  deep inside `claude_agent_sdk`/`anthropic` once the call actually
  reaches the SDK.
- The two backends' allowed sets are **disjoint, not a shared
  superset** -- `agent_sdk` (`claude_agent_sdk.ClaudeAgentOptions`) has
  no `temperature`/`top_p`/`max_tokens` fields at all, and
  `messages_api` (`anthropic.Client.messages.create()`) has no
  `permission_mode`/`max_turns` concept. A step meant to run on both
  backends needs two different capability blocks (or two different
  process entries), not one block unioning both key sets.
- This file is deliberately **not** environment-specific, unlike
  `.env` -- the same keys must be valid on every environment a given
  backend runs in, so it lives at the same tier as
  `config/process_registry.yaml`, not `.env`. Putting an allowlist in `.env`
  would let one environment silently accept a key another rejects.
- To add a new capability once its backend actually supports it (e.g. a
  `claude-agent-sdk`/`anthropic` SDK bump adds a new
  `ClaudeAgentOptions` field or Messages API param), add its key to the
  matching backend's `allowed` list here -- no accelerator code change
  required. Deliberately curated, not auto-derived from the SDK's full
  field list: several `ClaudeAgentOptions` fields (`cli_path`, `env`,
  `hooks`, `resume`, `session_id`, `can_use_tool`, ...) are
  internal/session-management concerns, not per-step model-call tuning,
  and must stay off the whitelist even though the SDK technically
  accepts them.
- A missing backend section (or a backend absent from this file
  entirely) resolves to an empty allowed set -- any capability key set
  against that backend fails validation, rather than being silently
  permitted.

See `config/capability_registry.yaml` (repo root) for the shipped defaults, and
`config/process_registry.yaml`'s `templatingDemo.escalate` step for a worked
example of a step whose live capability keys are agent_sdk-only
(matching the backend `examples/sample_usage.py` actually calls it
with), with the messages_api-only equivalents left as a comment.

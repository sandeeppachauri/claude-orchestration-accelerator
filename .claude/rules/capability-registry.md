---
description: Schema guidance for capability_registry.yaml
paths:
  - "**/config/capability_registry.yaml"
---

# capability_registry.yaml schema

Whitelist of `config/process_registry.yaml` step capability keys (see
`.claude/rules/process-registry.md`'s "capability passthrough" rule),
per backend. Structure:

`mcp_servers`/`allowed_tools`/`guardrails`/`skills` are also whitelisted
here but documented in full in `.claude/rules/mcp-scope.md` (the first
three) and `.claude/rules/guardrails-registry.md` (`guardrails`) --
`mcp_servers`/`allowed_tools`/`guardrails` are popped off and consumed as
hooks rather than forwarded to `ClaudeAgentOptions`/`messages.create()`
directly; only `skills` is a real passthrough field on both backends.

`tools`/`disallowed_tools` are real `ClaudeAgentOptions` fields, distinct
from `allowed_tools` above: `allowed_tools`/`mcp_servers` only ever
narrow *MCP* tool access (non-MCP tool names always pass through them
untouched -- see `.claude/rules/mcp-scope.md`), while `tools`/
`disallowed_tools` control the model's whole built-in toolset
(Read/Write/Edit/Bash/...). A step that should never need a tool (e.g.
"read this input, answer JSON") should set `tools: []` -- otherwise the
model can spend its entire `max_turns` budget on tool-call round-trips
instead of ever emitting a final text turn, leaving `raw_output` empty.

```yaml
agent_sdk:
  allowed: [max_turns, thinking, max_thinking_tokens, effort, permission_mode, fallback_model, tools, disallowed_tools, mcp_servers, allowed_tools, guardrails, skills, resume, session_id, stream]
messages_api:
  allowed: [temperature, top_p, max_tokens, thinking, stop_sequences, skills, cache_control, stream]
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
  `hooks`, `can_use_tool`, ...) are internal/session-management
  concerns, not per-step model-call tuning, and must stay off the
  whitelist even though the SDK technically accepts them. `resume`/
  `session_id` **are** whitelisted (agent_sdk-only) -- see
  `.claude/rules/context-mode.md` -- because `context_mode: session`
  processes construct `ClaudeAgentOptions` with `resume=<session_id>`
  for cross-call continuation; they're meaningless outside that mode.
  `stream` is whitelisted on **both** backends -- see
  `.claude/rules/streaming.md` -- it maps to
  `ClaudeAgentOptions.include_partial_messages` on agent_sdk and
  `client.messages.stream(...)` on messages_api; either way it emits
  chunks to `execute()`'s payload `on_chunk` callback as they arrive.
- A missing backend section (or a backend absent from this file
  entirely) resolves to an empty allowed set -- any capability key set
  against that backend fails validation, rather than being silently
  permitted.
- `cache_control` (Anthropic prompt caching) is deliberately
  **messages_api-only** -- the Messages API exposes explicit,
  controllable cache breakpoints (`{"type": "ephemeral", "ttl": "5m"}`),
  while the agent_sdk backend only does automatic, opaque system-prompt
  caching with no field to set and no TTL control. Setting `cache_control`
  on an agent_sdk-backed step fails whitelist validation immediately
  (`UnsupportedCapabilityError`) rather than silently no-opping. This
  registry entry only gates *whether* a step may set `cache_control` at
  all -- the concrete `type`/`ttl` value is process-specific and lives in
  `config/process_registry.yaml`'s step block (same tier as
  `model`/`fallback`), not here. See `config/process_registry.yaml`'s
  `templatingDemo.triage` step for the commented-out worked example, and
  `call_messages_api()` in `model-router/src/model_router_accelerator/backends.py`
  for how the value is applied to the system-prompt content block.

See `config/capability_registry.yaml` (repo root) for the shipped defaults, and
`config/process_registry.yaml`'s `templatingDemo.escalate` step for a worked
example of a step whose live capability keys are agent_sdk-only
(matching the backend `examples/sample_usage.py` actually calls it
with), with the messages_api-only equivalents left as a comment.

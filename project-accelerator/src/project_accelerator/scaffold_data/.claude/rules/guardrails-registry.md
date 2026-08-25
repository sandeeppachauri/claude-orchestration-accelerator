---
description: Schema guidance for config/guardrails.yaml and the guardrails step key
paths:
  - "**/config/guardrails.yaml"
---

# `config/guardrails.yaml` schema and the `guardrails` step key

General-purpose enforcement -- redaction, rate-limiting, forced
validation, etc. -- with nothing to do with MCP access. For MCP
server/tool scoping (`mcp_servers`/`allowed_tools`) or the `skills` step
key, see `.claude/rules/mcp-scope.md` instead -- a separate, independent
mechanism.

Guardrail *logic* (the mechanism) is project-level Python code in
`orchestration_accelerator/guardrails.py`; guardrail *parameters*
(thresholds, patterns) are config in `config/guardrails.yaml`, so a user
tunes behavior without touching code.

## `config/guardrails.yaml`

```yaml
<guardrailName>:
  type: <registered type name>
  params:
    <type-specific tuning keys>
```

```yaml
redactPII:
  type: redaction
  params:
    patterns: ["\\b\\d{3}-\\d{2}-\\d{4}\\b"]   # SSN-shaped strings
```

Built-in types (`orchestration_accelerator.guardrails.GUARDRAIL_TYPES`):

- `redaction` -- `params: {patterns: [<regex>, ...]}`. Denies the tool
  call if any pattern matches the tool input.
- `rate_limit` -- `params: {max_calls: <int>, window_seconds: <float>}`.
  Denies the tool call once `max_calls` have been made within the
  trailing `window_seconds`.

A project registers its own type via
`orchestration_accelerator.guardrails.register_guardrail_type(name, factory)`
-- `factory` takes that entry's `params` dict and returns a
`PreToolUse`-hook-shaped callable
(`async (input_data, tool_use_id, context) -> dict`).

## `guardrails` step key

```yaml
escalate:
  prompt: escalation_decision.yaml
  model: claude-sonnet-5
  fallback: [claude-sonnet-4-6]
  guardrails: [redactPII]   # names, resolved against config/guardrails.yaml
```

- Names are resolved via `orchestration_accelerator.guardrails.get_guardrail()`
  against `config/guardrails.yaml`. An unknown name, or an entry whose
  `type` isn't in `GUARDRAIL_TYPES`, raises `UnknownGuardrailError` naming
  the step and bad name.
- Omitted step key, or an absent `config/guardrails.yaml` file entirely,
  means no guardrails -- **fail-open**, same posture as
  `mcp_servers`/`allowed_tools`.
- Enforced the same way MCP scoping is: `call_agent_sdk()`
  (`model-router/src/model_router_accelerator/backends.py`) attaches each
  named guardrail as its own `PreToolUse` hook, coexisting with the MCP
  scope hook and `ClaudeSDKLoggerAccelerator`'s tracing hooks -- all three
  hook sources merge into one `ClaudeAgentOptions.hooks` dict, none
  overriding another.
- `guardrails` is whitelisted only in `config/capability_registry.yaml`'s
  `agent_sdk.allowed` list -- the mechanism attaches via
  `ClaudeAgentOptions.hooks`, an `agent_sdk`-only concept, so a
  `messages_api` step setting `guardrails` fails capability validation
  immediately rather than silently doing nothing.

See `config/guardrails.yaml` (repo root) for the shipped `redactPII`
example, and `config/process_registry.yaml`'s `templatingDemo.escalate`
step for the commented-out worked example.

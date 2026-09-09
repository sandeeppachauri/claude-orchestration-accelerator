---
description: Schema guidance for config/prompt_guardrails.yaml and the prompt_guardrails prompt-YAML field
paths:
  - "**/config/prompt_guardrails.yaml"
---

# `config/prompt_guardrails.yaml` schema and the `prompt_guardrails` prompt-YAML field

**Prompt-content policy only** -- reusable, named dos/don'ts text
composed into a prompt's rendered `system_prompt`, e.g. "only discuss
insurance types we currently offer," "never mention a competitor," "no
speculation about future products." This is composed prompt text handed
to the model, not enforcement code -- the model can still ignore it, the
same as any other instruction in a system prompt.

This is a **different, independent mechanism** from
`config/guardrails.yaml` (see `.claude/rules/guardrails-registry.md`) --
that one is tool-call enforcement, attached as a `PreToolUse` hook,
which denies/allows individual tool calls and never touches prompt
text. `prompt_guardrails` never touches tool calls. Do not confuse the
two: a step can use either, both, or neither.

## `config/prompt_guardrails.yaml`

```yaml
<guardrailName>:
  in_bounds:
    - "Only provide information about insurance types we currently offer"
  out_of_bounds:
    - "Do not speculate about future product offerings or company plans"
    - "Do not make promises or enter into agreements you're not authorized to make"
    - "Do not mention any competitor's products or services"
```

Plain list-of-strings under `in_bounds`/`out_of_bounds` -- the same
shape a prompt YAML's own `scope` field already uses (see
`.claude/rules/process-registry.md`), for consistency. No `type`/`params`
typing like `config/guardrails.yaml`'s `redaction`/`rate_limit` --
there's no pluggable enforcement logic here, just named text to look up
and format.

## `prompt_guardrails` field (in a `prompts/*.yaml` file)

```yaml
# prompts/support_reply.yaml
step: support_reply
version: 1
scope: ...
format: ...
constraints: ...
prompt_guardrails: [insuranceSupportPolicy]   # NEW, optional -- names resolved against config/prompt_guardrails.yaml
system_prompt: |
  You are a support agent for an insurance company. ...
user_prompt: |
  Customer message:
  {{customer_message}}
```

- Lives in the **prompt YAML file**, not `process_registry.yaml` -- same
  tier as `system_prompt`/`user_prompt`/`assistant_prompt`, so
  prompt-authoring stays self-contained per prompt file. (Compare to
  `config/guardrails.yaml`'s `guardrails:` key, which lives on a
  `process_registry.yaml` step instead -- a deliberate difference, since
  that mechanism is about model-call/tool-call plumbing, not prompt
  authoring.)
- Optional. Omitted, or an absent `config/prompt_guardrails.yaml` file
  entirely, means no composed policy text -- **fail-open**, zero
  behavior change for every existing prompt file, same posture as
  tool-call `guardrails`/MCP scoping.
- Names are resolved via
  `orchestration_accelerator.prompt_guardrails.get_prompt_guardrail()`.
  An unknown name raises `PromptValidationError` (reusing
  `PromptManager`'s existing error type) naming the step and the bad
  name, at prompt-load time -- not a silent no-op and not a new
  exception type to catch.
- Multiple names combine, in list order -- same list-composition style
  as `guardrails: [...]`/`mcp_servers: [...]` elsewhere in this repo.
- **Composition happens before `{{key}}` placeholder substitution.**
  `PromptManager.get()` loads each named guardrail, renders it (a
  `GUARDRAILS (<name>):` header plus its `in_bounds`/`out_of_bounds`
  bullet list), and appends the result onto `system_prompt` -- so a
  prompt with both `prompt_guardrails` and `{{key}}` placeholders in
  `system_prompt` works with no special-casing; the composed text is
  static and never itself contains a placeholder.
- **Backend scope: both `agent_sdk` and `messages_api`.** Unlike
  tool-call `guardrails` (which needs `ClaudeAgentOptions.hooks`, an
  `agent_sdk`-only concept), `prompt_guardrails` only ever changes plain
  `system_prompt` text -- a string field both backends already send.
  Nothing to whitelist in `config/capability_registry.yaml`; this isn't
  a capability-passthrough key at all, since it never reaches the model
  call as a distinct API parameter.

## How to add a prompt guardrail

1. Add (or extend) a named entry in `config/prompt_guardrails.yaml`,
   with `in_bounds`/`out_of_bounds` bullet lists describing the policy.
2. Reference it by name in the target prompt file's
   `prompt_guardrails: [<name>, ...]` list (`prompts/<step>.yaml`).
3. Verify: run `python examples/run_prompt_guardrails.py`, which prints
   the composed `system_prompt` before making any model call, or
   inspect `logs/trace.log`'s `MODEL_CALL_START` record for that step to
   confirm the policy text is present in the system prompt actually sent
   to the model.

See `config/prompt_guardrails.yaml` (repo root) for the shipped
`insuranceSupportPolicy` example, `prompts/support_reply.yaml` for the
worked prompt using it, `config/process_registry.yaml`'s
`templatingDemo.supportReply` step, and `examples/run_prompt_guardrails.py`
for a runnable end-to-end demo.

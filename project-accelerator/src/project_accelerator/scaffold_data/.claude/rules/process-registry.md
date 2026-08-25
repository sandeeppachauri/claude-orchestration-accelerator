---
description: Schema guidance for process_registry.yaml
paths:
  - "**/config/process_registry.yaml"
---

# process_registry.yaml schema

This file is the single source of truth for a process's step order and
per-step configuration. Structure:

```yaml
<processName>:
  id: <processName>_01
  description: <human readable description>
  steps: [<stepA>, <stepB>, ...]     # ordered — this is the ONLY place step order is controlled
  <stepA>:
    prompt: <file under prompts/>.yaml
    model: <model id>
    fallback: [<model id>, ...]      # ordered fallback chain, tried in order on rate-limit/overload
    max_turns: 1                     # optional -- any extra key below passes straight through
    thinking: {type: enabled, budget_tokens: 4096}   # optional, agent_sdk backend only
    temperature: 0.2                 # optional, messages_api backend only
  <stepB>:
    prompt: ...
    model: ...
    fallback: [...]
```

Rules:

- `id`, `description`, and `steps` are per-process metadata. Every other
  top-level key inside a process block must match a name in `steps`.
- `steps` may list any number of step names, in any order — nothing reads
  a fixed count or fixed names.
- A step's `prompt` can point at any file under `prompts/`, not
  necessarily one named after the step itself.
- `fallback` is an ordered list: the model router tries `model` first,
  then each `fallback` entry in order, on a rate-limit/overload error.
- Any step key besides `prompt`/`model`/`fallback`/`system_prompt` is a
  **capability passthrough** — `core.py` forwards it untouched to
  `execute_with_fallback(**capabilities)`, which forwards it to the
  chosen backend (`build_options(**extra)` for `agent_sdk`,
  `messages.create(**extra)` for `messages_api`). This is how you set
  `max_turns`, `thinking`/extended-thinking, `temperature`, `top_p`,
  `permission_mode`, etc. per step, entirely from this file — no
  accelerator code change needed. Every capability key is checked
  against `config/capability_registry.yaml`'s per-backend whitelist before the
  model call — a key not whitelisted for the step's backend raises
  `UnsupportedCapabilityError` immediately, not a `TypeError` several
  layers deep inside the SDK/API client. See
  `.claude/rules/capability-registry.md`.
- A caller's execution payload can select a process and, optionally, a
  single step to narrow to — it can never reorder, skip, or subset a
  process's `steps` list. If you want different step behavior, edit
  `steps` here.
- If a `(process, step)` pair isn't defined at all, the accelerator falls
  back to a built-in default: one model (from `.env`'s `DEFAULT_MODEL`)
  and one generic system prompt, with no fallback chain.

## Runtime input & `{{key}}` placeholders

A prompt file under `prompts/` (see `.claude/rules/prompt-yaml.md` if
present, or `prompt_manager.py`) has `system_prompt` and an optional
`user_prompt` field. Both are plain strings and may contain `{{key}}`
placeholders. `execute()`'s payload `input` then works one of two ways,
enforced by `PromptManager.render()` (mandatory, not optional):

- **No placeholders in the prompt** — `input` must be a plain string,
  sent verbatim as the user turn. `system_prompt` is used as-is. This is
  the legacy/simple path (e.g. `classify.yaml`).
- **Prompt has `{{key}}` placeholders** — `input` must be a dict of
  `{key: value}`. `user_prompt` becomes required in the prompt YAML (it
  is the user turn once templating is in play). Every placeholder in
  `system_prompt`/`user_prompt` must have a matching dict key, or
  `PromptValidationError` is raised immediately, so the config and the
  call site can never silently drift apart. Extra dict keys not
  referenced by this step's placeholders are allowed and ignored — a
  multi-step run without an explicit `step` shares one flat `input`
  dict across all steps, and different steps may need different
  subsets of it.

See `prompts/classify.yaml` (no placeholders), `prompts/ticket_triage.yaml`
(multiple placeholders, static prompt around them), and
`prompts/escalation_decision.yaml` (placeholders in both `system_prompt`
and `user_prompt`, paired with `templatingDemo.escalate` below for a full
capability-key reference) for worked examples, wired up under the
`templatingDemo` process in this file.

## Threading a prior step's output: `{{<stepName>_output}}`

Every step's raw result gets fed back into the step loop, and any step
that runs *after* it can pull it in as a placeholder named
`<stepName>_output` -- e.g. the `triage` step's result is exposed to
later steps as `{{triage_output}}`, `classify`'s as `{{classify_output}}`,
etc. This name is not declared anywhere in `<stepName>`'s own prompt YAML
-- it is generated mechanically by `core.py`'s step loop from that step's
key in `steps: [...]` (`f"{step_name}_output"`), so the convention to
remember is: **to consume step X's output, write `{{X_output}}`** in a
*later* step's prompt, matching X's exact name from `steps:` above.

- Only reaches a step that already takes the dict/placeholder input path
  (i.e. its prompt has at least one `{{key}}` somewhere) -- a step with a
  fully static prompt (no placeholders at all) still gets the legacy
  plain-string `input` untouched, per the rule above.
- If `input_data` itself is a dict (`templatingDemo`-style, multiple
  named fields), those original fields are preserved as-is and
  `<stepName>_output` keys are added alongside them -- a later step can
  reference both its own named fields and any prior step's output in the
  same prompt.
- First step in a process never has a `<stepName>_output` available (no
  prior step ran yet) -- only steps after it do.
- Declaring `{{<stepName>_output}}` in a prompt makes that placeholder
  **required** by `PromptManager.render()`'s strict-match check -- if you
  run that step standalone (`payload["step"]` narrowed to just that one
  step, no earlier step in the same call), you must supply
  `<stepName>_output` explicitly in `input` yourself, since no earlier
  step actually ran to produce it.

See `prompts/extract_v2.yaml` (`{{classify_output}}`),
`prompts/classify_soa.yaml` (`{{classify_output}}` + `{{extract_output}}`),
and `prompts/escalation_decision.yaml` (`{{triage_output}}`) for worked
examples of this convention.

---
description: Schema guidance for process_registry.yaml
paths:
  - "**/process_registry.yaml"
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
  accelerator code change needed. An unsupported key for the chosen
  backend/SDK version raises a `TypeError` at call time, not silently.
- A caller's execution payload can select a process and, optionally, a
  single step to narrow to — it can never reorder, skip, or subset a
  process's `steps` list. If you want different step behavior, edit
  `steps` here.
- If a `(process, step)` pair isn't defined at all, the accelerator falls
  back to a built-in default: one model (from `.env`'s `DEFAULT_MODEL`)
  and one generic system prompt, with no fallback chain.

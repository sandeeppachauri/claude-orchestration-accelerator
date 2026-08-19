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
- A caller's execution payload can select a process and, optionally, a
  single step to narrow to — it can never reorder, skip, or subset a
  process's `steps` list. If you want different step behavior, edit
  `steps` here.
- If a `(process, step)` pair isn't defined at all, the accelerator falls
  back to a built-in default: one model (from `.env`'s `DEFAULT_MODEL`)
  and one generic system prompt, with no fallback chain.

Add a new process to this project.

1. Ask the user for: process name, ordered step names, and per-step
   prompt/model/fallback (or invoke the `setup-accelerator` skill instead,
   which interviews for this and writes the files).
2. Add a `prompts/<step>.yaml` for each new step.
3. Add the process block to `process_registry.yaml` — steps list plus a
   `{prompt, model, fallback}` entry per step.
4. Run `pytest tests -q` to confirm nothing broke.

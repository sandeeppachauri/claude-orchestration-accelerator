---
name: setup-accelerator
description: >
  Stub for the Phase 2 guided setup skill. Once claude-project-accelerator
  exists (Phase 1), this skill will interview a user (project name, which
  process(es), target environment, model preferences), run `cpa new`, and
  write the resulting process_registry.yaml — a conversational wrapper
  around the CLI rather than a hand-editing workflow. Not yet implemented;
  superseded once Phase 2 ships (see Master_Accelerator_Plan.md Section 7).
---

# setup-accelerator (stub)

This is a minimal placeholder shipped with the reference Claude Code
skeleton ahead of Phase 2. It documents intent only — it does not yet
implement the guided interview described in the plan.

When Phase 2 lands, invoking this skill will:

1. Ask for the project name/location, which process(es) are needed (new vs.
   reusing a shipped sample like `ticketClassification`), the target
   environment (`local`/`dev`/`prod`), and any model preferences.
2. Run `cpa new --project-name <name>` (see `claude-project-accelerator`).
3. Edit the generated `process_registry.yaml` to match the interview
   answers.
4. Report back what was created and which `(process, step)` pairs are
   still running on the built-in default configuration.

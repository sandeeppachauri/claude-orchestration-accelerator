# Architecture

This project runs on the `claude-project-accelerator` stack:

1. `execute(payload)` (`project_accelerator`) resolves `environment`,
   looks up the `(process, step)` config from `process_registry.yaml`,
   calls the model via `claude-model-router-accelerator`'s ordered
   fallback chain, validates output against the prompt's format
   contract, and logs the turn.
2. `process_registry.yaml` is the single source of truth for step order
   and per-step `{prompt, model, fallback, ...capabilities}` config --
   see `.claude/rules/process-registry.md` for the schema and how extra
   keys (`max_turns`, `thinking`, `temperature`, ...) pass through to the
   model call untouched.
3. `prompts/*.yaml` holds the prompt templates the registry points at.
4. Auth resolution (`claude-auth-accelerator`) and tracing
   (`ClaudeSDKLoggerAccelerator`) are wired in automatically -- nothing
   to configure to get logging or credential resolution working.

See `HOWTO.md` for a file-by-file breakdown and `README.md` for the
quick-start commands.

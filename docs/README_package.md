# claude-orchestration-accelerator (package)

Prompt resolution + process registry for the master accelerator stack.

```bash
pip install -e .
```

## Sub-packages

- `orchestration_accelerator.prompting` — `PromptManager`, `PromptConfig`,
  `PromptValidationError`, `OutputContractError`. Loads versioned prompt
  YAML (scope/format/constraints) from a `prompts/` directory and
  enforces the output format contract in code.
- `orchestration_accelerator.registry` — loads `process_registry.yaml`,
  resolves `(process, step)` -> `{id, description, steps, step_config}`,
  and provides `get_default_step_config()` for the built-in default
  fallback (one model from `DEFAULT_MODEL`, one generic system prompt).
- `orchestration_accelerator.logging` — default logging wrapper. Ships
  `logger_config.json` (all 8 scopes enabled) and calls
  `sdk_logger_accelerator.configure()` automatically; `get_default_hooks()`
  returns a `ClaudeAgentOptions.hooks`-shaped dict wiring the pre/post
  tool-use hooks. Requires the `logging` extra
  (`pip install -e ".[logging]"`) since it depends on
  `ClaudeSDKLoggerAccelerator`, which lives in the sibling `Accelerators`
  repo (`pip install -e ../Accelerators/ClaudeSDKLoggerAccelerator`).
- `orchestration_accelerator.environment` — `.env`-backed environment
  resolution (`resolve_environment()`, `resolve_default_model()`),
  payload value -> `.env` -> hardcoded `"local"` fallback.

## process_registry.yaml

Ships at the package root with two sample processes,
`ticketClassification` and `onboarding` — see
`Master_Accelerator_Plan.md` Section 4.1 for the schema. This same file
is also the default `process_registry.yaml` copied into every project
scaffolded by `claude-project-accelerator`.

## Tests

```bash
pytest tests -q
```

#!/usr/bin/env bash
# PostToolUse hook: nudge to update docs/architecture.md/HOWTO.md/README.md
# whenever source config/code changes. Advisory only -- does not block.
# Reads the tool-call JSON payload from stdin (Claude Code hook contract):
# {"tool_name": "...", "tool_input": {"file_path": "..."}}
payload="$(cat)"
file_path="$(printf '%s' "$payload" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*:[[:space:]]*"(.*)"/\1/')"

case "$file_path" in
  *.py|*process_registry.yaml|*batch_registry.yaml|*prompts/*.yaml)
    echo "[doc-sync] '$file_path' changed -- review whether docs/architecture.md, HOWTO.md, or README.md need updating to match." >&2
    ;;
esac

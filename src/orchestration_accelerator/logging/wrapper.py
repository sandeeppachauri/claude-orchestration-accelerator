"""
wrapper.py

Default logging wrapper described in Master_Accelerator_Plan.md 4.1.
sdk_logger_accelerator itself requires a consumer to call configure({...})
and manually wire pre_tool_use_hook/post_tool_use_hook into
ClaudeAgentOptions.hooks. Since every orchestration-accelerator consumer
wants logging by default (not opt-in per project), this module:

  - ships a default logger_config.json with all 10 scopes enabled
  - calls sdk_logger_accelerator.configure() with it automatically
  - exposes get_default_hooks() to wire pre/post hooks into whatever
    ClaudeAgentOptions the caller builds
  - exposes log() as a thin wrapper over sdk_logger_accelerator.log_event()

This wrapper depends on ClaudeSDKLoggerAccelerator as a package -- no
tracing logic is duplicated here, only the wiring step is removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LOGGER_CONFIG_PATH = Path(__file__).resolve().parent / "logger_config.json"

with open(DEFAULT_LOGGER_CONFIG_PATH, "r") as _f:
    DEFAULT_LOGGER_CONFIG: dict[str, Any] = json.load(_f)

_configured = False


def configure_default_logging(config: dict[str, Any] | None = None) -> None:
    """Calls sdk_logger_accelerator.configure() with the default config
    (or an override), once per process. Safe to call repeatedly."""
    global _configured
    import sdk_logger_accelerator as logger

    logger.configure(config or DEFAULT_LOGGER_CONFIG)
    _configured = True


def get_default_hooks() -> dict[str, list[dict[str, Any]]]:
    """Returns a ClaudeAgentOptions.hooks-shaped dict wiring
    sdk_logger_accelerator's pre/post tool-use hooks, per its own
    documented HookMatcher shape. Ensures configure_default_logging() has
    run first."""
    if not _configured:
        configure_default_logging()
    import sdk_logger_accelerator as logger

    return {
        "PreToolUse": [{"hooks": [logger.pre_tool_use_hook]}],
        "PostToolUse": [{"hooks": [logger.post_tool_use_hook]}],
    }


async def log(scope: str, session_id: str, turn_index: int = 0, **fields: Any) -> None:
    """Thin wrapper over sdk_logger_accelerator.log_event(), ensuring
    configure_default_logging() has run first."""
    if not _configured:
        configure_default_logging()
    import sdk_logger_accelerator as logger

    await logger.log_event(logger.Scope(scope), session_id, turn_index, **fields)

"""
prompt_guardrails.py

Reusable, named prompt-content policy blocks -- dos/don'ts composed into
a prompt's system_prompt text (e.g. "only discuss offerings we actually
sell", "never mention a competitor"). Unrelated to guardrails.py's
tool-call enforcement (PreToolUse hooks, redaction/rate-limit) -- that
mechanism never touches prompt text, this one never touches tool calls.
See .claude/rules/prompt-guardrails.md.

Parameters (config/prompt_guardrails.yaml) are plain data, not pluggable
types like guardrails.py's GUARDRAIL_TYPES -- there is no enforcement
logic to register, just named text blocks to look up and format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROMPT_GUARDRAILS_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "prompt_guardrails.yaml"
)


class UnknownPromptGuardrailError(Exception):
    """Raised when a prompt YAML's `prompt_guardrails` list names an entry
    not defined in config/prompt_guardrails.yaml."""


@dataclass(frozen=True)
class PromptGuardrail:
    name: str
    in_bounds: list[str] = field(default_factory=list)
    out_of_bounds: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Formats this policy block for appending to a system_prompt,
        mirroring PromptConfig.describe()'s in_bounds:/out_of_bounds:
        style."""
        lines = [f"GUARDRAILS ({self.name}):"]
        for item in self.in_bounds:
            lines.append(f"- {item}")
        for item in self.out_of_bounds:
            lines.append(f"- {item}")
        return "\n".join(lines)


def load_prompt_guardrails(path: Path | str | None = None) -> dict[str, PromptGuardrail]:
    """Reads config/prompt_guardrails.yaml into a name -> PromptGuardrail
    map. Missing file -> empty map (fail-open, same posture as
    guardrails.load_guardrails())."""
    resolved_path = Path(path) if path is not None else DEFAULT_PROMPT_GUARDRAILS_CONFIG_PATH
    if not resolved_path.exists():
        return {}
    with open(resolved_path, "r") as f:
        config: dict[str, Any] = yaml.safe_load(f) or {}

    guardrails: dict[str, PromptGuardrail] = {}
    for name, entry in config.items():
        entry = entry or {}
        guardrails[name] = PromptGuardrail(
            name=name,
            in_bounds=entry.get("in_bounds", []),
            out_of_bounds=entry.get("out_of_bounds", []),
        )
    return guardrails


def get_prompt_guardrail(name: str, path: Path | str | None = None) -> PromptGuardrail:
    """Raises UnknownPromptGuardrailError if `name` isn't defined in
    config/prompt_guardrails.yaml."""
    guardrails = load_prompt_guardrails(path)
    if name not in guardrails:
        resolved_path = Path(path) if path is not None else DEFAULT_PROMPT_GUARDRAILS_CONFIG_PATH
        raise UnknownPromptGuardrailError(
            f"No prompt guardrail named '{name}' defined in {resolved_path}. "
            f"Known prompt guardrails: {sorted(guardrails)}"
        )
    return guardrails[name]

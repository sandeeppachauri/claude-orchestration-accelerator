"""
prompt_manager.py

Promoted, near-as-is, from prompt-description-demo/pipeline/prompt_manager.py.
Externalizes prompts as versioned, structured config -- SCOPE, FORMAT, and
CONSTRAINTS as first-class fields, not just prose baked into a
system_prompt string.

Why this exists:
  A prompt that lives only as a string embedded in application code can only
  change when that code is redeployed. This module treats prompts the way an
  integration architect treats endpoint config or transformation maps --
  externalized, versioned, and reloadable without touching the running
  process.

What it does NOT do:
  It does not resolve authentication and it does not resolve models. Those
  are orchestration_accelerator.registry's and claude-model-router-
  accelerator's concerns, respectively. PromptManager only ever returns
  prompt config.

Only change from the original demo module: PROMPTS_DIR now resolves relative
to this package's install location by default (prompts/ ships at the
project_accelerator/orchestration_accelerator package root, or a consuming
project's own prompts/ directory when constructed with an explicit path).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Default: <repo-or-package-root>/prompts -- i.e. three levels up from this
# file (src/orchestration_accelerator/prompting/prompt_manager.py -> src/orchestration_accelerator/prompting
# -> src/orchestration_accelerator -> src -> package root) then into prompts/.
# A consuming project scaffolded by claude-project-accelerator passes its own
# prompts/ directory explicitly instead of relying on this default.
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


class PromptValidationError(Exception):
    """Raised when a prompt config file is missing a required Description field."""


class OutputContractError(Exception):
    """Raised when a model's actual output fails to satisfy the prompt's format contract."""


@dataclass(frozen=True)
class PromptConfig:
    step: str
    version: int
    scope: dict[str, Any]
    format: dict[str, Any]
    constraints: list[str]
    system_prompt: str

    def describe(self) -> str:
        """Human-readable summary -- useful for logging which contract was
        actually in force for a given run."""
        lines = [
            f"[{self.step} v{self.version}]",
            f"  in_bounds:     {self.scope.get('in_bounds')}",
            f"  out_of_bounds: {self.scope.get('out_of_bounds')}",
            f"  format:        {self.format}",
            f"  constraints:   {len(self.constraints)} rule(s)",
        ]
        return "\n".join(lines)


class PromptManager:
    """
    Loads prompt configs from disk on every call to get(). This is the
    "hot reload" mechanism: because the source of truth is a file rather
    than an in-process constant, an edit to the YAML takes effect on the
    very next request -- no redeploy, no restart.
    """

    REQUIRED_FIELDS = {"step", "version", "scope", "format", "constraints", "system_prompt"}

    def __init__(self, prompts_dir: Path | str = PROMPTS_DIR):
        self.prompts_dir = Path(prompts_dir)

    def get(self, step: str, filename: str | None = None) -> PromptConfig:
        """Load a step's prompt config. `filename`, when given, lets a
        step's prompt file be named differently from the step itself (per
        process_registry.yaml's `prompt` field) -- defaults to
        `<step>.yaml` when omitted."""
        path = self.prompts_dir / (filename or f"{step}.yaml")
        if not path.exists():
            raise PromptValidationError(f"No prompt config found for step '{step}' at {path}")

        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        missing = self.REQUIRED_FIELDS - raw.keys()
        if missing:
            raise PromptValidationError(
                f"Prompt config for '{step}' is missing required Description "
                f"fields: {sorted(missing)}. A prompt without scope/format/"
                f"constraints is exactly the under-described prompt that "
                f"breaks in production."
            )

        return PromptConfig(
            step=raw["step"],
            version=raw["version"],
            scope=raw["scope"],
            format=raw["format"],
            constraints=raw["constraints"],
            system_prompt=raw["system_prompt"],
        )

    def validate_output(self, step: str, cfg: PromptConfig, output: str) -> Any:
        """
        Enforces the FORMAT pillar in code, not just in prompt text.
        Raises OutputContractError on violation.
        """
        fmt = cfg.format

        if fmt["type"] == "enum":
            value = output.strip()
            if fmt.get("case") == "lower":
                value = value.lower()
            allowed = fmt["allowed_values"]
            if value not in allowed:
                raise OutputContractError(
                    f"[{step} v{cfg.version}] output '{output!r}' is not one of "
                    f"the allowed_values {allowed}"
                )
            return value

        if fmt["type"] == "json":
            try:
                parsed = json.loads(output.strip())
            except json.JSONDecodeError as e:
                raise OutputContractError(
                    f"[{step} v{cfg.version}] output is not valid JSON: {e}"
                ) from e

            expected_keys = set(fmt["schema"].keys())
            actual_keys = set(parsed.keys())
            if actual_keys != expected_keys:
                raise OutputContractError(
                    f"[{step} v{cfg.version}] JSON keys {sorted(actual_keys)} "
                    f"do not match contract {sorted(expected_keys)}"
                )

            urgency_spec = fmt["schema"].get("urgency", "")
            if urgency_spec.startswith("enum["):
                allowed = [v.strip() for v in urgency_spec[5:-1].split(",")]
                if parsed.get("urgency") not in allowed:
                    raise OutputContractError(
                        f"[{step} v{cfg.version}] urgency '{parsed.get('urgency')}' "
                        f"not in {allowed}"
                    )
            return parsed

        if fmt["type"] == "text":
            word_count = len(output.split())
            max_words = fmt.get("max_words")
            if max_words and word_count > max_words:
                raise OutputContractError(
                    f"[{step} v{cfg.version}] output is {word_count} words, "
                    f"exceeds max_words={max_words}"
                )
            return output.strip()

        raise OutputContractError(f"Unknown format type '{fmt['type']}' in contract")

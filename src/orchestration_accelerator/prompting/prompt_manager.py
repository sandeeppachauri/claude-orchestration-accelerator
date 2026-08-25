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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestration_accelerator.errors import friendly_error

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

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
    user_prompt: str | None = None

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
            raise PromptValidationError(
                friendly_error(
                    f"Step '{step}' has no prompt file to run -- this is a "
                    f"setup/config problem, not something the input caused.",
                    f"No prompt config found for step '{step}' at {path}",
                )
            )

        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        missing = self.REQUIRED_FIELDS - raw.keys()
        if missing:
            raise PromptValidationError(
                friendly_error(
                    f"The prompt file for step '{step}' is incomplete and needs "
                    f"a developer to fix it before this step can run.",
                    f"Prompt config for '{step}' is missing required Description "
                    f"fields: {sorted(missing)}. A prompt without scope/format/"
                    f"constraints is exactly the under-described prompt that "
                    f"breaks in production.",
                )
            )

        return PromptConfig(
            step=raw["step"],
            version=raw["version"],
            scope=raw["scope"],
            format=raw["format"],
            constraints=raw["constraints"],
            system_prompt=raw["system_prompt"],
            user_prompt=raw.get("user_prompt"),
        )

    def has_placeholders(self, step: str, filename: str | None = None) -> bool:
        """Whether this step's prompt declares any `{{key}}` placeholder --
        i.e. whether it takes the templated-dict input path in render()
        rather than the legacy plain-string path. Lets a caller (the
        step loop in core.py) decide up front whether to build a dict
        of prior-step outputs for this step, without duplicating
        render()'s placeholder-detection logic."""
        cfg = self.get(step, filename=filename)
        placeholders = set(_PLACEHOLDER_RE.findall(cfg.system_prompt))
        if cfg.user_prompt is not None:
            placeholders |= set(_PLACEHOLDER_RE.findall(cfg.user_prompt))
        return bool(placeholders)

    def render(
        self, step: str, values: dict[str, Any] | str, filename: str | None = None
    ) -> tuple[PromptConfig, str, str]:
        """Load a step's prompt config and resolve `{{key}}` placeholders
        in `system_prompt`/`user_prompt` against `values`.

        `values` is either:
          - a plain string: legacy path. The prompt must contain NO
            placeholders (any `{{key}}` present is a config/call-site
            mismatch, raised immediately). Returned user content is
            `values` verbatim; `system_prompt` is used as-is.
          - a dict of `{key: value}`: template path. The step's
            `user_prompt` field is then REQUIRED (there is nothing else
            to send as the user turn). Every `{{key}}` in `system_prompt`
            and `user_prompt` must have a matching dict key, else
            `PromptValidationError` is raised so config and call site
            can never silently drift apart. Extra dict keys not used by
            this step's placeholders are allowed and ignored -- a
            multi-step run shares one flat `input` dict across steps
            with different placeholder needs, so a key meant for another
            step must not fail this one.

        Returns (cfg, rendered_system_prompt, rendered_user_content).
        """
        cfg = self.get(step, filename=filename)

        placeholders = set(_PLACEHOLDER_RE.findall(cfg.system_prompt))
        if cfg.user_prompt is not None:
            placeholders |= set(_PLACEHOLDER_RE.findall(cfg.user_prompt))

        if isinstance(values, str):
            if placeholders:
                raise PromptValidationError(
                    friendly_error(
                        f"The input sent for step '{step}' is the wrong shape -- "
                        f"it needs to be a set of named fields, not a single block "
                        f"of text.",
                        f"Step '{step}' prompt declares placeholder(s) "
                        f"{sorted(placeholders)} but was called with a plain "
                        f"string input. Pass a dict of {{key: value}} covering "
                        f"every placeholder instead.",
                    )
                )
            return cfg, cfg.system_prompt, values

        # values is a dict from here on.
        if not placeholders:
            raise PromptValidationError(
                friendly_error(
                    f"The input sent for step '{step}' is the wrong shape -- "
                    f"it needs to be a single block of text, not named fields.",
                    f"Step '{step}' prompt has no {{{{key}}}} placeholders but was "
                    f"called with a dict input {sorted(values.keys())}. Pass a plain "
                    f"string, or add placeholders to the prompt YAML.",
                )
            )

        if cfg.user_prompt is None:
            raise PromptValidationError(
                friendly_error(
                    f"Step '{step}' is misconfigured and needs a developer fix "
                    f"before it can accept structured input.",
                    f"Step '{step}' input is a dict but the prompt YAML has no "
                    f"'user_prompt' field -- a templated step must define "
                    f"'user_prompt' as the user turn.",
                )
            )

        missing = placeholders - values.keys()
        if missing:
            raise PromptValidationError(
                friendly_error(
                    f"The input sent for step '{step}' is missing some required "
                    f"information: {sorted(missing)}.",
                    f"Step '{step}' prompt requires placeholder(s) {sorted(missing)} "
                    f"not present in the supplied input {sorted(values.keys())}.",
                )
            )

        def _sub(text: str) -> str:
            return _PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), text)

        return cfg, _sub(cfg.system_prompt), _sub(cfg.user_prompt)

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
                    friendly_error(
                        f"The model's answer for step '{step}' wasn't one of the "
                        f"expected options ({', '.join(allowed)}) -- the run "
                        f"needs to be retried or the prompt adjusted.",
                        f"[{step} v{cfg.version}] output '{output!r}' is not one of "
                        f"the allowed_values {allowed}",
                    )
                )
            return value

        if fmt["type"] == "json":
            if not output.strip():
                raise OutputContractError(
                    friendly_error(
                        f"Step '{step}' got no answer back from the model at all "
                        f"(empty response), so there's nothing to check against "
                        f"the expected JSON format. This usually means the model "
                        f"ran out of turns doing something else (e.g. tool calls) "
                        f"before it could reply -- check this step's `tools`/"
                        f"`max_turns`/`permission_mode` in process_registry.yaml.",
                        f"[{step} v{cfg.version}] output is empty ('').",
                    )
                )
            cleaned = output.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned).strip()

            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                raise OutputContractError(
                    friendly_error(
                        f"The model's answer for step '{step}' wasn't valid JSON, "
                        f"so it couldn't be processed. The run needs to be "
                        f"retried, or the prompt/model needs adjusting.",
                        f"[{step} v{cfg.version}] output is not valid JSON: {e}. "
                        f"Raw output: {output!r}",
                    )
                ) from e

            expected_keys = set(fmt["schema"].keys())
            actual_keys = set(parsed.keys())
            if actual_keys != expected_keys:
                raise OutputContractError(
                    friendly_error(
                        f"The model's answer for step '{step}' didn't include the "
                        f"expected fields -- the run needs to be retried or the "
                        f"prompt adjusted.",
                        f"[{step} v{cfg.version}] JSON keys {sorted(actual_keys)} "
                        f"do not match contract {sorted(expected_keys)}",
                    )
                )

            urgency_spec = fmt["schema"].get("urgency", "")
            if urgency_spec.startswith("enum["):
                allowed = [v.strip() for v in urgency_spec[5:-1].split(",")]
                if parsed.get("urgency") not in allowed:
                    raise OutputContractError(
                        friendly_error(
                            f"The model gave an urgency level for step '{step}' "
                            f"that isn't one of the expected options "
                            f"({', '.join(allowed)}).",
                            f"[{step} v{cfg.version}] urgency '{parsed.get('urgency')}' "
                            f"not in {allowed}",
                        )
                    )
            return parsed

        if fmt["type"] == "text":
            word_count = len(output.split())
            max_words = fmt.get("max_words")
            if max_words and word_count > max_words:
                raise OutputContractError(
                    friendly_error(
                        f"The model's answer for step '{step}' was longer than "
                        f"allowed ({word_count} words, limit {max_words}).",
                        f"[{step} v{cfg.version}] output is {word_count} words, "
                        f"exceeds max_words={max_words}",
                    )
                )
            return output.strip()

        raise OutputContractError(
            friendly_error(
                f"Step '{step}' has an invalid output format configured -- this "
                f"needs a developer fix in the prompt file, not a retry.",
                f"Unknown format type '{fmt['type']}' in contract",
            )
        )

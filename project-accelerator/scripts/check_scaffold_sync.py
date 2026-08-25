#!/usr/bin/env python
"""
check_scaffold_sync.py

`cpa new` ships project-accelerator/src/project_accelerator/scaffold_data/
to every scaffolded project -- it must always reflect this repo's own
config/ schemas, rule docs, and worked example (templatingDemo,
dummyDemoSkill), or a freshly scaffolded project silently gets a stale
copy. Checks STRUCTURE (schema shape), not literal byte-for-byte content
-- scaffold_data intentionally carries commented-out/inactive example
data instead of this repo's live values.

Exits non-zero with a diff-style message naming every drifted file if out
of sync. Run directly: `python project-accelerator/scripts/check_scaffold_sync.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFIG = REPO_ROOT / "config"
SCAFFOLD_DATA = REPO_ROOT / "project-accelerator" / "src" / "project_accelerator" / "scaffold_data"
SCAFFOLD_CONFIG = SCAFFOLD_DATA / "config"
CAPABILITY_RULE_DOC = REPO_ROOT / ".claude" / "rules" / "capability-registry.md"
CLI_PY = REPO_ROOT / "project-accelerator" / "src" / "project_accelerator" / "cli.py"

# Rule docs and other files kept byte-identical between root and
# scaffold_data.
EXACT_SYNCED_PAIRS = [
    (REPO_ROOT / ".claude" / "rules" / "process-registry.md", SCAFFOLD_DATA / ".claude" / "rules" / "process-registry.md"),
    (REPO_ROOT / ".claude" / "rules" / "batch-registry.md", SCAFFOLD_DATA / ".claude" / "rules" / "batch-registry.md"),
    (REPO_ROOT / ".claude" / "rules" / "capability-registry.md", SCAFFOLD_DATA / ".claude" / "rules" / "capability-registry.md"),
    (REPO_ROOT / ".claude" / "rules" / "mcp-scope.md", SCAFFOLD_DATA / ".claude" / "rules" / "mcp-scope.md"),
    (REPO_ROOT / ".claude" / "rules" / "guardrails-registry.md", SCAFFOLD_DATA / ".claude" / "rules" / "guardrails-registry.md"),
    (REPO_ROOT / "config" / "process_registry.yaml", SCAFFOLD_CONFIG / "process_registry.yaml"),
    (REPO_ROOT / "config" / "batch_registry.yaml", SCAFFOLD_CONFIG / "batch_registry.yaml"),
]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def check_exact_pairs(errors: list[str]) -> None:
    for root_path, scaffold_path in EXACT_SYNCED_PAIRS:
        if not root_path.exists():
            errors.append(f"missing root file: {root_path}")
            continue
        if not scaffold_path.exists():
            errors.append(f"missing scaffold_data copy: {scaffold_path}")
            continue
        root_text = root_path.read_text()
        scaffold_text = scaffold_path.read_text()
        if root_text != scaffold_text:
            errors.append(
                f"{root_path.relative_to(REPO_ROOT)} and "
                f"{scaffold_path.relative_to(REPO_ROOT)} have drifted (content differs)"
            )


def check_capability_registry_structure(errors: list[str]) -> None:
    root_cfg = _load_yaml(ROOT_CONFIG / "capability_registry.yaml")
    scaffold_cfg = _load_yaml(SCAFFOLD_CONFIG / "capability_registry.yaml")
    for backend in root_cfg:
        root_allowed = set(root_cfg.get(backend, {}).get("allowed", []))
        scaffold_allowed = set(scaffold_cfg.get(backend, {}).get("allowed", []))
        missing = root_allowed - scaffold_allowed
        if missing:
            errors.append(
                f"config/capability_registry.yaml backend '{backend}' has "
                f"key(s) {sorted(missing)} not present in scaffold_data's copy"
            )


def _extract_doc_allowed_lists(text: str) -> dict[str, set[str]]:
    """Parses the `agent_sdk:\\n  allowed: [...]` / `messages_api:\\n
    allowed: [...]` fence in .claude/rules/capability-registry.md's
    illustrative schema block -- a hand-written example, not YAML loaded
    from config/, so it drifts silently from the real registry unless
    something checks it (this is exactly the bug that shipped stale
    scaffolded-project docs: the registry gained mcp_servers/allowed_tools/
    guardrails/skills but this doc's example fence was never updated)."""
    result: dict[str, set[str]] = {}
    for backend in ("agent_sdk", "messages_api"):
        match = re.search(rf"{backend}:\s*\n\s*allowed:\s*\[(.*?)\]", text)
        if match:
            result[backend] = {k.strip() for k in match.group(1).split(",") if k.strip()}
    return result


def check_capability_rule_doc_matches_registry(errors: list[str]) -> None:
    if not CAPABILITY_RULE_DOC.exists():
        errors.append(f"missing rule doc: {CAPABILITY_RULE_DOC}")
        return

    root_cfg = _load_yaml(ROOT_CONFIG / "capability_registry.yaml")
    doc_lists = _extract_doc_allowed_lists(CAPABILITY_RULE_DOC.read_text())

    for backend in root_cfg:
        registry_allowed = set(root_cfg.get(backend, {}).get("allowed", []))
        doc_allowed = doc_lists.get(backend, set())
        missing_from_doc = registry_allowed - doc_allowed
        extra_in_doc = doc_allowed - registry_allowed
        if missing_from_doc:
            errors.append(
                f".claude/rules/capability-registry.md's example fence for "
                f"'{backend}' is missing key(s) {sorted(missing_from_doc)} "
                f"present in config/capability_registry.yaml -- update the "
                f"doc's illustrative `allowed: [...]` list"
            )
        if extra_in_doc:
            errors.append(
                f".claude/rules/capability-registry.md's example fence for "
                f"'{backend}' documents key(s) {sorted(extra_in_doc)} not "
                f"present in config/capability_registry.yaml -- stale entry, "
                f"remove it from the doc"
            )


def check_howto_capability_table_matches_registry(errors: list[str]) -> None:
    """cli.py's generated HOWTO.md ships a 'Full capability-passthrough key
    reference' table describing every whitelisted capability key to every
    scaffolded project -- it must list every key in
    config/capability_registry.yaml (both backends combined), or a
    scaffolded project's own docs undersell what's actually available."""
    if not CLI_PY.exists():
        errors.append(f"missing file: {CLI_PY}")
        return

    root_cfg = _load_yaml(ROOT_CONFIG / "capability_registry.yaml")
    registry_keys: set[str] = set()
    for backend_cfg in root_cfg.values():
        registry_keys |= set(backend_cfg.get("allowed", []))

    text = CLI_PY.read_text()
    table_match = re.search(
        r"Full capability-passthrough key reference.*?\n\n(.*?)\n\n", text, re.DOTALL
    )
    if not table_match:
        errors.append(
            f"{CLI_PY}: could not locate the 'Full capability-passthrough "
            f"key reference' table to check it against config/capability_registry.yaml"
        )
        return

    table_text = table_match.group(1)
    documented_keys = set(re.findall(r"\|\s*`([a-zA-Z_]+)`\s*\|", table_text))
    missing_from_table = registry_keys - documented_keys
    if missing_from_table:
        errors.append(
            f"{CLI_PY}'s 'Full capability-passthrough key reference' table "
            f"is missing key(s) {sorted(missing_from_table)} present in "
            f"config/capability_registry.yaml -- add a row for each"
        )


def check_guardrails_yaml_exists(errors: list[str]) -> None:
    scaffold_guardrails = SCAFFOLD_CONFIG / "guardrails.yaml"
    if not scaffold_guardrails.exists():
        errors.append(f"missing scaffold_data copy: {scaffold_guardrails}")


def check_examples_referenced(errors: list[str]) -> None:
    """templatingDemo/escalate/dummyDemoSkill are this repo's worked
    example -- scaffold_data must ship the same names so a snippet quoted
    from CLAUDE.md/README.md still resolves in a scaffolded project."""
    root_registry = _load_yaml(ROOT_CONFIG / "process_registry.yaml")
    scaffold_registry = _load_yaml(SCAFFOLD_CONFIG / "process_registry.yaml")

    if "templatingDemo" in root_registry:
        if "templatingDemo" not in scaffold_registry:
            errors.append(
                "root config/process_registry.yaml has 'templatingDemo' but "
                "scaffold_data's copy does not -- example renamed/removed "
                "without updating the scaffold"
            )
        else:
            root_steps = set(root_registry["templatingDemo"].get("steps", []))
            scaffold_steps = set(scaffold_registry["templatingDemo"].get("steps", []))
            missing_steps = root_steps - scaffold_steps
            if missing_steps:
                errors.append(
                    f"templatingDemo step(s) {sorted(missing_steps)} in root "
                    f"config/process_registry.yaml missing from scaffold_data's copy"
                )

    dummy_skill_root = REPO_ROOT / ".claude" / "skills" / "dummyDemoSkill" / "SKILL.md"
    dummy_skill_scaffold = SCAFFOLD_DATA / ".claude" / "skills" / "dummyDemoSkill" / "SKILL.md"
    if dummy_skill_root.exists() and not dummy_skill_scaffold.exists():
        errors.append(
            f"{dummy_skill_root.relative_to(REPO_ROOT)} exists but "
            f"{dummy_skill_scaffold.relative_to(REPO_ROOT)} is missing -- "
            f"example skill not mirrored into the scaffold"
        )

    root_mcp = REPO_ROOT / ".mcp.json"
    scaffold_mcp = SCAFFOLD_DATA / ".mcp.json"
    if root_mcp.exists() and not scaffold_mcp.exists():
        errors.append(f"{root_mcp} exists but {scaffold_mcp} is missing")

    root_team_guide = REPO_ROOT / "docs" / "Claude_Orchestration_Accelerator_Team_Guide.docx"
    scaffold_team_guide = SCAFFOLD_DATA / "docs" / "Claude_Orchestration_Accelerator_Team_Guide.docx"
    if root_team_guide.exists() and not scaffold_team_guide.exists():
        errors.append(
            f"{root_team_guide.relative_to(REPO_ROOT)} exists but "
            f"{scaffold_team_guide.relative_to(REPO_ROOT)} is missing -- "
            f"team guide not mirrored into the scaffold"
        )


def main() -> int:
    errors: list[str] = []
    check_exact_pairs(errors)
    check_capability_registry_structure(errors)
    check_capability_rule_doc_matches_registry(errors)
    check_howto_capability_table_matches_registry(errors)
    check_guardrails_yaml_exists(errors)
    check_examples_referenced(errors)

    if errors:
        print("scaffold_data is out of sync with the repo root:\n", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nUpdate project-accelerator/src/project_accelerator/scaffold_data/ "
            "to match, then re-run this check.",
            file=sys.stderr,
        )
        return 1

    print("scaffold_data is in sync with the repo root.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

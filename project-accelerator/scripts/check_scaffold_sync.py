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

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFIG = REPO_ROOT / "config"
SCAFFOLD_DATA = REPO_ROOT / "project-accelerator" / "src" / "project_accelerator" / "scaffold_data"
SCAFFOLD_CONFIG = SCAFFOLD_DATA / "config"

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


def main() -> int:
    errors: list[str] = []
    check_exact_pairs(errors)
    check_capability_registry_structure(errors)
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

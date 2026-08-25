"""
test_scaffold_sync.py

process_registry.yaml/batch_registry.yaml/rule docs exist as two physical
copies -- root repo (this accelerator's own dev/test use) and
project-accelerator/src/project_accelerator/scaffold_data/ (what `cpa new`
actually ships to every scaffolded project) -- kept in sync by hand. This
test catches drift immediately instead of silently shipping a stale
scaffold.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_DATA = ROOT / "project-accelerator" / "src" / "project_accelerator" / "scaffold_data"

SYNCED_PAIRS = [
    (ROOT / "config" / "process_registry.yaml", SCAFFOLD_DATA / "config" / "process_registry.yaml"),
    (ROOT / "config" / "batch_registry.yaml", SCAFFOLD_DATA / "config" / "batch_registry.yaml"),
    (
        ROOT / ".claude" / "rules" / "process-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "process-registry.md",
    ),
    (
        ROOT / ".claude" / "rules" / "batch-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "batch-registry.md",
    ),
    (
        ROOT / ".claude" / "rules" / "capability-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "capability-registry.md",
    ),
    (
        ROOT / ".claude" / "rules" / "mcp-scope.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "mcp-scope.md",
    ),
    (
        ROOT / ".claude" / "rules" / "guardrails-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "guardrails-registry.md",
    ),
]


@pytest.mark.parametrize("root_path,scaffold_path", SYNCED_PAIRS, ids=lambda p: p.name if isinstance(p, Path) else p)
def test_root_and_scaffold_copy_match(root_path: Path, scaffold_path: Path) -> None:
    assert root_path.exists(), f"missing root copy: {root_path}"
    assert scaffold_path.exists(), f"missing scaffold_data copy: {scaffold_path}"
    assert root_path.read_text() == scaffold_path.read_text(), (
        f"{root_path} and {scaffold_path} have drifted -- keep these two "
        f"physical copies in sync by hand until they're unified."
    )


def test_check_scaffold_sync_script_passes() -> None:
    """Covers everything test_root_and_scaffold_copy_match's exact pairs
    don't: capability_registry.yaml structural (allowed-list) parity,
    config/guardrails.yaml presence, and the templatingDemo/dummyDemoSkill/
    .mcp.json worked example being mirrored into scaffold_data."""
    script = ROOT / "project-accelerator" / "scripts" / "check_scaffold_sync.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr

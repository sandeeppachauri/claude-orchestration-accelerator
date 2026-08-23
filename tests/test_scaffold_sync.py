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

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_DATA = ROOT / "project-accelerator" / "src" / "project_accelerator" / "scaffold_data"

SYNCED_PAIRS = [
    (ROOT / "process_registry.yaml", SCAFFOLD_DATA / "process_registry.yaml"),
    (ROOT / "batch_registry.yaml", SCAFFOLD_DATA / "batch_registry.yaml"),
    (
        ROOT / ".claude" / "rules" / "process-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "process-registry.md",
    ),
    (
        ROOT / ".claude" / "rules" / "batch-registry.md",
        SCAFFOLD_DATA / ".claude" / "rules" / "batch-registry.md",
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

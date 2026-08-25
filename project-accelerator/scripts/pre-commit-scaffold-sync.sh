#!/bin/sh
# pre-commit-scaffold-sync.sh
#
# Tracked template for a git pre-commit hook -- git only runs hooks from
# .git/hooks/, which isn't checked in, so this file is installed there by
# install-git-hooks.sh (run once per clone). Blocks a commit that touches
# config/*.yaml, .claude/rules/*.md, or project-accelerator's scaffold_data
# without keeping scaffold_data in sync -- see check_scaffold_sync.py.

changed=$(git diff --cached --name-only)

if echo "$changed" | grep -qE '^(config/.*\.yaml|\.claude/rules/.*\.md|project-accelerator/src/project_accelerator/scaffold_data/)'; then
    python project-accelerator/scripts/check_scaffold_sync.py
    if [ $? -ne 0 ]; then
        echo ""
        echo "pre-commit: scaffold_data drift detected -- commit blocked. See above." >&2
        exit 1
    fi
fi

exit 0

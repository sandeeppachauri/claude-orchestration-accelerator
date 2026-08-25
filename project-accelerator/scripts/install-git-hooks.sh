#!/bin/sh
# install-git-hooks.sh
#
# One-time, per-clone setup: copies this repo's tracked hook templates
# into .git/hooks/, which git only reads from a local, untracked
# location. Run once after cloning: sh project-accelerator/scripts/install-git-hooks.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cp "$REPO_ROOT/project-accelerator/scripts/pre-commit-scaffold-sync.sh" "$REPO_ROOT/.git/hooks/pre-commit"
chmod +x "$REPO_ROOT/.git/hooks/pre-commit"
echo "Installed pre-commit hook: scaffold_data drift check."

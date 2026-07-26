#!/bin/sh
# Point this clone's git hooks at scripts/hooks/.
#
#     ./scripts/install-git-hooks.sh
#
# This sets `core.hooksPath`, which is local to your clone and committed
# nowhere — every contributor opts in for themselves. Undo it with:
#
#     git config --unset core.hooksPath
#
# What you get: a pre-push hook that refuses direct pushes to main, standing in
# for the server-side branch protection that a private repository on a Free plan
# cannot have.

set -eu

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

chmod +x scripts/hooks/* 2>/dev/null || true
git config core.hooksPath scripts/hooks

printf 'git hooks installed: core.hooksPath = %s\n' "$(git config core.hooksPath)"
printf 'active hooks:\n'
for hook in scripts/hooks/*; do
    [ -f "$hook" ] || continue
    printf '  %s\n' "$(basename "$hook")"
done
printf '\nDisable again with: git config --unset core.hooksPath\n'

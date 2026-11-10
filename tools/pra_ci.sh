#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Dispatch the PRA XNU build on GitHub Actions and download the artifact.
#
#   tools/pra_ci.sh [owner/repo]
#
# With no argument, uses the `origin` remote. Requires `gh auth login` first.
set -eu
cd "$(dirname "$0")/.."

REPO=${1:-}
if [ -z "$REPO" ]; then
    URL=$(git remote get-url origin 2>/dev/null || true)
    REPO=$(printf '%s\n' "$URL" | sed -nE 's#.*github\.com[:/]([^/]+/[^/]+?)(\.git)?$#\1#p')
fi
if [ -z "$REPO" ]; then
    echo "usage: pra_ci.sh owner/repo   (or add an origin remote first)" >&2
    exit 1
fi

gh auth status >/dev/null 2>&1 || {
    echo "error: gh is not authenticated; run: gh auth login" >&2
    exit 1
}

# The workflow must exist on the default branch for workflow_dispatch.
# Push the current tree there; a new repo gets this branch as its default.
if ! git remote get-url origin >/dev/null 2>&1; then
    gh repo create "$REPO" --private --source=. --remote=origin
fi
git push -u origin HEAD

# Dispatch with the PRA target. The push trigger defaults to A5XELTE, so this
# must be an explicit workflow_dispatch run.
gh workflow run xnu.yml --repo "$REPO" \
    -f machine_config=PRA \
    -f macos_version=13.5 \
    -f kernel_config=DEVELOPMENT \
    -f keep_going=true

# Give Actions a moment to register the run, then follow the newest one.
sleep 5
RUN=$(gh run list --repo "$REPO" --workflow xnu.yml --limit 1 \
    --json databaseId --jq '.[0].databaseId')
[ -n "$RUN" ] || { echo "error: no run appeared" >&2; exit 1; }
echo "run: https://github.com/$REPO/actions/runs/$RUN"

# Download even on failure: the workflow uploads xnu-kernel and buildtree with
# if: always(), and the buildtree is what makes a failed compile debuggable.
gh run watch "$RUN" --repo "$REPO" || true
CONCLUSION=$(gh run view "$RUN" --repo "$REPO" --json conclusion --jq .conclusion)
echo "conclusion: $CONCLUSION"

mkdir -p out/ci
gh run download "$RUN" --repo "$REPO" -n xnu-kernel -D out/ci || true
gh run download "$RUN" --repo "$REPO" -n xnu-buildtree -D out/ci || true
ls -l out/ci

if [ "$CONCLUSION" = "success" ]; then
    echo
    echo "package: tools/pra_package.sh out/ci/kernel.development.pra"
else
    echo
    echo "build failed; inspect out/ci and the run log before packaging" >&2
    exit 1
fi

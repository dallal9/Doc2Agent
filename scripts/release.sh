#!/usr/bin/env bash
#
# Release helper — designed to run on a feature branch that will become a PR.
#
# What it does:
#   1. Reads `scripts/release.yaml` (you should have edited it already).
#   2. Bumps the version in `pyproject.toml` to match.
#   3. Commits both files on the current branch.
#   4. Prints the exact commands you need to run after the PR is merged
#      into `main` to tag the merge commit and trigger the release workflow.
#
# It does NOT push, NOT tag, NOT touch `main`. Branch protection stays intact.
#
# Usage:
#   ./scripts/release.sh             # bump + commit on current branch
#   ./scripts/release.sh --dry-run   # show what would happen, no changes
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

YAML="scripts/release.yaml"
PYPROJECT="pyproject.toml"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

if [[ ! -f "$YAML" ]]; then
  echo "error: $YAML not found" >&2
  exit 1
fi

# Parse version + description from YAML using python (pyyaml is in uv.lock).
read_yaml() {
  uv run python - "$YAML" <<'PY'
import sys, yaml, pathlib, base64
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
version = (data.get("version") or "").strip()
description = (data.get("description") or "").rstrip()
if not version:
    raise SystemExit("error: 'version' missing from release.yaml")
print(f"VERSION={version}")
print("DESCRIPTION_B64=" + base64.b64encode(description.encode("utf-8")).decode("ascii"))
PY
}

eval "$(read_yaml)"
DESCRIPTION="$(echo -n "$DESCRIPTION_B64" | base64 -d)"
TAG="v${VERSION}"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "Release version : $VERSION"
echo "Tag (later)     : $TAG"
echo "Current branch  : $BRANCH"
echo "Description     :"
echo "$DESCRIPTION" | sed 's/^/  | /'
echo

# Sanity checks tailored to PR-based flow.
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  echo "error: refusing to run on '$BRANCH'." >&2
  echo "       create a release branch first, e.g.:" >&2
  echo "         git checkout -b release/${TAG}" >&2
  exit 1
fi
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "error: tag $TAG already exists locally — pick a new version." >&2
  exit 1
fi
if git ls-remote --tags origin "refs/tags/$TAG" | grep -q .; then
  echo "error: tag $TAG already exists on origin — pick a new version." >&2
  exit 1
fi
if ! grep -qE '^version\s*=\s*"[^"]+"' "$PYPROJECT"; then
  echo "error: could not find a 'version = \"...\"' line in $PYPROJECT" >&2
  exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] would set version=$VERSION in $PYPROJECT"
  echo "[dry-run] would commit $PYPROJECT and $YAML on branch '$BRANCH'"
  exit 0
fi

# Bump pyproject.toml (only the project's own version line — first match).
uv run python - "$PYPROJECT" "$VERSION" <<'PY'
import re, sys, pathlib
path = pathlib.Path(sys.argv[1])
new_version = sys.argv[2]
text = path.read_text(encoding="utf-8")
new_text, n = re.subn(
    r'^(version\s*=\s*")[^"]+(")',
    rf'\g<1>{new_version}\g<2>',
    text,
    count=1,
    flags=re.MULTILINE,
)
if n == 0:
    raise SystemExit("error: failed to update version in pyproject.toml")
path.write_text(new_text, encoding="utf-8")
PY

git add "$PYPROJECT" "$YAML"

# Only commit if there's actually something staged (lets you re-run safely).
if git diff --cached --quiet; then
  echo "Nothing to commit — pyproject.toml and release.yaml are already in sync."
else
  git commit -m "chore(release): ${TAG}"
  echo "Committed version bump on branch '$BRANCH'."
fi

# Escape the description for safe embedding in the printed heredoc command.
ESCAPED_DESCRIPTION="${DESCRIPTION//\\/\\\\}"
ESCAPED_DESCRIPTION="${ESCAPED_DESCRIPTION//\$/\\\$}"
ESCAPED_DESCRIPTION="${ESCAPED_DESCRIPTION//\`/\\\`}"

cat <<EOF

──────────────────────────────────────────────────────────────────────
Next steps (do these by hand, since main is protected):
──────────────────────────────────────────────────────────────────────

  1. Push this branch and open a PR:

       git push -u origin $BRANCH
       gh pr create --fill   # or open one in the GitHub UI

  2. After the PR is reviewed and merged into main:

       git checkout main
       git pull --ff-only

  3. Tag the merge commit and push the tag (this triggers the release
     workflow which creates the GitHub Release):

       git tag -a $TAG -m "$TAG" -m "\$(uv run python -c 'import yaml,pathlib; print(yaml.safe_load(pathlib.Path("scripts/release.yaml").read_text())["description"].rstrip())')"
       git push origin $TAG

     (Or just run: ./scripts/tag-release.sh — same thing.)

──────────────────────────────────────────────────────────────────────
EOF

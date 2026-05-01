#!/usr/bin/env bash
#
# Tag the current commit using version + description from release/release.yaml,
# and push the tag to origin. Run this on `main` after the release PR is merged.
#
# This step is what triggers .github/workflows/release.yml to publish the
# GitHub Release.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

YAML="release/release.yaml"
if [[ ! -f "$YAML" ]]; then
  echo "error: $YAML not found" >&2
  exit 1
fi

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
if [[ "$BRANCH" != "main" && "$BRANCH" != "master" ]]; then
  echo "warning: you are on branch '$BRANCH', not 'main'." >&2
  echo "         tags should normally point at the merged commit on main." >&2
  read -r -p "         continue anyway? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "error: tag $TAG already exists locally." >&2
  exit 1
fi
if git ls-remote --tags origin "refs/tags/$TAG" | grep -q .; then
  echo "error: tag $TAG already exists on origin." >&2
  exit 1
fi

# Confirm the version-bump commit is actually in the local history.
if ! grep -qE "^version\s*=\s*\"${VERSION//./\\.}\"" pyproject.toml; then
  echo "error: pyproject.toml version doesn't match $VERSION." >&2
  echo "       did you forget to 'git pull' on main after the PR merged?" >&2
  exit 1
fi

git tag -a "$TAG" -m "$TAG" -m "$DESCRIPTION"
git push origin "$TAG"

echo
echo "Pushed $TAG. The release workflow will create the GitHub Release shortly."

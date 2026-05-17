#!/usr/bin/env bash
# Bump version + create release commit + tag.
#
# Usage:
#   ./scripts/release.sh 1.1.0       # explicit version
#   ./scripts/release.sh patch       # 1.0.0 → 1.0.1
#   ./scripts/release.sh minor       # 1.0.0 → 1.1.0
#   ./scripts/release.sh major       # 1.0.0 → 2.0.0
#
# What it does:
#   1. Read current VERSION
#   2. Compute new version (semver bump or explicit value)
#   3. Verify git tree is clean (no uncommitted changes)
#   4. Verify HEAD is on `main` (release from a branch is a footgun)
#   5. Update VERSION + apps/api/pyproject.toml + apps/web/package.json
#   6. Update CHANGELOG.md: move [Unreleased] → [X.Y.Z] — <today>
#   7. Commit "chore(release): vX.Y.Z"
#   8. Tag vX.Y.Z (annotated, with CHANGELOG snippet as message)
#   9. Optionally push (--push flag) — default DRY: just creates
#      the commit + tag locally, you push when ready.
#
# DOES NOT publish to PyPI or npm. DOES NOT trigger a Railway/Vercel
# deploy directly — pushing to `main` does that (Railway watches
# `main`).

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

usage() {
    cat <<EOF
Usage: $0 <version|patch|minor|major> [--push] [--no-tag]

Examples:
  $0 1.1.0          # bump to explicit version
  $0 patch          # 1.0.0 → 1.0.1
  $0 minor --push   # 1.0.0 → 1.1.0, then push to origin/main
EOF
    exit 2
}

if [[ $# -lt 1 ]]; then
    usage
fi

target="$1"; shift
do_push=false
do_tag=true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --push)   do_push=true ;;
        --no-tag) do_tag=false ;;
        *)        usage ;;
    esac
    shift
done

# ---- 1. Current version ----
if [[ ! -f VERSION ]]; then
    echo "ERROR: VERSION file not found at $repo_root/VERSION" >&2
    exit 1
fi
current="$(cat VERSION | tr -d '[:space:]')"
echo "Current version: $current"

# ---- 2. Compute new version ----
case "$target" in
    patch|minor|major)
        # semver bump
        IFS='.' read -r maj min pat <<< "$current"
        case "$target" in
            patch) pat=$((pat + 1)) ;;
            minor) min=$((min + 1)); pat=0 ;;
            major) maj=$((maj + 1)); min=0; pat=0 ;;
        esac
        new="${maj}.${min}.${pat}"
        ;;
    [0-9]*.[0-9]*.[0-9]*)
        new="$target"
        ;;
    *)
        echo "ERROR: invalid version target: $target" >&2
        usage
        ;;
esac
echo "Target version:  $new"

if [[ "$current" == "$new" ]]; then
    echo "ERROR: new version equals current" >&2
    exit 1
fi

# ---- 3. Tree is clean ----
if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree is dirty — commit or stash first" >&2
    git status --short
    exit 1
fi

# ---- 4. On main ----
branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
    echo "WARN: HEAD is on '$branch', not 'main'." >&2
    echo "      Releases should be cut from main. Continue? [y/N]" >&2
    read -r confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        exit 1
    fi
fi

# ---- 5. Update version files ----
echo "$new" > VERSION

# pyproject.toml
python3 -c "
import re
p = 'apps/api/pyproject.toml'
text = open(p).read()
text = re.sub(r'^version = \"$current\"', 'version = \"$new\"', text, count=1, flags=re.M)
open(p, 'w').write(text)
"

# package.json (web)
python3 -c "
import json
p = 'apps/web/package.json'
data = json.load(open(p))
data['version'] = '$new'
with open(p, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"

# ---- 6. Update CHANGELOG ----
today="$(date -u +%Y-%m-%d)"
# Insert new section header. The [Unreleased] block stays — it's
# just emptied conceptually (no auto-move of lines; humans curate
# what's "unreleased" before tagging).
python3 -c "
import re
p = 'CHANGELOG.md'
text = open(p).read()
needle = '## [Unreleased]'
if needle not in text:
    raise SystemExit('CHANGELOG.md missing [Unreleased] section')
new_section = f'## [Unreleased]\n\nTracks work-in-progress on \`main\` ahead of the next tag.\n\n---\n\n## [$new] — $today\n\nSee git log v$current..v$new for the full list of changes.\n'
text = text.replace(needle + '\n\nTracks work-in-progress on \`main\` ahead of the next tag. Lines move\ninto a versioned section when a release ships.\n', new_section, 1)
# Fallback simpler replacement if the above didn't match (CHANGELOG drift)
if needle in text and f'[$new]' not in text:
    text = text.replace(needle, new_section.replace('## [Unreleased]\n\nTracks work-in-progress on \`main\` ahead of the next tag.\n\n---\n\n', '## [Unreleased]\n\n---\n\n', 1), 1)
open(p, 'w').write(text)
" || echo "WARN: CHANGELOG update failed — review manually"

# ---- 7. Commit ----
git add VERSION apps/api/pyproject.toml apps/web/package.json CHANGELOG.md
git commit -m "chore(release): v$new

Bump version from $current to $new across VERSION + api pyproject +
web package.json + CHANGELOG.

🤖 Generated with \`scripts/release.sh\`"

# ---- 8. Tag ----
if [[ "$do_tag" == "true" ]]; then
    # Extract this version's changelog section for the tag annotation
    annotation_body="$(python3 -c "
import re
text = open('CHANGELOG.md').read()
m = re.search(r'^## \[$new\][^\n]*\n(.*?)(?=\n## \[|\Z)', text, re.S | re.M)
print((m.group(1).strip() if m else 'See CHANGELOG.md for changes.')[:4000])
")"
    git tag -a "v$new" -m "AEC Platform v$new

$annotation_body"
    echo "Tagged v$new"
fi

# ---- 9. Push? ----
if [[ "$do_push" == "true" ]]; then
    echo "Pushing to origin/main + tag..."
    git push origin "$branch"
    if [[ "$do_tag" == "true" ]]; then
        git push origin "v$new"
    fi
    echo ""
    echo "✓ Released v$new"
    echo "  Railway will redeploy api + worker shortly."
    echo "  Verify with: AEC_BASE_URL=https://aec-platform-production.up.railway.app make verify-deploy"
    echo "  Then check: curl https://aec-platform-production.up.railway.app/_meta/version"
else
    echo ""
    echo "✓ Release commit + tag created locally."
    echo "  Push when ready: git push origin $branch && git push origin v$new"
    echo "  Or re-run with --push to do it now."
fi

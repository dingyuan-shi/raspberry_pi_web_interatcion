#!/usr/bin/env bash
# Create a single-commit `release` branch (no BLE history) and optionally
# copy screenshots from origin/main.
#
# Usage:
#   cd bluetooth_pi
#   git fetch origin
#   bash scripts/make-release-branch.sh
set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Run this inside your git clone." >&2
    exit 1
fi

git fetch origin

if ! git rev-parse --verify origin/cursor/ble-remote-control >/dev/null 2>&1; then
    echo "ERROR: origin/cursor/ble-remote-control not found. Run: git fetch origin" >&2
    exit 1
fi

echo ">>> Saving screenshots from origin/main (if any)"
TMPDIR=$(mktemp -d)
for f in watch lite cmd shell; do
    git show "origin/main:docs/screenshots/${f}.png" > "${TMPDIR}/${f}.png" 2>/dev/null \
        && echo "    found ${f}.png on main" || true
done

echo ">>> Building single-commit release from origin/cursor/ble-remote-control"
git checkout --orphan release-new origin/cursor/ble-remote-control
git add -A
git commit -m "$(cat <<'EOF'
Initial release: Raspberry Pi web monitoring and remote control

- LAN dashboard (Chart.js + SSE)
- Deploy-gated commands and WebSocket shell
- Lite (SVG) and cheap (PNG) for Kindle and legacy browsers
EOF
)"

mkdir -p docs/screenshots
for f in watch lite cmd shell; do
    if [[ -s "${TMPDIR}/${f}.png" ]]; then
        cp "${TMPDIR}/${f}.png" "docs/screenshots/${f}.png"
        echo "    restored ${f}.png"
    fi
done
rm -rf "${TMPDIR}"

if git status --porcelain docs/screenshots | grep -q .; then
    git add docs/screenshots/*.png
    git commit --amend --no-edit
fi

git branch -D release 2>/dev/null || true
git branch -m release

echo
echo "Done. Local branch: release ($(git rev-list --count HEAD) commit)"
echo "Push with:"
echo "  git push -u origin release"
echo "  git push -f origin release:main    # optional: replace GitHub main"

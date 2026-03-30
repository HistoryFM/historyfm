#!/usr/bin/env bash
# deploy.sh — Publish chapters, sync frontend content, and push for Vercel deploy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"
if command -v sovereign-ink >/dev/null 2>&1; then
  sovereign-ink publish --all
else
  python3 -m sovereign_ink publish --all
fi
bash "$REPO_ROOT/scripts/sync-content.sh"

cd "$REPO_ROOT/frontend"
git add content/
git commit -m "Content update: $(date +%Y-%m-%d)" || echo "No changes to commit."
git push

echo "Done. Vercel will rebuild automatically."

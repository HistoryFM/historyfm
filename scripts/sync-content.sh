#!/usr/bin/env bash
# sync-content.sh — Mirror published content into frontend/content.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="$REPO_ROOT/published"
CONTENT_DIR="$REPO_ROOT/frontend/content/novels"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "ERROR: Source directory not found: $SOURCE_DIR"
  echo "Run 'sovereign-ink publish --all' first."
  exit 1
fi

rm -rf "$CONTENT_DIR"
mkdir -p "$CONTENT_DIR"

if compgen -G "$SOURCE_DIR/*" > /dev/null; then
  cp -R "$SOURCE_DIR"/. "$CONTENT_DIR"/
fi

echo "✓ Synced published/ -> frontend/content/novels/"

# Create polls.json if it doesn't exist
POLLS_FILE="$REPO_ROOT/frontend/content/polls.json"
if [ ! -f "$POLLS_FILE" ]; then
  mkdir -p "$(dirname "$POLLS_FILE")"
  cat > "$POLLS_FILE" <<'POLLSJSON'
{
  "polls": [
    {
      "id": "next-era",
      "question": "Which historical era should we dramatize next?",
      "options": [
        { "id": "revolution", "label": "The American Revolution", "description": "1775-1783" },
        { "id": "civil-war", "label": "The Civil War", "description": "1861-1865" },
        { "id": "reconstruction", "label": "Reconstruction", "description": "1865-1877" },
        { "id": "gilded-age", "label": "The Gilded Age", "description": "1870-1900" },
        { "id": "war-of-1812", "label": "The War of 1812", "description": "1812-1815" }
      ]
    }
  ]
}
POLLSJSON
  echo "✓ polls.json created"
fi

echo "Done."

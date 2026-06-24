#!/bin/bash
# Usage: ./scripts/new_migration.sh "add some column"
# Creates a new migration with the next sequential ID (0003, 0004, ...).
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 \"migration description\"" >&2
  exit 1
fi

VERSIONS_DIR="db/migrations/versions"
COUNT=$(find "$VERSIONS_DIR" -maxdepth 1 -name "*.py" ! -name "__*" | wc -l | tr -d ' ')
NEXT=$(printf '%04d' $((COUNT + 1)))

echo "Creating migration $NEXT..."
uv run alembic revision -m "$1" --rev-id "$NEXT"

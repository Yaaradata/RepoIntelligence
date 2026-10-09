#!/usr/bin/env bash
# Apply sql/migrations/*.sql in order, stopping loudly at the first failure.
# Run by a human. Agents must never run this.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is not set}"
cd "$(dirname "$0")/.."

for f in sql/migrations/*.sql; do
  echo "=== applying $f"
  if ! psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$f"; then
    echo
    echo "########################################################"
    echo "# MIGRATION FAILED: $f"
    echo "# Nothing after this file was applied."
    echo "# Fix it, then re-run scripts/migrate.sh."
    echo "########################################################"
    exit 1
  fi
done

echo "=== all migrations applied; verifying"
python3 scripts/check_schema.py

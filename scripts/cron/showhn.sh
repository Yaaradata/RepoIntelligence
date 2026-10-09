#!/usr/bin/env bash
# Every 6 hours: re-read points/comments for Show HN stories posted < 54h ago.
set -euo pipefail
REPO="${REPO_INTELLIGENCE_HOME:-/home/ubuntu/RepoIntelligence}"
cd "$REPO" || { echo "cron: REPO path does not exist: $REPO" >&2; exit 1; }
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "cron: no venv python at $PY" >&2; exit 1; }
mkdir -p reports/cron
"$PY" scripts/run_stage.py --stage showhn_refresh --trigger cron >> reports/cron/showhn.log 2>&1

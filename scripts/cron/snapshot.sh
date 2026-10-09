#!/usr/bin/env bash
# Sunday 20:00 UTC (01:30 IST Mon): watchlist snapshot on the fixed weekday,
# then downloads for every watched repo. run_stage.py refuses other weekdays.
set -euo pipefail
REPO="${REPO_INTELLIGENCE_HOME:-/home/ubuntu/RepoIntelligence}"
cd "$REPO" || { echo "cron: REPO path does not exist: $REPO" >&2; exit 1; }
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "cron: no venv python at $PY" >&2; exit 1; }
mkdir -p reports/cron
"$PY" scripts/run_stage.py --stage snapshot --scope watchlist --trigger cron >> reports/cron/snapshot.log 2>&1
"$PY" scripts/run_stage.py --stage packages --scope watchlist --trigger cron >> reports/cron/snapshot.log 2>&1

#!/usr/bin/env bash
# Sunday 20:00 UTC (01:30 IST Mon): watchlist snapshot on the fixed weekday,
# then downloads for every watched repo. run_stage.py refuses other weekdays.
set -euo pipefail
REPO=/home/ubuntu/RepoIntelligencev1
cd "$REPO"
mkdir -p reports/cron
PY="$REPO/.venv/bin/python"
"$PY" scripts/run_stage.py --stage snapshot --scope watchlist --trigger cron >> reports/cron/snapshot.log 2>&1
"$PY" scripts/run_stage.py --stage packages --scope watchlist --trigger cron >> reports/cron/snapshot.log 2>&1

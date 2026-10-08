#!/usr/bin/env bash
# Every 6 hours: re-read points/comments for Show HN stories posted < 54h ago.
set -euo pipefail
REPO=/home/ubuntu/RepoIntelligencev1
cd "$REPO"
mkdir -p reports/cron
"$REPO/.venv/bin/python" scripts/run_stage.py --stage showhn_refresh --trigger cron >> reports/cron/showhn.log 2>&1

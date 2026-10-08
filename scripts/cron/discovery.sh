#!/usr/bin/env bash
# Daily 19:00 UTC (00:30 IST): discovery lanes A/D/E → identity → first snapshot
# of new repos → packages → Show HN match. Free. Cron never runs a paid stage.
set -euo pipefail
REPO=/home/ubuntu/RepoIntelligencev1
cd "$REPO"
mkdir -p reports/cron
"$REPO/.venv/bin/python" scripts/run_pipeline.py --trigger cron >> reports/cron/discovery.log 2>&1

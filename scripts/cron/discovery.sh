#!/usr/bin/env bash
# Daily 19:00 UTC (00:30 IST): discovery lanes A/D/E → identity → first snapshot
# of new repos → packages → Show HN match. Free. Cron never runs a paid stage.
set -euo pipefail
REPO="${REPO_INTELLIGENCE_HOME:-/home/ubuntu/RepoIntelligence}"
cd "$REPO" || { echo "cron: REPO path does not exist: $REPO" >&2; exit 1; }
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "cron: no venv python at $PY" >&2; exit 1; }
mkdir -p reports/cron
"$PY" scripts/run_pipeline.py --trigger cron >> reports/cron/discovery.log 2>&1

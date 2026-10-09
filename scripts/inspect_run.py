#!/usr/bin/env python3
"""What did a run find? Read-only — opens a READ ONLY transaction.

  python scripts/inspect_run.py                  # most recent run
  python scripts/inspect_run.py --run-id <uuid>
  python scripts/inspect_run.py --coverage       # field coverage across all repos
  python scripts/inspect_run.py --sample 20      # 20 repos with their snapshot
  python scripts/inspect_run.py --format json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repo_intelligence.common.config import setting, validate_setting_overrides  # noqa: E402
from repo_intelligence.common.db import connect  # noqa: E402
from repo_intelligence.observability.inspect_report import collect, render_json, render_text  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--coverage", action="store_true",
                    help="field coverage and --sample draw from every repo, not only this run")
    ap.add_argument("--sample", type=int, default=None,
                    help="print N repos, lowest repo_id first")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.sample is not None and args.sample < 0:
        raise SystemExit("--sample must be >= 0")
    validate_setting_overrides()
    bar = float(setting("showhn", "min_confidence_for_scoring", 0.70))
    with connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        report = collect(conn, run_id=args.run_id, coverage_all=args.coverage,
                         sample=args.sample, confidence_bar=bar)
    text = render_json(report) if args.format == "json" else render_text(report)
    sys.stdout.write(text)
    return 0 if report.get("run") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

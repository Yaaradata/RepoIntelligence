#!/usr/bin/env python3
"""Phase 1 collection pipeline: discovery → identity → snapshot(new) → packages → Show HN.

  python scripts/run_pipeline.py --dry-run
  python scripts/run_pipeline.py [--lanes new,popular,seed]

Free; no paid stages exist yet. Later phases extend this with --week,
--allow-paid and --max-cost-usd.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repo_intelligence.common.db import connect  # noqa: E402
from repo_intelligence.observability import runs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lanes", default="new,popular,seed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    args = ap.parse_args()

    from repo_intelligence.discovery.lanes import run_discovery
    from repo_intelligence.external.registries import RegistryClient
    from repo_intelligence.identity.stage import resolve_candidates
    from repo_intelligence.packages.stage import run_packages
    from repo_intelligence.showhn.match import run_match
    from repo_intelligence.snapshot.stage import run_snapshot, snapshot_scope

    gh = hn = None
    if not args.dry_run:
        from repo_intelligence.external.github import GitHubClient
        from repo_intelligence.external.hackernews import HNClient
        gh, hn = GitHubClient(), HNClient()

    now = datetime.now(timezone.utc)
    with connect() as conn:
        run_id = runs.start_pipeline_run(conn, "collection", trigger_type=args.trigger,
                                         metadata={"lanes": args.lanes, "dry_run": args.dry_run})
        status, totals = "failed", {"ok": 0, "failed": 0}

        def stage(name, fn):
            sid = runs.start_stage_run(conn, run_id, name)
            try:
                stats = fn()
            except BaseException as exc:
                conn.rollback()
                runs.finish_stage_run(conn, sid, status="failed", error_summary=f"{type(exc).__name__}: {exc}")
                raise
            print(stats.summary(), flush=True)
            runs.finish_stage_run(conn, sid, status="succeeded", items_success=stats.succeeded,
                                  items_failed=stats.failed, items_skipped=stats.skipped,
                                  error_summary="; ".join(stats.errors) or None)
            totals["ok"] += stats.succeeded
            totals["failed"] += stats.failed
            return stats

        try:
            stage("discovery", lambda: run_discovery(conn, gh, hn, run_id, lanes=args.lanes.split(","),
                                                     dry_run=args.dry_run))
            if not args.dry_run:
                stage("identity", lambda: resolve_candidates(conn, gh, run_id))
            new_repos = snapshot_scope(conn, "new")
            stage("snapshot", lambda: run_snapshot(conn, gh, new_repos, scope_label="scope=new",
                                                   now=now, dry_run=args.dry_run))
            meta = conn.execute(
                """SELECT repo_id, full_name, homepage, primary_language, package_ecosystem,
                          package_name, previous_full_names
                   FROM repo_intelligence.github_repositories WHERE repo_id = ANY(%s)""",
                ([r["repo_id"] for r in new_repos],)).fetchall()
            stage("packages", lambda: run_packages(conn, gh, RegistryClient(), meta, scope_label="scope=new",
                                                   today=now.date(), dry_run=args.dry_run))
            stage("showhn", lambda: run_match(conn, hn, meta, scope_label="scope=new", now=now,
                                              dry_run=args.dry_run))
            status = "succeeded"
        finally:
            runs.finish_pipeline_run(conn, run_id, status=status, items_succeeded=totals["ok"],
                                     items_failed=totals["failed"])
    print(f"run_id={run_id} status={status}")
    return 0 if status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())

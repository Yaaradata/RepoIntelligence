#!/usr/bin/env python3
"""Run one Phase 1 stage.

  python scripts/run_stage.py --stage discovery [--lanes new,popular,seed] [--dry-run]
  python scripts/run_stage.py --stage identity --run-id <uuid>
  python scripts/run_stage.py --stage snapshot --scope new|watchlist|run [--run-id <uuid>]
  python scripts/run_stage.py --stage packages --scope new|watchlist|run
  python scripts/run_stage.py --stage showhn --scope new|watchlist|run
  python scripts/run_stage.py --stage showhn_refresh

All Phase 1 stages are free. Paid stages (screen, editorial, selection, digest)
arrive in Phases 4–6 and will refuse to run without --allow-paid.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repo_intelligence.common import config  # noqa: E402
from repo_intelligence.common.db import connect  # noqa: E402
from repo_intelligence.observability import runs  # noqa: E402

STAGES = ["discovery", "identity", "snapshot", "packages", "showhn", "showhn_refresh"]


def repos_for_scope(conn, scope: str, run_id: str | None):
    from repo_intelligence.snapshot.stage import snapshot_scope
    ids = [r["repo_id"] for r in snapshot_scope(conn, scope, run_id=run_id)]
    if not ids:
        return []
    return conn.execute(
        """SELECT repo_id, full_name, homepage, primary_language, package_ecosystem,
                  package_name, previous_full_names
           FROM repo_intelligence.github_repositories WHERE repo_id = ANY(%s) ORDER BY repo_id""",
        (ids,)).fetchall()


def run_one(conn, stage: str, args, run_id: str) -> object:
    now = datetime.now(timezone.utc)
    if stage == "discovery":
        from repo_intelligence.discovery.lanes import run_discovery
        from repo_intelligence.external.github import GitHubClient
        from repo_intelligence.external.hackernews import HNClient
        gh = None if args.dry_run else GitHubClient()
        hn = None if args.dry_run else HNClient()
        return run_discovery(conn, gh, hn, run_id, lanes=args.lanes.split(","), dry_run=args.dry_run)
    if stage == "identity":
        from repo_intelligence.external.github import GitHubClient
        from repo_intelligence.identity.stage import resolve_candidates
        return resolve_candidates(conn, GitHubClient(), args.run_id or run_id)
    if stage == "snapshot":
        from repo_intelligence.external.github import GitHubClient
        from repo_intelligence.snapshot.stage import run_snapshot, snapshot_scope
        weekday = config.setting("snapshot", "fixed_weekday", 6)
        if args.scope == "watchlist" and now.weekday() != weekday and not args.force_weekday:
            raise SystemExit(f"refusing watchlist snapshot: today is weekday {now.weekday()}, "
                             f"fixed snapshot weekday is {weekday} (pass --force-weekday to override)")
        repos = snapshot_scope(conn, args.scope, run_id=args.run_id or run_id)
        gh = None if args.dry_run else GitHubClient()
        return run_snapshot(conn, gh, repos, scope_label=f"scope={args.scope}", now=now, dry_run=args.dry_run)
    if stage == "packages":
        from repo_intelligence.external.github import GitHubClient
        from repo_intelligence.external.registries import RegistryClient
        from repo_intelligence.packages.stage import run_packages
        repos = repos_for_scope(conn, args.scope, args.run_id or run_id)
        gh = None if args.dry_run else GitHubClient()
        return run_packages(conn, gh, RegistryClient(), repos, scope_label=f"scope={args.scope}",
                            today=now.date(), refresh_mapping=args.refresh_mapping, dry_run=args.dry_run)
    if stage == "showhn":
        from repo_intelligence.external.hackernews import HNClient
        from repo_intelligence.showhn.match import run_match
        repos = repos_for_scope(conn, args.scope, args.run_id or run_id)
        return run_match(conn, HNClient(), repos, scope_label=f"scope={args.scope}", now=now, dry_run=args.dry_run)
    if stage == "showhn_refresh":
        from repo_intelligence.external.hackernews import HNClient
        from repo_intelligence.showhn.match import run_refresh
        return run_refresh(conn, HNClient(), now=now, dry_run=args.dry_run)
    raise SystemExit(f"unknown stage {stage}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--scope", default="new", choices=["new", "watchlist", "run"])
    ap.add_argument("--run-id")
    ap.add_argument("--lanes", default="new,popular,seed")
    ap.add_argument("--refresh-mapping", action="store_true")
    ap.add_argument("--force-weekday", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    return ap


def main() -> int:
    args = build_parser().parse_args()
    with connect() as conn:
        run_id = runs.start_pipeline_run(conn, f"stage.{args.stage}", trigger_type=args.trigger,
                                         metadata={"scope": args.scope, "dry_run": args.dry_run})
        stage_run = runs.start_stage_run(conn, run_id, args.stage)
        status = "failed"
        try:
            stats = run_one(conn, args.stage, args, run_id)
            print(stats.summary())
            status = "succeeded"
            runs.finish_stage_run(conn, stage_run, status=status, items_success=stats.succeeded,
                                  items_failed=stats.failed, items_skipped=stats.skipped,
                                  error_summary="; ".join(stats.errors) or None)
            runs.finish_pipeline_run(conn, run_id, status=status, items_input=stats.planned,
                                     items_succeeded=stats.succeeded, items_failed=stats.failed)
        except BaseException as exc:
            conn.rollback()
            runs.finish_stage_run(conn, stage_run, status="failed", error_summary=f"{type(exc).__name__}: {exc}")
            runs.finish_pipeline_run(conn, run_id, status="failed")
            raise
    print(f"run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

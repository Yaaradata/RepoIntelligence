"""Stage 2 — metadata snapshot. One row per repo per UTC day (idempotent)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from repo_intelligence.common import config
from repo_intelligence.common.stats import StageStats
from repo_intelligence.external.github import GitHubClient, GitHubError, commits_in_last_days
from repo_intelligence.identity.stage import upsert_repository
from repo_intelligence.quality_facts.facts import readme_facts, upsert_facts
from repo_intelligence.snapshot.semver import parse_semver

SNAPSHOT_SQL = """
INSERT INTO repo_intelligence.github_repo_snapshots
    (repo_id, captured_at, stars, forks, subscribers, open_issues, open_prs,
     contributors_count, commits_7d, commits_30d, pushed_at, latest_release_tag,
     latest_release_at, release_count, description, topics, languages)
VALUES (%(repo_id)s, %(captured_at)s, %(stars)s, %(forks)s, %(subscribers)s, %(open_issues)s,
        %(open_prs)s, %(contributors_count)s, %(commits_7d)s, %(commits_30d)s, %(pushed_at)s,
        %(latest_release_tag)s, %(latest_release_at)s, %(release_count)s, %(description)s,
        %(topics)s, %(languages)s)
ON CONFLICT (repo_id, captured_date) DO UPDATE SET
    captured_at = EXCLUDED.captured_at, stars = EXCLUDED.stars, forks = EXCLUDED.forks,
    subscribers = EXCLUDED.subscribers, open_issues = EXCLUDED.open_issues,
    open_prs = EXCLUDED.open_prs, contributors_count = EXCLUDED.contributors_count,
    commits_7d = EXCLUDED.commits_7d, commits_30d = EXCLUDED.commits_30d,
    pushed_at = EXCLUDED.pushed_at, latest_release_tag = EXCLUDED.latest_release_tag,
    latest_release_at = EXCLUDED.latest_release_at, release_count = EXCLUDED.release_count,
    description = EXCLUDED.description, topics = EXCLUDED.topics, languages = EXCLUDED.languages
"""

RELEASE_SQL = """
INSERT INTO repo_intelligence.github_repo_releases
    (repo_id, tag, published_at, is_prerelease, semver_major, semver_minor, semver_patch, name, body_excerpt)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (repo_id, tag) DO UPDATE SET
    published_at = EXCLUDED.published_at, is_prerelease = EXCLUDED.is_prerelease,
    name = EXCLUDED.name, body_excerpt = EXCLUDED.body_excerpt
"""


def build_snapshot(repo: dict[str, Any], *, open_prs: int | None, contributors: int | None,
                   releases: list[dict[str, Any]], release_count: int,
                   languages: dict[str, int], weeks: list[dict[str, Any]] | None,
                   now: datetime) -> dict[str, Any]:
    published = [r for r in releases if r.get("published_at") and not r.get("draft")]
    stable = [r for r in published if not r.get("prerelease")] or published
    latest = max(stable, key=lambda r: r["published_at"]) if stable else None
    today = now.date()
    issues_and_prs = repo.get("open_issues_count")
    return {
        "repo_id": int(repo["id"]),
        "captured_at": now,
        "stars": int(repo["stargazers_count"]),
        "forks": int(repo["forks_count"]),
        "subscribers": repo.get("subscribers_count"),      # NOT watchers_count (= stars)
        "open_prs": open_prs,
        "open_issues": (max(0, issues_and_prs - open_prs)
                        if issues_and_prs is not None and open_prs is not None else None),
        "contributors_count": contributors,
        "commits_7d": commits_in_last_days(weeks, 7, today=today) if weeks is not None else None,
        "commits_30d": commits_in_last_days(weeks, 30, today=today) if weeks is not None else None,
        "pushed_at": repo.get("pushed_at"),
        "latest_release_tag": latest["tag_name"] if latest else None,
        "latest_release_at": latest["published_at"] if latest else None,
        "release_count": release_count,
        "description": repo.get("description"),
        "topics": repo.get("topics") or [],
        "languages": json.dumps(languages or {}),
    }


def snapshot_scope(conn, scope: str, *, run_id: str | None = None, today: date | None = None) -> list[dict[str, Any]]:
    """watchlist: every non-excluded repo (fixed weekday only). new: repos never snapshotted.
    run: candidates of one discovery run."""
    if scope == "watchlist":
        sql = """SELECT r.repo_id, r.full_name FROM repo_intelligence.github_repositories r
                 LEFT JOIN repo_intelligence.github_repo_editorial_state s USING (repo_id)
                 WHERE COALESCE(s.watchlist_status, 'active') <> 'excluded'
                 ORDER BY r.repo_id"""
        return conn.execute(sql).fetchall()
    if scope == "new":
        return conn.execute(
            """SELECT r.repo_id, r.full_name FROM repo_intelligence.github_repositories r
               WHERE r.last_snapshot_at IS NULL ORDER BY r.repo_id""").fetchall()
    if scope == "run":
        return conn.execute(
            """SELECT DISTINCT r.repo_id, r.full_name FROM repo_intelligence.github_discovery_candidates c
               JOIN repo_intelligence.github_repositories r USING (repo_id)
               WHERE c.run_id=%s ORDER BY r.repo_id""", (run_id,)).fetchall()
    raise ValueError(f"unknown snapshot scope {scope}")


def run_snapshot(conn, gh: GitHubClient, repos: list[dict[str, Any]], *, scope_label: str,
                 now: datetime | None = None, dry_run: bool = False) -> StageStats:
    now = now or datetime.now(timezone.utc)
    stats = StageStats("snapshot")
    stats.announce(f"{scope_label} date={now.date()} calls/repo≈8", len(repos))
    if dry_run or not repos:
        return stats

    pr_counts = gh.open_pr_counts([tuple(r["full_name"].split("/", 1)) for r in repos])
    per_release = config.setting("snapshot", "releases_per_repo", 10)
    body_chars = config.setting("snapshot", "release_body_chars", 3000)
    excerpt_chars = config.setting("snapshot", "readme_excerpt_chars", 8000)
    retries = config.setting("snapshot", "commit_activity_retries", 3)
    retry_sleep = config.setting("snapshot", "commit_activity_retry_sleep", 2.0)

    for i, row in enumerate(repos, start=1):
        try:
            repo = gh.get_repo_by_id(row["repo_id"])       # by id: survives renames
            if repo is None:
                stats.fail(f"{row['full_name']}: gone (404)")
                continue
            upsert_repository(conn, repo)
            owner, name = repo["owner"]["login"], repo["name"]
            releases = gh.releases(owner, name, per_page=per_release)
            snap = build_snapshot(
                repo,
                open_prs=pr_counts.get(row["full_name"], pr_counts.get(repo["full_name"])),
                contributors=gh.contributors_count(owner, name),
                releases=releases,
                release_count=gh.release_count(owner, name) if len(releases) >= per_release else len(releases),
                languages=gh.languages(owner, name),
                weeks=gh.commit_activity(owner, name, retries=retries, retry_sleep=retry_sleep),
                now=now,
            )
            conn.execute(SNAPSHOT_SQL, snap)
            for rel in releases:
                if not rel.get("published_at") or rel.get("draft"):
                    continue
                major, minor, patch = parse_semver(rel.get("tag_name"))
                conn.execute(RELEASE_SQL, (snap["repo_id"], rel["tag_name"], rel["published_at"],
                                           bool(rel.get("prerelease")), major, minor, patch,
                                           rel.get("name"), (rel.get("body") or "")[:body_chars]))
            upsert_facts(conn, snap["repo_id"], readme_facts(gh.readme(owner, name), excerpt_chars=excerpt_chars))
            conn.execute("UPDATE repo_intelligence.github_repositories SET last_snapshot_at=%s WHERE repo_id=%s",
                         (now, snap["repo_id"]))
            conn.commit()
            stats.succeeded += 1
        except GitHubError as exc:
            conn.rollback()
            stats.fail(f"{row['full_name']}: {exc}")
        stats.progress(i)
    return stats

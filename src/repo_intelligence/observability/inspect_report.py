"""Read-only figures for one collection run.

Every statement in this module is a SELECT. The script that opens the
connection sets the transaction read-only before calling ``collect``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

# Columns a person checks after the first snapshot. A value far below the
# others means that fetch failed quietly, not that the repo lacks the field.
COVERAGE_COLUMNS = (
    "stars",
    "forks",
    "subscribers",
    "open_prs",
    "contributors_count",
    "commits_7d",
    "commits_30d",
    "latest_release_tag",
    "description",
    "topics",
)

# Attached only when the column is under 50%. These are the failure modes
# already observed in the clients, not guesses about a particular run.
COVERAGE_NOTES = {
    "contributors_count": "403 forbidden on large histories",
    "commits_7d": "202 still computing",
    "commits_30d": "202 still computing",
    "latest_release_tag": "genuinely absent when the repo has no release",
}

POINTS_BACK_NOTE = (
    "not stored. A registry entry that links to a different repository is "
    "dropped and nothing is written, so a rejected back-reference cannot be counted."
)

SQL_LATEST_RUN_ID = """
SELECT run_id
FROM repo_intelligence.pipeline_runs
ORDER BY started_at DESC
LIMIT 1
"""

SQL_RUN = """
SELECT run_id, pipeline_name, trigger_type, code_commit_sha, started_at, ended_at,
       status, items_input, items_succeeded, items_failed, total_cost_usd, metadata
FROM repo_intelligence.pipeline_runs
WHERE run_id = %s
"""

SQL_STAGES = """
SELECT stage_name, started_at, ended_at, status, items_input, items_success,
       items_failed, items_skipped, error_summary
FROM repo_intelligence.stage_runs
WHERE run_id = %s
ORDER BY started_at, stage_run_id
"""

SQL_LANES = """
SELECT lane, COUNT(*)::int AS n
FROM repo_intelligence.github_discovery_candidates
WHERE run_id = %s
GROUP BY lane
ORDER BY lane
"""

SQL_SOURCES = """
SELECT lane, source, COUNT(*)::int AS n
FROM repo_intelligence.github_discovery_candidates
WHERE run_id = %s
GROUP BY lane, source
ORDER BY lane, n DESC, source
"""

SQL_RUN_REPO_IDS = """
SELECT DISTINCT repo_id
FROM repo_intelligence.github_discovery_candidates
WHERE run_id = %s AND repo_id IS NOT NULL
ORDER BY repo_id
"""

_COVERAGE_SELECT = """
  COUNT(*)::int AS repos,
  COUNT(s.stars)::int AS stars,
  COUNT(s.forks)::int AS forks,
  COUNT(s.subscribers)::int AS subscribers,
  COUNT(s.open_prs)::int AS open_prs,
  COUNT(s.contributors_count)::int AS contributors_count,
  COUNT(s.commits_7d)::int AS commits_7d,
  COUNT(s.commits_30d)::int AS commits_30d,
  COUNT(s.latest_release_tag)::int AS latest_release_tag,
  COUNT(s.description)::int AS description,
  COUNT(s.topics)::int AS topics
FROM repo_intelligence.github_repositories r
LEFT JOIN LATERAL (
    SELECT stars, forks, subscribers, open_prs, contributors_count,
           commits_7d, commits_30d, latest_release_tag, description, topics
    FROM repo_intelligence.github_repo_snapshots
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) s ON TRUE
"""

SQL_COVERAGE_ALL = "SELECT" + _COVERAGE_SELECT

SQL_COVERAGE_FOR_IDS = "SELECT" + _COVERAGE_SELECT + "WHERE r.repo_id = ANY(%s)\n"

SQL_SHOWHN_SUMMARY = """
SELECT match_strategy,
       COUNT(*)::int AS n,
       COUNT(*) FILTER (WHERE match_confidence >= %s)::int AS above_bar
FROM (
    SELECT DISTINCT ON (repo_id, hn_story_id) match_strategy, match_confidence
    FROM repo_intelligence.github_repo_showhn
    WHERE repo_id = ANY(%s)
    ORDER BY repo_id, hn_story_id, captured_at DESC
) latest
GROUP BY match_strategy
ORDER BY match_strategy
"""

SQL_SHOWHN_LOWEST = """
SELECT r.full_name, h.title, h.match_strategy, h.match_confidence
FROM (
    SELECT DISTINCT ON (repo_id, hn_story_id)
           repo_id, title, match_strategy, match_confidence
    FROM repo_intelligence.github_repo_showhn
    WHERE repo_id = ANY(%s)
    ORDER BY repo_id, hn_story_id, captured_at DESC
) h
JOIN repo_intelligence.github_repositories r USING (repo_id)
ORDER BY h.match_confidence ASC, r.repo_id
LIMIT 10
"""

SQL_PACKAGE_ECOSYSTEMS = """
SELECT package_ecosystem, COUNT(*)::int AS n
FROM repo_intelligence.github_repositories
WHERE repo_id = ANY(%s) AND package_ecosystem IS NOT NULL
GROUP BY package_ecosystem
ORDER BY package_ecosystem
"""

SQL_DOWNLOADS = """
SELECT COUNT(*)::int AS repos,
       COUNT(s.downloads_30d)::int AS with_downloads_30d
FROM repo_intelligence.github_repositories r
LEFT JOIN LATERAL (
    SELECT downloads_30d
    FROM repo_intelligence.github_repo_snapshots
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) s ON TRUE
WHERE r.repo_id = ANY(%s)
"""

SQL_SAMPLE_FOR_IDS = """
SELECT r.repo_id, r.full_name,
       s.stars, s.contributors_count, s.commits_30d, s.latest_release_tag,
       q.readme_length, h.match_confidence
FROM repo_intelligence.github_repositories r
LEFT JOIN LATERAL (
    SELECT stars, contributors_count, commits_30d, latest_release_tag
    FROM repo_intelligence.github_repo_snapshots
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) s ON TRUE
LEFT JOIN repo_intelligence.github_repo_quality_facts q USING (repo_id)
LEFT JOIN LATERAL (
    SELECT match_confidence
    FROM repo_intelligence.github_repo_showhn
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) h ON TRUE
WHERE r.repo_id = ANY(%s)
ORDER BY r.repo_id
LIMIT %s
"""

SQL_SAMPLE_ALL = """
SELECT r.repo_id, r.full_name,
       s.stars, s.contributors_count, s.commits_30d, s.latest_release_tag,
       q.readme_length, h.match_confidence
FROM repo_intelligence.github_repositories r
LEFT JOIN LATERAL (
    SELECT stars, contributors_count, commits_30d, latest_release_tag
    FROM repo_intelligence.github_repo_snapshots
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) s ON TRUE
LEFT JOIN repo_intelligence.github_repo_quality_facts q USING (repo_id)
LEFT JOIN LATERAL (
    SELECT match_confidence
    FROM repo_intelligence.github_repo_showhn
    WHERE repo_id = r.repo_id
    ORDER BY captured_at DESC
    LIMIT 1
) h ON TRUE
ORDER BY r.repo_id
LIMIT %s
"""


def coverage_stat(column: str, present: int, total: int) -> dict[str, Any]:
    """Percentage of repos whose latest snapshot has this column non-NULL."""
    if total <= 0:
        return {"column": column, "present": present, "total": total,
                "pct": None, "flagged": False, "note": None}
    pct = 100.0 * present / total
    flagged = pct < 50.0
    note = None
    if flagged:
        note = COVERAGE_NOTES.get(column) or "below 50%; no known cause recorded"
    return {"column": column, "present": present, "total": total,
            "pct": pct, "flagged": flagged, "note": note}


def coverage_from_counts(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not row:
        return [coverage_stat(column, 0, 0) for column in COVERAGE_COLUMNS]
    total = int(row["repos"])
    return [coverage_stat(column, int(row[column]), total) for column in COVERAGE_COLUMNS]


def format_coverage_line(stat: dict[str, Any]) -> str:
    if stat["pct"] is None:
        return f"{stat['column']:<22}{'n/a':>7}   (0 / 0)"
    flag = f"   <- {stat['note']}" if stat["flagged"] else ""
    return (f"{stat['column']:<22}{stat['pct']:6.1f}%   "
            f"({stat['present']:,} / {stat['total']:,}){flag}")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    return round((end - start).total_seconds(), 1)


def _top_sources(rows: list[dict[str, Any]], n: int = 10) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = grouped.setdefault(row["lane"], [])
        if len(bucket) < n:
            bucket.append({"source": row["source"], "count": int(row["n"])})
    return grouped


def _stage_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_name": row["stage_name"],
        "status": row["status"],
        "started_at": _iso(row["started_at"]),
        "ended_at": _iso(row["ended_at"]),
        "duration_seconds": _seconds(row["started_at"], row["ended_at"]),
        "items_input": row["items_input"],
        "items_success": row["items_success"],
        "items_failed": row["items_failed"],
        "items_skipped": row["items_skipped"],
        "error_summary": row["error_summary"],
    }


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def collect(conn, *, run_id: str | None, coverage_all: bool, sample: int | None,
            confidence_bar: float) -> dict[str, Any]:
    """Run the named SELECT statements. Does not commit."""
    if run_id is None:
        latest = conn.execute(SQL_LATEST_RUN_ID).fetchone()
        if latest is None:
            return {"run": None}
        run_id = str(latest["run_id"])
    run = conn.execute(SQL_RUN, (run_id,)).fetchone()
    if run is None:
        return {"run": None, "missing_run_id": run_id}
    stages = [_stage_record(row) for row in conn.execute(SQL_STAGES, (run_id,)).fetchall()]
    lanes = [{"lane": row["lane"], "count": int(row["n"])}
             for row in conn.execute(SQL_LANES, (run_id,)).fetchall()]
    sources = _top_sources(conn.execute(SQL_SOURCES, (run_id,)).fetchall())
    repo_ids = [int(row["repo_id"]) for row in conn.execute(SQL_RUN_REPO_IDS, (run_id,)).fetchall()]

    if coverage_all:
        coverage_row = conn.execute(SQL_COVERAGE_ALL).fetchone()
        population = "all"
    elif repo_ids:
        coverage_row = conn.execute(SQL_COVERAGE_FOR_IDS, (repo_ids,)).fetchone()
        population = "run"
    else:
        coverage_row = None
        population = "run"

    showhn = {"by_strategy": [], "above_bar": 0, "matches": 0,
              "confidence_bar": confidence_bar, "lowest": []}
    packages = {"by_ecosystem": [], "repos": len(repo_ids), "with_downloads_30d": 0,
                "points_back_rejected": None, "points_back_note": POINTS_BACK_NOTE}
    if repo_ids:
        summary = conn.execute(SQL_SHOWHN_SUMMARY, (confidence_bar, repo_ids)).fetchall()
        showhn["by_strategy"] = [
            {"match_strategy": row["match_strategy"], "count": int(row["n"]),
             "above_bar": int(row["above_bar"])}
            for row in summary
        ]
        showhn["matches"] = sum(item["count"] for item in showhn["by_strategy"])
        showhn["above_bar"] = sum(item["above_bar"] for item in showhn["by_strategy"])
        showhn["lowest"] = [
            {"full_name": row["full_name"], "title": row["title"],
             "match_strategy": row["match_strategy"],
             "match_confidence": _num(row["match_confidence"])}
            for row in conn.execute(SQL_SHOWHN_LOWEST, (repo_ids,)).fetchall()
        ]
        packages["by_ecosystem"] = [
            {"ecosystem": row["package_ecosystem"], "count": int(row["n"])}
            for row in conn.execute(SQL_PACKAGE_ECOSYSTEMS, (repo_ids,)).fetchall()
        ]
        downloads = conn.execute(SQL_DOWNLOADS, (repo_ids,)).fetchone()
        packages["with_downloads_30d"] = int(downloads["with_downloads_30d"]) if downloads else 0

    sample_rows = None
    if sample is not None:
        if coverage_all:
            fetched = conn.execute(SQL_SAMPLE_ALL, (sample,)).fetchall()
        elif repo_ids:
            fetched = conn.execute(SQL_SAMPLE_FOR_IDS, (repo_ids, sample)).fetchall()
        else:
            fetched = []
        sample_rows = [
            {"repo_id": int(row["repo_id"]), "full_name": row["full_name"],
             "stars": row["stars"], "contributors_count": row["contributors_count"],
             "commits_30d": row["commits_30d"], "latest_release_tag": row["latest_release_tag"],
             "readme_length": row["readme_length"],
             "showhn_confidence": _num(row["match_confidence"])}
            for row in fetched
        ]

    return {
        "run": {
            "run_id": str(run["run_id"]),
            "pipeline_name": run["pipeline_name"],
            "trigger_type": run["trigger_type"],
            "code_commit_sha": run["code_commit_sha"],
            "started_at": _iso(run["started_at"]),
            "ended_at": _iso(run["ended_at"]),
            "status": run["status"],
            "items_input": run["items_input"],
            "items_succeeded": run["items_succeeded"],
            "items_failed": run["items_failed"],
            "metadata": run["metadata"],
        },
        "stages": stages,
        "discovery": {"by_lane": lanes, "top_sources": sources, "repos": len(repo_ids)},
        "coverage": {"population": population, "columns": coverage_from_counts(coverage_row)},
        "showhn": showhn,
        "packages": packages,
        "api_spend": {
            "note": "GitHub call counts are not persisted. Durations and item counts are what stage_runs stores.",
            "stages": stages,
        },
        "sample": sample_rows,
    }


def render_text(report: dict[str, Any]) -> str:
    if report.get("run") is None:
        missing = report.get("missing_run_id")
        if missing:
            return f"no pipeline run {missing}\n"
        return "no pipeline runs\n"
    lines: list[str] = []
    run = report["run"]
    lines.append("== run ==")
    lines.append(f"run_id      {run['run_id']}")
    lines.append(f"pipeline    {run['pipeline_name']}")
    lines.append(f"trigger     {run['trigger_type']}")
    lines.append(f"status      {run['status']}")
    lines.append(f"started_at  {run['started_at']}")
    lines.append(f"ended_at    {run['ended_at']}")
    lines.append(f"items       input={run['items_input']} succeeded={run['items_succeeded']} "
                 f"failed={run['items_failed']}")
    lines.append("")
    lines.append("== stages ==")
    if not report["stages"]:
        lines.append("(none)")
    for stage in report["stages"]:
        duration = stage["duration_seconds"]
        spent = f"{duration}s" if duration is not None else "running"
        lines.append(
            f"{stage['stage_name']:<16} {stage['status']:<10} {spent:>8}  "
            f"in={stage['items_input']} ok={stage['items_success']} "
            f"failed={stage['items_failed']} skipped={stage['items_skipped']}"
        )
        if stage["error_summary"]:
            lines.append(f"  error: {stage['error_summary']}")
    lines.append("")
    lines.append("== discovery ==")
    discovery = report["discovery"]
    lines.append(f"repos with id   {discovery['repos']}")
    if not discovery["by_lane"]:
        lines.append("(no candidates for this run)")
    for lane in discovery["by_lane"]:
        lines.append(f"{lane['lane']:<16} {lane['count']:>7}")
        for source in discovery["top_sources"].get(lane["lane"], []):
            lines.append(f"  {source['source']:<40} {source['count']:>7}")
    lines.append("")
    lines.append(f"== field coverage ({report['coverage']['population']}) ==")
    for stat in report["coverage"]["columns"]:
        lines.append(format_coverage_line(stat))
    lines.append("")
    showhn = report["showhn"]
    lines.append("== show hn ==")
    lines.append(f"matches         {showhn['matches']}")
    lines.append(f"above {showhn['confidence_bar']:.2f}     {showhn['above_bar']}")
    if not showhn["by_strategy"]:
        lines.append("(no matches)")
    for row in showhn["by_strategy"]:
        lines.append(f"{row['match_strategy']:<16} {row['count']:>7}  above_bar={row['above_bar']}")
    if showhn["lowest"]:
        lines.append("lowest confidence")
        for row in showhn["lowest"]:
            title = row["title"] or ""
            lines.append(f"  {row['match_confidence']:.2f}  {row['match_strategy']:<12} "
                         f"{row['full_name']}  |  {title}")
    lines.append("")
    packages = report["packages"]
    lines.append("== packages ==")
    mapped = sum(row["count"] for row in packages["by_ecosystem"])
    lines.append(f"mapped          {mapped}")
    lines.append(f"downloads_30d   {packages['with_downloads_30d']}")
    if not packages["by_ecosystem"]:
        lines.append("(no package mapping)")
    for row in packages["by_ecosystem"]:
        lines.append(f"{row['ecosystem']:<16} {row['count']:>7}")
    lines.append(f"points_back     {packages['points_back_note']}")
    lines.append("")
    lines.append("== api spend ==")
    lines.append(report["api_spend"]["note"])
    for stage in report["api_spend"]["stages"]:
        duration = stage["duration_seconds"]
        spent = f"{duration}s" if duration is not None else "running"
        lines.append(f"{stage['stage_name']:<16} {spent:>8}  "
                     f"ok={stage['items_success']} failed={stage['items_failed']} "
                     f"skipped={stage['items_skipped']}")
    if report.get("sample") is not None:
        lines.append("")
        lines.append(f"== sample ({len(report['sample'])}) ==")
        lines.append(f"{'repo_id':<10} {'full_name':<32} {'stars':>8} {'contrib':>8} "
                     f"{'c30':>6} {'release':<16} {'readme':>8} {'hn':>6}")
        for row in report["sample"]:
            hn = "" if row["showhn_confidence"] is None else f"{row['showhn_confidence']:.2f}"
            lines.append(
                f"{row['repo_id']:<10} {str(row['full_name'])[:32]:<32} "
                f"{_cell(row['stars']):>8} {_cell(row['contributors_count']):>8} "
                f"{_cell(row['commits_30d']):>6} {str(row['latest_release_tag'] or '')[:16]:<16} "
                f"{_cell(row['readme_length']):>8} {hn:>6}"
            )
    lines.append("")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return "" if value is None else f"{value}"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str) + "\n"

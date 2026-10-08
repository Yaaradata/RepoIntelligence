"""Stage 4 — Show HN match and +6h/+24h/+48h snapshots.

Every capture is a new row (PK includes captured_at). A capture taken when the
story is between 6h and 24h old fills points_6h; 24–48h fills points_24h /
comments_24h; 48h+ fills points_48h / comments_48h. Run every 6 hours over
stories posted in the last ~54 hours.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from repo_intelligence.common.stats import StageStats
from repo_intelligence.external.hackernews import HNClient, match_story, posted_at

INSERT_SQL = """
INSERT INTO repo_intelligence.github_repo_showhn
    (repo_id, hn_story_id, captured_at, title, story_url, posted_at, author,
     match_strategy, match_confidence, points, comment_count,
     points_6h, points_24h, points_48h, comments_24h, comments_48h)
VALUES (%(repo_id)s, %(hn_story_id)s, %(captured_at)s, %(title)s, %(story_url)s, %(posted_at)s,
        %(author)s, %(match_strategy)s, %(match_confidence)s, %(points)s, %(comment_count)s,
        %(points_6h)s, %(points_24h)s, %(points_48h)s, %(comments_24h)s, %(comments_48h)s)
ON CONFLICT DO NOTHING
"""


def offset_fields(age_hours: float, points: int | None, comments: int | None) -> dict[str, int | None]:
    fields = {"points_6h": None, "points_24h": None, "points_48h": None,
              "comments_24h": None, "comments_48h": None}
    if 6 <= age_hours < 24:
        fields["points_6h"] = points
    elif 24 <= age_hours < 48:
        fields["points_24h"], fields["comments_24h"] = points, comments
    elif age_hours >= 48:
        fields["points_48h"], fields["comments_48h"] = points, comments
    return fields


def capture_row(repo_id: int, story: dict[str, Any], strategy: str, confidence: float,
                now: datetime) -> dict[str, Any]:
    posted = posted_at(story)
    age = (now - posted).total_seconds() / 3600 if posted else 0.0
    points, comments = story.get("points"), story.get("num_comments")
    return {
        "repo_id": repo_id, "hn_story_id": int(story["objectID"]), "captured_at": now,
        "title": story.get("title"), "story_url": story.get("url"), "posted_at": posted,
        "author": story.get("author"), "match_strategy": strategy, "match_confidence": confidence,
        "points": points, "comment_count": comments, **offset_fields(age, points, comments),
    }


def run_match(conn, hn: HNClient, repos: list[dict[str, Any]], *, scope_label: str,
              now: datetime | None = None, dry_run: bool = False) -> StageStats:
    now = now or datetime.now(timezone.utc)
    stats = StageStats("showhn_match")
    stats.announce(scope_label, len(repos))
    if dry_run:
        return stats
    for i, repo in enumerate(repos, start=1):
        owner, name = repo["full_name"].split("/", 1)
        try:
            hits = hn.search_show_hn(f"github.com/{owner}/{name}")
        except Exception as exc:  # noqa: BLE001
            stats.fail(f"{repo['full_name']}: {exc}")
            continue
        matched = 0
        for story in hits:
            m = match_story(story, owner=owner, name=name, homepage=repo.get("homepage"))
            if m:
                conn.execute(INSERT_SQL, capture_row(repo["repo_id"], story, m[0], m[1], now))
                matched += 1
        conn.commit()
        if matched:
            stats.succeeded += 1
        else:
            stats.skipped += 1
        stats.progress(i)
    return stats


def run_refresh(conn, hn: HNClient, *, now: datetime | None = None, window_hours: int = 54,
                dry_run: bool = False) -> StageStats:
    """Re-read points/comments for matched stories posted within window_hours."""
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """SELECT DISTINCT ON (repo_id, hn_story_id) repo_id, hn_story_id, match_strategy, match_confidence
           FROM repo_intelligence.github_repo_showhn
           WHERE posted_at >= %s - make_interval(hours => %s)
           ORDER BY repo_id, hn_story_id, captured_at DESC""",
        (now, window_hours),
    ).fetchall()
    stats = StageStats("showhn_refresh")
    stats.announce(f"stories posted within {window_hours}h", len(rows))
    if dry_run:
        return stats
    for i, row in enumerate(rows, start=1):
        try:
            item = hn.item(row["hn_story_id"])
        except Exception as exc:  # noqa: BLE001
            stats.fail(f"story {row['hn_story_id']}: {exc}")
            continue
        if not item:
            stats.skipped += 1
            continue
        story = {"objectID": item["id"], "title": item.get("title"), "url": item.get("url"),
                 "author": item.get("author"), "created_at_i": item.get("created_at_i"),
                 "points": item.get("points"),
                 "num_comments": sum(1 for _ in _iter_comments(item))}
        conn.execute(INSERT_SQL, capture_row(row["repo_id"], story, row["match_strategy"],
                                             float(row["match_confidence"]), now))
        conn.commit()
        stats.succeeded += 1
        stats.progress(i)
    return stats


def _iter_comments(node: dict[str, Any]):
    for child in node.get("children") or []:
        if child.get("type") == "comment":
            yield child
        yield from _iter_comments(child)

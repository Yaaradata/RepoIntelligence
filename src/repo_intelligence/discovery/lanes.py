"""Stage 0 — discovery lanes A (new), D (recently popular), E (seeded).

Lanes B (accelerating) and C (established) are queries over our own snapshots
and releases; they arrive in Phase 2 once two weekly snapshots exist.

GitHub search ANDs repeated `topic:` qualifiers, so a topic group such as
"topic:ai topic:machine-learning topic:llm" is expanded to one query per topic.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Iterable

from repo_intelligence.common import config
from repo_intelligence.common.stats import StageStats
from repo_intelligence.external.github import GitHubClient
from repo_intelligence.external.hackernews import HNClient
from repo_intelligence.identity.stage import upsert_repository

GITHUB_SLUG = re.compile(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?(?:$|[/#?])")


def topics() -> list[str]:
    seen: list[str] = []
    for group in config.setting("discovery", "topic_groups", []):
        for token in group.split():
            if token.startswith("topic:") and token not in seen:
                seen.append(token)
    return seen


def lane_a_queries(today: date) -> list[str]:
    created = today - timedelta(days=config.setting("discovery", "new_lane_created_within_days", 30))
    pushed = today - timedelta(days=config.setting("discovery", "new_lane_pushed_within_days", 7))
    min_stars = config.setting("discovery", "min_stars_new_lane", 3)
    return [f"created:>={created} pushed:>={pushed} stars:>={min_stars} is:public fork:false {t}"
            for t in topics()]


def lane_d_queries(today: date) -> list[str]:
    pushed = today - timedelta(days=config.setting("discovery", "popular_pushed_within_days", 14))
    min_stars = config.setting("discovery", "popular_min_stars", 2000)
    return [f"stars:>={min_stars} pushed:>={pushed} is:public fork:false archived:false {t}"
            for t in topics()]


def slug_from_url(url: str | None) -> str | None:
    match = GITHUB_SLUG.search(url or "")
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _insert_candidate(conn, run_id: str, lane: str, source: str, *, repo_id: int | None = None,
                      hint: str | None = None, evidence: dict[str, Any] | None = None) -> None:
    conn.execute(
        """INSERT INTO repo_intelligence.github_discovery_candidates
           (run_id, lane, source, full_name_hint, repo_id, evidence)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (run_id, lane, source, hint, repo_id, json.dumps(evidence or {})),
    )


def _run_search_lane(conn, gh: GitHubClient, run_id: str, lane: str, queries: Iterable[str],
                     stats: StageStats, seen: set[int]) -> None:
    cap = config.setting("discovery", "search_result_cap", 1000)
    for query in queries:
        n = 0
        for item in gh.search_repositories(query, cap=cap):
            n += 1
            upsert_repository(conn, item)           # search items carry the full repo payload
            repo_id = int(item["id"])
            _insert_candidate(conn, run_id, lane, f"search:{query.split()[-1]}", repo_id=repo_id,
                              hint=item["full_name"],
                              evidence={"stars_at_discovery": item.get("stargazers_count"),
                                        "pushed_at": item.get("pushed_at")})
            if repo_id not in seen:
                seen.add(repo_id)
                stats.succeeded += 1
        conn.commit()
        print(f"  lane={lane} query='{query}' results={n} unique_so_far={len(seen)}", flush=True)


def run_discovery(conn, gh: GitHubClient | None, hn: HNClient | None, run_id: str, *,
                  lanes: Iterable[str] = ("new", "popular", "seed"), today: date | None = None,
                  dry_run: bool = False) -> StageStats:
    today = today or date.today()
    lanes = list(lanes)
    stats = StageStats("discovery")
    plan: list[tuple[str, list[str]]] = []
    if "new" in lanes:
        plan.append(("new", lane_a_queries(today)))
    if "popular" in lanes:
        plan.append(("popular", lane_d_queries(today)))
    nominations = config.seeds().get("nominations") or []
    n_queries = sum(len(q) for _, q in plan)
    stats.announce(f"lanes={','.join(lanes)} search_queries={n_queries} "
                   f"seeds={len(nominations) if 'seed' in lanes else 0} "
                   f"max_search_calls={n_queries * 10}", n_queries)
    if dry_run:
        for lane, queries in plan:
            for q in queries:
                print(f"  DRY lane={lane} q='{q}'")
        return stats

    seen: set[int] = set()
    for lane, queries in plan:
        _run_search_lane(conn, gh, run_id, lane, queries, stats, seen)

    if "seed" in lanes:
        for entry in nominations:
            slug = (entry.get("repo") or "").strip()
            if slug:
                _insert_candidate(conn, run_id, "seed", "seeds.yaml", hint=slug,
                                  evidence={k: v for k, v in entry.items() if k != "repo"})
                stats.succeeded += 1
        if hn is not None:
            for story in hn.front_page_show_hn():
                slug = slug_from_url(story.get("url"))
                if slug:
                    _insert_candidate(conn, run_id, "seed", "showhn_front", hint=slug,
                                      evidence={"hn_story_id": int(story["objectID"]),
                                                "title": story.get("title")})
                    stats.succeeded += 1
        conn.commit()
    return stats

"""Stage 1 — canonical identity. Keyed on GitHub's numeric repo id, never owner/name."""

from __future__ import annotations

from typing import Any

from repo_intelligence.common.stats import StageStats
from repo_intelligence.external.github import GitHubClient, GitHubError

UPSERT_SQL = """
INSERT INTO repo_intelligence.github_repositories
    (repo_id, owner, name, full_name, description, homepage, html_url, created_at,
     primary_language, licence_key, is_fork, is_archived)
VALUES (%(repo_id)s, %(owner)s, %(name)s, %(full_name)s, %(description)s, %(homepage)s,
        %(html_url)s, %(created_at)s, %(primary_language)s, %(licence_key)s,
        %(is_fork)s, %(is_archived)s)
ON CONFLICT (repo_id) DO UPDATE SET
    owner = EXCLUDED.owner,
    name = EXCLUDED.name,
    full_name = EXCLUDED.full_name,
    description = EXCLUDED.description,
    homepage = EXCLUDED.homepage,
    html_url = EXCLUDED.html_url,
    primary_language = EXCLUDED.primary_language,
    licence_key = EXCLUDED.licence_key,
    is_fork = EXCLUDED.is_fork,
    is_archived = EXCLUDED.is_archived,
    previous_full_names = CASE
        WHEN github_repositories.full_name <> EXCLUDED.full_name
             AND NOT (github_repositories.full_name = ANY(COALESCE(github_repositories.previous_full_names, '{}')))
        THEN array_append(COALESCE(github_repositories.previous_full_names, '{}'), github_repositories.full_name)
        ELSE github_repositories.previous_full_names
    END
RETURNING repo_id, (xmax = 0) AS inserted, previous_full_names
"""


def identity_row(repo: dict[str, Any]) -> dict[str, Any]:
    """Map a GitHub repository payload (REST or search item) to github_repositories columns."""
    licence = repo.get("license") or {}
    key = licence.get("key")
    return {
        "repo_id": int(repo["id"]),
        "owner": repo["owner"]["login"],
        "name": repo["name"],
        "full_name": repo["full_name"],
        "description": repo.get("description"),
        "homepage": repo.get("homepage") or None,
        "html_url": repo["html_url"],
        "created_at": repo["created_at"],
        "primary_language": repo.get("language"),
        "licence_key": None if key in (None, "other", "noassertion") else key,
        "is_fork": bool(repo.get("fork")),
        "is_archived": bool(repo.get("archived")),
    }


def upsert_repository(conn, repo: dict[str, Any]) -> dict[str, Any]:
    """Insert or refresh identity. A changed full_name is recorded as a rename."""
    return conn.execute(UPSERT_SQL, identity_row(repo)).fetchone()


def resolve_candidates(conn, gh: GitHubClient, run_id: str) -> StageStats:
    """Give every candidate in the run a repo_id; fetch identity for hint-only candidates."""
    stats = StageStats("identity")
    pending = conn.execute(
        """SELECT candidate_id, full_name_hint FROM repo_intelligence.github_discovery_candidates
           WHERE run_id=%s AND repo_id IS NULL""",
        (run_id,),
    ).fetchall()
    stats.announce(f"run={run_id[:8]} unresolved candidates", len(pending))
    for i, row in enumerate(pending, start=1):
        hint = (row["full_name_hint"] or "").strip("/")
        if hint.count("/") != 1:
            stats.fail(f"bad hint {hint!r}")
            continue
        owner, name = hint.split("/")
        try:
            repo = gh.get_repo(owner, name)   # follows 301 → destination id
        except GitHubError as exc:
            stats.fail(f"{hint}: {exc}")
            continue
        if repo is None:
            stats.fail(f"{hint}: not found")
            continue
        upsert_repository(conn, repo)
        conn.execute(
            "UPDATE repo_intelligence.github_discovery_candidates SET repo_id=%s WHERE candidate_id=%s",
            (int(repo["id"]), row["candidate_id"]),
        )
        conn.commit()
        stats.succeeded += 1
        stats.progress(i)
    return stats

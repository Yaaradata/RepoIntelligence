"""Stage 3 — map repo → package and record downloads on today's snapshot.

Downloads are a display field and an adoption signal. Like stars, they are
never shown to the screen or editorial model.

Acceptance rule: a candidate package is accepted only if the registry entry
links back to github.com/{owner}/{name} (or any previous name). A manifest
name whose registry entry has no source link at all is also accepted; a
manifest or name match whose registry entry links elsewhere is rejected.
"""

from __future__ import annotations

import json
import re
import tomllib
from datetime import date, datetime, timezone
from typing import Any

from repo_intelligence.common.stats import StageStats
from repo_intelligence.external.github import GitHubClient, GitHubError
from repo_intelligence.external.registries import RegistryClient

HOMEPAGE_PATTERNS = [
    ("npm", re.compile(r"npmjs\.com/package/((?:@[^/]+/)?[^/?#]+)")),
    ("pypi", re.compile(r"pypi\.org/project/([^/?#]+)")),
    ("crates", re.compile(r"crates\.io/crates/([^/?#]+)")),
    ("docker", re.compile(r"hub\.docker\.com/r/([^/?#]+/[^/?#]+)")),
]
LANGUAGE_ECOSYSTEM = {"JavaScript": "npm", "TypeScript": "npm", "Python": "pypi", "Rust": "crates"}


def manifest_candidates(gh: GitHubClient, owner: str, name: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    text = gh.file_text(owner, name, "package.json")
    if text:
        try:
            doc = json.loads(text)
            if doc.get("name") and not doc.get("private"):
                out.append(("npm", doc["name"]))
        except json.JSONDecodeError:
            pass
    text = gh.file_text(owner, name, "pyproject.toml")
    if text:
        try:
            doc = tomllib.loads(text)
            pkg = (doc.get("project") or {}).get("name") or \
                ((doc.get("tool") or {}).get("poetry") or {}).get("name")
            if pkg:
                out.append(("pypi", pkg))
        except tomllib.TOMLDecodeError:
            pass
    text = gh.file_text(owner, name, "Cargo.toml")
    if text:
        try:
            pkg = (tomllib.loads(text).get("package") or {}).get("name")
            if pkg:
                out.append(("crates", pkg))
        except tomllib.TOMLDecodeError:
            pass
    return out


def homepage_candidates(homepage: str | None) -> list[tuple[str, str]]:
    out = []
    for ecosystem, pattern in HOMEPAGE_PATTERNS:
        match = pattern.search(homepage or "")
        if match:
            out.append((ecosystem, match.group(1)))
    return out


def _links_back(reg: RegistryClient, ecosystem: str, package: str,
                slugs: list[tuple[str, str]]) -> bool | None:
    """True if any slug matches; False if the registry links elsewhere / nowhere; None if missing."""
    result: bool | None = None
    for owner, name in slugs:
        hit = reg.points_back(ecosystem, package, owner, name)
        if hit is None:
            return None
        if hit:
            return True
        result = False
    return result


def resolve_package(gh: GitHubClient, reg: RegistryClient, repo: dict[str, Any]) -> tuple[str, str, str] | None:
    """(ecosystem, package, strategy) or None."""
    owner, name = repo["full_name"].split("/", 1)
    slugs = [(owner, name)] + [tuple(p.split("/", 1)) for p in (repo.get("previous_full_names") or [])]

    for ecosystem, package in manifest_candidates(gh, owner, name):
        verdict = _links_back(reg, ecosystem, package, slugs)
        if verdict:
            return ecosystem, package, "manifest"
        if verdict is False and not any(u for u in (reg.repository_urls(ecosystem, package) or [])
                                        if "github.com" in u.lower()):
            return ecosystem, package, "manifest"   # registry records no source link at all
    for ecosystem, package in homepage_candidates(repo.get("homepage")):
        if _links_back(reg, ecosystem, package, slugs) is not None:   # maintainer's own link; must exist
            return ecosystem, package, "homepage"
    ecosystem = LANGUAGE_ECOSYSTEM.get(repo.get("primary_language") or "")
    if ecosystem and _links_back(reg, ecosystem, name.lower(), slugs):
        return ecosystem, name.lower(), "name_verified"
    return None


def run_packages(conn, gh: GitHubClient, reg: RegistryClient, repos: list[dict[str, Any]], *,
                 scope_label: str, today: date | None = None, refresh_mapping: bool = False,
                 dry_run: bool = False) -> StageStats:
    today = today or datetime.now(timezone.utc).date()
    stats = StageStats("packages")
    stats.announce(f"{scope_label} date={today} refresh_mapping={refresh_mapping}", len(repos))
    if dry_run:
        return stats
    for i, repo in enumerate(repos, start=1):
        try:
            ecosystem, package = repo.get("package_ecosystem"), repo.get("package_name")
            if refresh_mapping or not ecosystem:
                found = resolve_package(gh, reg, repo)
                if found:
                    ecosystem, package, strategy = found
                    conn.execute(
                        """UPDATE repo_intelligence.github_repositories
                           SET package_ecosystem=%s, package_name=%s, package_match_strategy=%s
                           WHERE repo_id=%s""", (ecosystem, package, strategy, repo["repo_id"]))
            if not ecosystem:
                stats.skipped += 1
                conn.commit()
                continue
            d7, d30 = reg.downloads(ecosystem, package, today=today)
            conn.execute(
                """UPDATE repo_intelligence.github_repo_snapshots SET downloads_7d=%s, downloads_30d=%s
                   WHERE repo_id=%s AND captured_date=%s""", (d7, d30, repo["repo_id"], today))
            conn.commit()
            stats.succeeded += 1
        except (GitHubError, Exception) as exc:  # noqa: BLE001 — registry outages must not stop the stage
            conn.rollback()
            stats.fail(f"{repo['full_name']}: {type(exc).__name__}: {exc}")
        stats.progress(i)
    return stats

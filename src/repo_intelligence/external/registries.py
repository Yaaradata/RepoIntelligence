"""npm / PyPI / crates.io / Docker Hub: package lookup, back-reference check, downloads.

All endpoints are free and unauthenticated. Paced at REGISTRY_RATE_SLEEP with a
User-Agent identifying the project (pypistats requires one).
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, Callable

import requests

from repo_intelligence.common import config
from repo_intelligence.external.hackernews import github_slug_in


class RegistryClient:
    def __init__(self, *, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep, rate_sleep: float | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.HTTP_USER_AGENT, "Accept": "application/json"})
        self._sleep = sleep
        self.rate_sleep = config.REGISTRY_RATE_SLEEP if rate_sleep is None else rate_sleep

    def _get(self, url: str) -> Any:
        self._sleep(self.rate_sleep)
        resp = self.session.get(url, timeout=30)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        return resp.json()

    # ── metadata: where does the registry say the source lives? ──────
    def repository_urls(self, ecosystem: str, package: str) -> list[str] | None:
        """Source URLs the registry records for a package; None if the package does not exist."""
        if ecosystem == "npm":
            doc = self._get(f"{config.NPM_REGISTRY_BASE}/{package.replace('/', '%2F')}")
            if doc is None:
                return None
            repo = doc.get("repository")
            urls = [repo.get("url") if isinstance(repo, dict) else repo, doc.get("homepage")]
            bugs = doc.get("bugs")
            urls.append(bugs.get("url") if isinstance(bugs, dict) else None)
            return [u for u in urls if u]
        if ecosystem == "pypi":
            doc = self._get(f"{config.PYPI_JSON_BASE}/{package}/json")
            if doc is None:
                return None
            info = doc.get("info") or {}
            urls = list((info.get("project_urls") or {}).values()) + [info.get("home_page")]
            return [u for u in urls if u]
        if ecosystem == "crates":
            doc = self._get(f"{config.CRATES_API_BASE}/crates/{package}")
            if doc is None:
                return None
            crate = doc.get("crate") or {}
            return [u for u in (crate.get("repository"), crate.get("homepage")) if u]
        if ecosystem == "docker":
            doc = self._get(f"{config.DOCKERHUB_API_BASE}/repositories/{package}")
            if doc is None:
                return None
            # Docker Hub has no structured source field; the description may link it.
            return [doc.get("full_description") or "", doc.get("description") or ""]
        raise ValueError(f"unknown ecosystem {ecosystem}")

    def points_back(self, ecosystem: str, package: str, owner: str, name: str) -> bool | None:
        """True if the registry links to github.com/owner/name; None if the package is missing."""
        urls = self.repository_urls(ecosystem, package)
        if urls is None:
            return None
        if ecosystem == "docker":
            return any(f"github.com/{owner.lower()}/{name.lower()}" in u.lower() for u in urls)
        return any(github_slug_in(u, owner, name) for u in urls)

    # ── downloads ─────────────────────────────────────────────────────
    def downloads(self, ecosystem: str, package: str, *, today: date | None = None) -> tuple[int | None, int | None]:
        """(downloads_7d, downloads_30d). Docker exposes only lifetime pulls → (None, None)."""
        today = today or date.today()
        if ecosystem == "npm":
            week = self._get(f"{config.NPM_API_BASE}/downloads/point/last-week/{package}")
            month = self._get(f"{config.NPM_API_BASE}/downloads/point/last-month/{package}")
            return (week or {}).get("downloads"), (month or {}).get("downloads")
        if ecosystem == "pypi":
            data = (self._get(f"{config.PYPI_STATS_BASE}/packages/{package.lower()}/recent") or {}).get("data") or {}
            return data.get("last_week"), data.get("last_month")
        if ecosystem == "crates":
            # /crates/{c} only offers lifetime and 90-day counts; daily series gives 7d/30d.
            doc = self._get(f"{config.CRATES_API_BASE}/crates/{package}/downloads") or {}
            per_day: dict[str, int] = {}
            for row in doc.get("version_downloads") or []:
                per_day[row["date"]] = per_day.get(row["date"], 0) + int(row["downloads"])
            for row in (doc.get("meta") or {}).get("extra_downloads") or []:
                per_day[row["date"]] = per_day.get(row["date"], 0) + int(row["downloads"])
            if not per_day:
                return None, None

            def window(days: int) -> int:
                start = (today - timedelta(days=days)).isoformat()
                return sum(v for d, v in per_day.items() if start < d <= today.isoformat())

            return window(7), window(30)
        if ecosystem == "docker":
            return None, None
        raise ValueError(f"unknown ecosystem {ecosystem}")

"""Hacker News via the Algolia API (no key)."""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from repo_intelligence.common import config

CONFIDENCE = {"url_exact": 1.00, "homepage": 0.70, "title_text": 0.40}


class HNClient:
    def __init__(self, *, base_url: str | None = None, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep, rate_sleep: float | None = None):
        self.base_url = (base_url or config.HN_API_BASE).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.HTTP_USER_AGENT})
        self._sleep = sleep
        self.rate_sleep = config.HN_RATE_SLEEP if rate_sleep is None else rate_sleep

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._sleep(self.rate_sleep)
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def search_show_hn(self, query: str) -> list[dict[str, Any]]:
        data = self._get("/search", {"query": query, "tags": "show_hn", "hitsPerPage": 50})
        return (data or {}).get("hits") or []

    def front_page_show_hn(self) -> list[dict[str, Any]]:
        data = self._get("/search", {"tags": "show_hn,front_page", "hitsPerPage": 100})
        return (data or {}).get("hits") or []

    def item(self, story_id: int) -> dict[str, Any] | None:
        return self._get(f"/items/{int(story_id)}")


def _norm_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.rstrip("/")


def github_slug_in(url: str | None, owner: str, name: str) -> bool:
    """True if url points at github.com/{owner}/{name} exactly (not a longer repo name)."""
    pattern = rf"github\.com/{re.escape(owner.lower())}/{re.escape(name.lower())}(?:$|[/#?]|\.git)"
    return re.search(pattern, _norm_url(url)) is not None


def match_story(story: dict[str, Any], *, owner: str, name: str, homepage: str | None) -> tuple[str, float] | None:
    """Classify an Algolia hit against a repo. Returns (strategy, confidence) or None."""
    url = story.get("url")
    if github_slug_in(url, owner, name):
        return "url_exact", CONFIDENCE["url_exact"]
    if homepage and url and _norm_url(url) == _norm_url(homepage):
        return "homepage", CONFIDENCE["homepage"]
    title = (story.get("title") or "").lower()
    if len(name) >= 4 and re.search(rf"\b{re.escape(name.lower())}\b", title):
        return "title_text", CONFIDENCE["title_text"]
    return None


def posted_at(story: dict[str, Any]) -> datetime | None:
    ts = story.get("created_at_i")
    return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None


def flatten_comments(item: dict[str, Any], *, limit: int = 30, max_chars: int = 500) -> list[str]:
    """Comment texts, top-level first (Algolia exposes no comment scores), HTML stripped."""
    levels: list[list[str]] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        for child in node.get("children") or []:
            text = child.get("text")
            if text and child.get("type") == "comment":
                while len(levels) <= depth:
                    levels.append([])
                clean = html.unescape(re.sub(r"<[^>]+>", " ", text))
                levels[depth].append(re.sub(r"\s+", " ", clean).strip()[:max_chars])
            walk(child, depth + 1)

    walk(item, 0)
    return [c for level in levels for c in level][:limit]


def count_comments(item: dict[str, Any]) -> int:
    return sum(1 + count_comments(c) for c in item.get("children") or [] if c.get("type") == "comment")

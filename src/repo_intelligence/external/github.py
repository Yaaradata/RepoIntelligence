"""GitHub REST + GraphQL client.

Rate limiting lives here, not in callers: every response's X-RateLimit-*
headers are read, and when the remaining budget for that resource drops below
its floor the client sleeps until X-RateLimit-Reset. Search (30/min) is paced
separately from core REST (5,000/h).

API traps handled here:
  * watchers_count duplicates stargazers_count → callers use subscribers_count.
  * open_issues_count includes PRs → open_pr_counts() supplies the PR count.
  * /stats/commit_activity answers 202 while GitHub computes → retried, then None.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator

import requests

from repo_intelligence.common import config

log = logging.getLogger(__name__)

# Sleep until reset when remaining falls below this, per resource.
RATE_FLOOR = {"core": 100, "graphql": 100, "search": 2}
MAX_ATTEMPTS = 4
GRAPHQL_BATCH = 40


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub HTTP {status}: {message}")
        self.status = status


def _last_page(link_header: str | None) -> int | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="last"' in part:
            match = re.search(r"[?&]page=(\d+)", part)
            if match:
                return int(match.group(1))
    return None


def commits_in_last_days(weeks: list[dict[str, Any]], days: int, *, today: date) -> int:
    """Sum per-day commit counts from /stats/commit_activity over (today-days, today]."""
    start = today - timedelta(days=days)
    total = 0
    for week in weeks:
        week_start = datetime.fromtimestamp(int(week["week"]), tz=timezone.utc).date()
        for offset, count in enumerate(week.get("days") or []):
            day = week_start + timedelta(days=offset)
            if start < day <= today:
                total += int(count)
    return total


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        rate_sleep: float | None = None,
        search_sleep: float | None = None,
    ):
        token = token if token is not None else config.env("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN is not set")
        self.base_url = (base_url or config.GITHUB_API_BASE).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": config.HTTP_USER_AGENT,
        })
        self._sleep = sleep
        self._clock = clock
        self.rate_sleep = config.GITHUB_RATE_SLEEP if rate_sleep is None else rate_sleep
        self.search_sleep = config.GITHUB_SEARCH_SLEEP if search_sleep is None else search_sleep
        self.calls = {"core": 0, "search": 0, "graphql": 0}
        self.remaining: dict[str, int] = {}

    # ── transport ─────────────────────────────────────────────────────
    def _respect_rate_limit(self, resp: requests.Response, resource: str) -> None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")
        resource = resp.headers.get("X-RateLimit-Resource", resource)
        if remaining is None:
            return
        self.remaining[resource] = int(remaining)
        if int(remaining) < RATE_FLOOR.get(resource, 100) and reset:
            wait = max(0.0, float(reset) - self._clock()) + 1.0
            log.warning("github %s remaining=%s — sleeping %.0fs until reset", resource, remaining, wait)
            self._sleep(wait)

    def _request(
        self,
        method: str,
        path: str,
        *,
        resource: str = "core",
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept_202: bool = False,
    ) -> requests.Response | None:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._sleep(self.search_sleep if resource == "search" else self.rate_sleep)
            resp = self.session.request(method, url, params=params, json=json_body,
                                        headers=headers, timeout=30)
            self.calls[resource] = self.calls.get(resource, 0) + 1
            self._respect_rate_limit(resp, resource)
            if resp.status_code == 202 and accept_202:
                return resp
            if resp.status_code in (200, 201):
                return resp
            if resp.status_code in (204, 404, 409, 451):
                return None   # empty repo / not found / blocked
            retry_after = resp.headers.get("Retry-After")
            exhausted = resp.headers.get("X-RateLimit-Remaining") == "0"
            if resp.status_code in (403, 429) and (retry_after or exhausted):
                if retry_after:
                    wait = float(retry_after)
                else:
                    wait = max(0.0, float(resp.headers.get("X-RateLimit-Reset", self._clock() + 60)) - self._clock()) + 1.0
                log.warning("github secondary/primary limit on %s — sleeping %.0fs", path, wait)
                self._sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < MAX_ATTEMPTS:
                self._sleep(2.0 ** attempt)
                continue
            raise GitHubError(resp.status_code, resp.text[:300])
        raise GitHubError(0, f"gave up after {MAX_ATTEMPTS} attempts: {path}")

    def _get_json(self, path: str, **kwargs: Any) -> Any:
        resp = self._request("GET", path, **kwargs)
        return None if resp is None else resp.json()

    # ── repositories ──────────────────────────────────────────────────
    def get_repo(self, owner: str, name: str) -> dict[str, Any] | None:
        """Follows 301 renames/transfers; the returned `id` is the destination repo."""
        return self._get_json(f"/repos/{owner}/{name}")

    def get_repo_by_id(self, repo_id: int) -> dict[str, Any] | None:
        return self._get_json(f"/repositories/{int(repo_id)}")

    def search_repositories(self, query: str, *, sort: str = "stars", cap: int = 1000) -> Iterator[dict[str, Any]]:
        """Paginate a search to GitHub's 1,000-result cap (10 pages x 100)."""
        fetched = 0
        page = 1
        while fetched < cap:
            data = self._get_json("/search/repositories", resource="search",
                                  params={"q": query, "sort": sort, "order": "desc",
                                          "per_page": 100, "page": page})
            items = (data or {}).get("items") or []
            for item in items:
                yield item
                fetched += 1
                if fetched >= cap:
                    return
            if len(items) < 100:
                return
            page += 1

    def contributors_count(self, owner: str, name: str) -> int | None:
        """One call: per_page=1 and read the last page number from the Link header."""
        try:
            resp = self._request("GET", f"/repos/{owner}/{name}/contributors",
                                 params={"per_page": 1, "anon": "false"})
        except GitHubError as exc:
            if exc.status == 403:   # history too large to list
                return None
            raise
        if resp is None:
            return 0
        last = _last_page(resp.headers.get("Link"))
        return last if last is not None else len(resp.json() or [])

    def releases(self, owner: str, name: str, per_page: int = 10) -> list[dict[str, Any]]:
        return self._get_json(f"/repos/{owner}/{name}/releases", params={"per_page": per_page}) or []

    def release_count(self, owner: str, name: str) -> int:
        resp = self._request("GET", f"/repos/{owner}/{name}/releases", params={"per_page": 1})
        if resp is None:
            return 0
        last = _last_page(resp.headers.get("Link"))
        return last if last is not None else len(resp.json() or [])

    def languages(self, owner: str, name: str) -> dict[str, int]:
        return self._get_json(f"/repos/{owner}/{name}/languages") or {}

    def readme(self, owner: str, name: str) -> str | None:
        data = self._get_json(f"/repos/{owner}/{name}/readme")
        if not data or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def file_text(self, owner: str, name: str, path: str) -> str | None:
        data = self._get_json(f"/repos/{owner}/{name}/contents/{path}")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def root_listing(self, owner: str, name: str, path: str = "") -> list[str]:
        data = self._get_json(f"/repos/{owner}/{name}/contents/{path}")
        return [item["name"] for item in data] if isinstance(data, list) else []

    def commit_activity(
        self, owner: str, name: str, *, retries: int = 3, retry_sleep: float = 2.0
    ) -> list[dict[str, Any]] | None:
        """52 weeks of per-day commits; None if GitHub is still computing after retries."""
        for _ in range(retries + 1):
            resp = self._request("GET", f"/repos/{owner}/{name}/stats/commit_activity", accept_202=True)
            if resp is None:
                return None
            if resp.status_code == 200:
                body = resp.json()
                return body if isinstance(body, list) else None
            self._sleep(retry_sleep)
        return None

    # ── GraphQL ───────────────────────────────────────────────────────
    def open_pr_counts(self, repos: Iterable[tuple[str, str]]) -> dict[str, int | None]:
        """Open PR count per 'owner/name', batched GRAPHQL_BATCH per query.

        Replaces one search-API call per repo (30/min) with one GraphQL call
        per 40 repos.
        """
        repos = list(repos)
        out: dict[str, int | None] = {}
        for i in range(0, len(repos), GRAPHQL_BATCH):
            chunk = repos[i:i + GRAPHQL_BATCH]
            parts = []
            for j, (owner, name) in enumerate(chunk):
                parts.append(
                    f'r{j}: repository(owner: {_gql_str(owner)}, name: {_gql_str(name)}) '
                    "{ pullRequests(states: OPEN) { totalCount } }"
                )
            resp = self._request("POST", f"{self.base_url}/graphql", resource="graphql",
                                 json_body={"query": "query {" + " ".join(parts) + "}"})
            data = ((resp.json() if resp is not None else {}) or {}).get("data") or {}
            for j, (owner, name) in enumerate(chunk):
                node = data.get(f"r{j}")
                out[f"{owner}/{name}"] = (node or {}).get("pullRequests", {}).get("totalCount") if node else None
        return out


def _gql_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

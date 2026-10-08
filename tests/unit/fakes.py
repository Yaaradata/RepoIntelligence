"""Scripted HTTP session for client tests."""

from __future__ import annotations

import json
from typing import Any


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None, headers: dict[str, str] | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns queued responses; records every request."""

    def __init__(self, responses: list[FakeResponse] | None = None, routes: dict[str, Any] | None = None):
        self.queue = list(responses or [])
        self.routes = routes or {}
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def _route(self, url: str) -> FakeResponse:
        for fragment, resp in self.routes.items():
            if fragment in url:
                return resp if isinstance(resp, FakeResponse) else FakeResponse(200, resp)
        return FakeResponse(404, {"message": "Not Found"})

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.queue.pop(0) if self.queue else self._route(url)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("GET", url, **kwargs)

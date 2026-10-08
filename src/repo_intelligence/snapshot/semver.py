"""Lenient semver parsing for release tags (v1.2.3, release-2.0, 1.4.0-rc1)."""

from __future__ import annotations

import re

SEMVER_RE = re.compile(r"(?<![\d.])v?(\d+)\.(\d+)(?:\.(\d+))?")


def parse_semver(tag: str | None) -> tuple[int | None, int | None, int | None]:
    match = SEMVER_RE.search(tag or "")
    if not match:
        return None, None, None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch) if patch is not None else 0

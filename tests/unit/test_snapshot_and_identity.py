from datetime import datetime, timezone

from repo_intelligence.identity.stage import identity_row
from repo_intelligence.snapshot.semver import parse_semver
from repo_intelligence.snapshot.stage import build_snapshot

REPO = {
    "id": 42, "name": "tool", "full_name": "acme/tool", "owner": {"login": "acme"},
    "html_url": "https://github.com/acme/tool", "created_at": "2026-01-01T00:00:00Z",
    "stargazers_count": 900, "watchers_count": 900, "subscribers_count": 31,
    "forks_count": 12, "open_issues_count": 20, "pushed_at": "2026-10-01T00:00:00Z",
    "license": {"key": "mit"}, "topics": ["cli"], "language": "Go", "description": "d",
}
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def snap(**kw):
    base = dict(open_prs=8, contributors=5, releases=[], release_count=0, languages={}, weeks=None, now=NOW)
    base.update(kw)
    return build_snapshot(REPO, **base)


def test_subscribers_not_watchers():
    assert snap()["subscribers"] == 31


def test_open_issues_excludes_prs():
    s = snap()
    assert (s["open_issues"], s["open_prs"]) == (12, 8)


def test_open_issues_unknown_when_pr_count_unknown():
    assert snap(open_prs=None)["open_issues"] is None


def test_latest_release_prefers_stable_and_skips_drafts():
    releases = [
        {"tag_name": "v2.0.0-rc1", "published_at": "2026-10-03T00:00:00Z", "prerelease": True},
        {"tag_name": "v1.9.0", "published_at": "2026-09-20T00:00:00Z", "prerelease": False},
        {"tag_name": "v3.0.0", "published_at": None, "draft": True},
    ]
    s = snap(releases=releases, release_count=3)
    assert s["latest_release_tag"] == "v1.9.0"


def test_semver_parsing():
    assert parse_semver("v1.2.3") == (1, 2, 3)
    assert parse_semver("release-2.0") == (2, 0, 0)
    assert parse_semver("1.4.0-rc1") == (1, 4, 0)
    assert parse_semver("nightly") == (None, None, None)


def test_identity_row_keys_on_numeric_id_and_normalises_licence():
    row = identity_row(REPO)
    assert row["repo_id"] == 42 and row["licence_key"] == "mit"
    assert identity_row({**REPO, "license": {"key": "other"}})["licence_key"] is None
    assert identity_row({**REPO, "license": None})["licence_key"] is None

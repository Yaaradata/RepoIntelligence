from datetime import date, datetime, timedelta, timezone

from repo_intelligence.external.hackernews import flatten_comments, github_slug_in, match_story
from repo_intelligence.external.registries import RegistryClient
from repo_intelligence.packages.stage import resolve_package
from repo_intelligence.showhn.match import capture_row, offset_fields

from .fakes import FakeSession


def test_url_exact_match_and_not_a_longer_repo_name():
    assert github_slug_in("https://github.com/acme/tool", "acme", "tool")
    assert github_slug_in("https://github.com/Acme/Tool/tree/main", "acme", "tool")
    assert not github_slug_in("https://github.com/acme/toolkit", "acme", "tool")


def test_match_strategies_and_confidence():
    assert match_story({"url": "https://github.com/acme/tool"}, owner="acme", name="tool",
                       homepage=None) == ("url_exact", 1.0)
    assert match_story({"url": "https://tool.dev/"}, owner="acme", name="tool",
                       homepage="https://tool.dev") == ("homepage", 0.7)
    assert match_story({"url": "https://x.com", "title": "Show HN: Tool – fast"}, owner="acme",
                       name="tool", homepage=None) == ("title_text", 0.4)
    assert match_story({"url": "https://x.com", "title": "unrelated"}, owner="acme",
                       name="tool", homepage=None) is None


def test_offset_buckets():
    assert offset_fields(3, 10, 2)["points_6h"] is None
    assert offset_fields(7, 10, 2)["points_6h"] == 10
    assert offset_fields(30, 50, 9) | {} == {"points_6h": None, "points_24h": 50, "points_48h": None,
                                             "comments_24h": 9, "comments_48h": None}
    assert offset_fields(60, 80, 20)["points_48h"] == 80


def test_capture_row_age_from_created_at_i():
    now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    story = {"objectID": "77", "created_at_i": int((now - timedelta(hours=25)).timestamp()),
             "points": 120, "num_comments": 40, "url": "https://github.com/a/b", "title": "t"}
    row = capture_row(1, story, "url_exact", 1.0, now)
    assert row["points_24h"] == 120 and row["hn_story_id"] == 77


def test_flatten_comments_top_level_first_and_stripped():
    item = {"children": [
        {"type": "comment", "text": "<p>Top &amp; one</p>", "children": [
            {"type": "comment", "text": "reply", "children": []}]},
        {"type": "comment", "text": "top two", "children": []},
    ]}
    assert flatten_comments(item) == ["Top & one", "top two", "reply"]


def registry(routes):
    return RegistryClient(session=FakeSession(routes=routes), sleep=lambda s: None, rate_sleep=0)


def test_crates_downloads_windows_from_daily_series():
    today = date(2026, 10, 4)
    rows = [{"date": (today - timedelta(days=d)).isoformat(), "downloads": 10} for d in range(0, 40)]
    reg = registry({"/crates/foo/downloads": {"version_downloads": rows, "meta": {"extra_downloads": []}}})
    assert reg.downloads("crates", "foo", today=today) == (70, 300)


class FakeGH:
    def __init__(self, files):
        self.files = files

    def file_text(self, owner, name, path):
        return self.files.get(path)


REPO = {"repo_id": 1, "full_name": "acme/requests", "homepage": None, "primary_language": "Python",
        "previous_full_names": None}


def test_name_match_without_back_reference_is_rejected():
    reg = registry({"pypi.org/pypi/requests/json": {"info": {"project_urls": {"Source": "https://github.com/psf/requests"}}}})
    assert resolve_package(FakeGH({}), reg, REPO) is None


def test_name_match_with_back_reference_is_accepted():
    reg = registry({"pypi.org/pypi/requests/json": {"info": {"project_urls": {"Source": "https://github.com/acme/requests"}}}})
    assert resolve_package(FakeGH({}), reg, REPO) == ("pypi", "requests", "name_verified")


def test_manifest_pointing_elsewhere_is_rejected_but_back_referenced_manifest_accepted():
    files = {"pyproject.toml": '[project]\nname = "acme-req"\n'}
    reg = registry({"pypi.org/pypi/acme-req/json": {"info": {"home_page": "https://github.com/other/x"}}})
    assert resolve_package(FakeGH(files), reg, {**REPO, "primary_language": None}) is None
    reg = registry({"pypi.org/pypi/acme-req/json": {"info": {"home_page": "https://github.com/acme/requests"}}})
    assert resolve_package(FakeGH(files), reg, REPO) == ("pypi", "acme-req", "manifest")


def test_renamed_repo_matches_previous_name():
    reg = registry({"pypi.org/pypi/requests/json": {"info": {"project_urls": {"Source": "https://github.com/old/requests"}}}})
    assert resolve_package(FakeGH({}), reg, {**REPO, "previous_full_names": ["old/requests"]}) == \
        ("pypi", "requests", "name_verified")

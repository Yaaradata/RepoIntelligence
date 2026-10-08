from datetime import date, datetime, timezone

import pytest

from repo_intelligence.external.github import GitHubClient, GitHubError, commits_in_last_days

from .fakes import FakeResponse, FakeSession


def client(responses, **kw):
    sleeps: list[float] = []
    gh = GitHubClient("t", base_url="https://api.test", session=FakeSession(responses),
                      sleep=sleeps.append, clock=lambda: 1000.0, rate_sleep=0.0, search_sleep=0.0, **kw)
    return gh, sleeps


def test_sleeps_until_reset_when_core_remaining_below_100():
    gh, sleeps = client([FakeResponse(200, {"id": 1}, {"X-RateLimit-Remaining": "99",
                                                      "X-RateLimit-Reset": "1300",
                                                      "X-RateLimit-Resource": "core"})])
    gh.get_repo("o", "r")
    assert 301.0 in sleeps           # reset - now + 1s


def test_no_sleep_when_budget_healthy():
    gh, sleeps = client([FakeResponse(200, {"id": 1}, {"X-RateLimit-Remaining": "4000",
                                                      "X-RateLimit-Reset": "1300"})])
    gh.get_repo("o", "r")
    assert all(s == 0.0 for s in sleeps)


def test_search_floor_is_search_specific():
    gh, sleeps = client([FakeResponse(200, {"items": []}, {"X-RateLimit-Remaining": "20",
                                                          "X-RateLimit-Reset": "1060",
                                                          "X-RateLimit-Resource": "search"})])
    list(gh.search_repositories("q"))
    assert all(s == 0.0 for s in sleeps)   # 20 of 30/min left is fine


def test_secondary_rate_limit_retries_after_retry_after():
    gh, sleeps = client([FakeResponse(403, {"message": "secondary"}, {"Retry-After": "7"}),
                         FakeResponse(200, {"id": 5})])
    assert gh.get_repo("o", "r")["id"] == 5
    assert 7.0 in sleeps


def test_404_is_none_and_500_exhausts():
    gh, _ = client([FakeResponse(404, {})])
    assert gh.get_repo("o", "missing") is None
    gh, _ = client([FakeResponse(500, {})] * 4)
    with pytest.raises(GitHubError):
        gh.get_repo("o", "r")


def test_commit_activity_retries_202_then_returns_weeks():
    weeks = [{"week": 0, "days": [0] * 7, "total": 0}]
    gh, sleeps = client([FakeResponse(202, {}), FakeResponse(202, {}), FakeResponse(200, weeks)])
    assert gh.commit_activity("o", "r", retries=3, retry_sleep=2.0) == weeks
    assert sleeps.count(2.0) == 2


def test_commit_activity_gives_up_as_none():
    gh, _ = client([FakeResponse(202, {})] * 4)
    assert gh.commit_activity("o", "r", retries=3, retry_sleep=0.0) is None


def test_contributors_count_reads_last_page_from_link_header():
    link = '<https://api.test/repos/o/r/contributors?per_page=1&page=2>; rel="next", ' \
           '<https://api.test/repos/o/r/contributors?per_page=1&page=137>; rel="last"'
    gh, _ = client([FakeResponse(200, [{"login": "a"}], {"Link": link})])
    assert gh.contributors_count("o", "r") == 137


def test_contributors_count_single_page_and_empty_repo():
    gh, _ = client([FakeResponse(200, [{"login": "a"}])])
    assert gh.contributors_count("o", "r") == 1
    gh, _ = client([FakeResponse(204, None)])
    assert gh.contributors_count("o", "r") == 0


def test_search_paginates_until_short_page():
    page1 = {"items": [{"id": i} for i in range(100)]}
    page2 = {"items": [{"id": i} for i in range(100, 130)]}
    gh, _ = client([FakeResponse(200, page1), FakeResponse(200, page2)])
    assert len(list(gh.search_repositories("q"))) == 130


def test_open_pr_counts_graphql_aliases():
    gh, _ = client([FakeResponse(200, {"data": {"r0": {"pullRequests": {"totalCount": 4}}, "r1": None}})])
    assert gh.open_pr_counts([("a", "x"), ("b", "y")]) == {"a/x": 4, "b/y": None}


def test_commits_in_last_days_counts_per_day_not_per_week():
    sunday = int(datetime(2026, 9, 27, tzinfo=timezone.utc).timestamp())
    prev = int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())
    weeks = [{"week": prev, "days": [1, 1, 1, 1, 1, 1, 1]},
             {"week": sunday, "days": [2, 0, 3, 0, 0, 0, 0]}]
    # (Sep 23, Sep 30]: Sep 24-26 from prev week = 3, Sep 27-29 = 5
    assert commits_in_last_days(weeks, 7, today=date(2026, 9, 30)) == 3 + 5

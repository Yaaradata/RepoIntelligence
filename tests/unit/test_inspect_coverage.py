"""Coverage percentages and the under-50% marker. No database."""

from pathlib import Path

from repo_intelligence.observability import inspect_report as report

ROOT = Path(__file__).resolve().parents[2]


def test_full_column_is_100_percent_and_not_flagged():
    stat = report.coverage_stat("stars", 1284, 1284)
    assert stat["pct"] == 100.0
    assert stat["flagged"] is False
    text = report.format_coverage_line(stat)
    assert "100.0%" in text
    assert "1,284 / 1,284" in text
    assert "<-" not in text


def test_sixty_four_percent_is_not_flagged():
    stat = report.coverage_stat("commits_7d", 649, 1000)
    assert round(stat["pct"], 1) == 64.9
    assert stat["flagged"] is False
    assert "<-" not in report.format_coverage_line(stat)


def test_exact_50_percent_is_not_flagged():
    stat = report.coverage_stat("subscribers", 500, 1000)
    assert stat["pct"] == 50.0
    assert stat["flagged"] is False


def test_contributors_under_50_names_the_403():
    stat = report.coverage_stat("contributors_count", 400, 1000)
    text = report.format_coverage_line(stat)
    assert stat["flagged"] is True
    assert "<-" in text
    assert "403 forbidden on large histories" in text


def test_commits_under_50_names_the_202():
    text = report.format_coverage_line(report.coverage_stat("commits_30d", 100, 1000))
    assert "<-" in text
    assert "202 still computing" in text


def test_missing_release_tag_names_absence_not_a_fetch_failure():
    text = report.format_coverage_line(report.coverage_stat("latest_release_tag", 221, 1000))
    assert "<-" in text
    assert "no release" in text


def test_unknown_low_column_is_flagged_without_an_invented_cause():
    text = report.format_coverage_line(report.coverage_stat("description", 100, 1000))
    assert "<-" in text
    assert "no known cause recorded" in text


def test_zero_of_thirty_nine_is_never_populated():
    stat = report.coverage_stat("commits_7d", 0, 39)
    text = report.format_coverage_line(stat)
    assert stat["never_populated"] is True
    assert stat["flagged"] is False
    assert "<== NEVER POPULATED" in text
    assert "<-" not in text
    assert "0.0%" in text
    assert "(0 / 39)" in text


def test_zero_of_three_is_too_small_to_call_never_populated():
    stat = report.coverage_stat("commits_7d", 0, 3)
    text = report.format_coverage_line(stat)
    assert stat["never_populated"] is False
    assert "NEVER POPULATED" not in text


def test_nineteen_of_thirty_nine_is_under_half_not_never_populated():
    stat = report.coverage_stat("commits_7d", 19, 39)
    text = report.format_coverage_line(stat)
    assert stat["never_populated"] is False
    assert stat["flagged"] is True
    assert "<-" in text
    assert "NEVER POPULATED" not in text


def test_zero_repos_does_not_divide():
    stat = report.coverage_stat("stars", 0, 0)
    assert stat["pct"] is None
    assert stat["flagged"] is False
    assert "n/a" in report.format_coverage_line(stat)


def test_count_row_covers_every_listed_column():
    row = {"repos": 10, **{column: 10 for column in report.COVERAGE_COLUMNS}}
    row["contributors_count"] = 1
    stats = {item["column"]: item for item in report.coverage_from_counts(row)}
    assert set(stats) == set(report.COVERAGE_COLUMNS)
    assert stats["stars"]["pct"] == 100.0
    assert stats["contributors_count"]["flagged"] is True


def test_queries_are_select_only():
    for name, value in vars(report).items():
        if not name.startswith("SQL_"):
            continue
        statement = " ".join(value.split()).lower()
        assert statement.startswith("select"), name
        for forbidden in ("insert ", "update ", "delete ", "drop ", "alter ", "truncate "):
            assert forbidden not in statement, name


def test_inspect_script_sets_a_read_only_transaction_and_does_not_write():
    text = (ROOT / "scripts" / "inspect_run.py").read_text(encoding="utf-8").lower()
    assert "set transaction read only" in text
    for forbidden in ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create "):
        assert forbidden not in text

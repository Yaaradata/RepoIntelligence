import re
from datetime import date

from repo_intelligence.common.config import MIGRATIONS_DIR
from repo_intelligence.discovery.lanes import lane_a_queries, lane_d_queries, slug_from_url, topics
from repo_intelligence.quality_facts.facts import listing_facts, readme_facts


def test_one_search_query_per_topic_because_github_ands_topics():
    queries = lane_a_queries(date(2026, 10, 8))
    assert all(q.count("topic:") == 1 for q in queries)
    assert len(queries) == len(topics()) == len(set(topics()))
    assert "created:>=2026-09-08" in queries[0] and "pushed:>=2026-10-01" in queries[0]


def test_popular_lane_query_shape():
    q = lane_d_queries(date(2026, 10, 8))[0]
    assert "stars:>=2000" in q and "pushed:>=2026-09-24" in q and "archived:false" in q


def test_slug_from_url():
    assert slug_from_url("https://github.com/acme/tool.git") == "acme/tool"
    assert slug_from_url("https://github.com/acme/tool/issues/3") == "acme/tool"
    assert slug_from_url("https://example.com") is None


def test_readme_facts():
    readme = "# Tool\n![b](https://img.shields.io/x)\n## Installation\n```\npip install t\n```\n## Usage\n"
    facts = readme_facts(readme)
    assert facts["has_install_section"] and facts["has_usage_example"]
    assert facts["code_block_count"] == 1 and facts["badge_count"] == 1
    assert readme_facts(None)["has_readme"] is False


def test_listing_facts_ci_needs_workflows():
    assert listing_facts([".github", "tests"], workflow_names=[])["has_ci"] is False
    assert listing_facts([".github", "tests"], workflow_names=["ci.yml"])["has_ci"] is True
    assert listing_facts(["CHANGELOG.md", "docs"])["has_changelog"] is True


def test_migrations_follow_the_rules():
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        assert "CREATE OR REPLACE VIEW" not in sql.upper(), path.name
        assert re.search(r"^BEGIN;", sql, re.M) and re.search(r"^COMMIT;", sql, re.M), path.name
        for stmt in re.findall(r"CREATE (TABLE|INDEX) (?!IF NOT EXISTS)", sql):
            raise AssertionError(f"{path.name}: CREATE {stmt} without IF NOT EXISTS")
        for view in re.findall(r"CREATE VIEW repo_intelligence\.(\w+)", sql):
            assert f"DROP VIEW IF EXISTS repo_intelligence.{view}" in sql, view


def test_repo_id_is_the_identity_key():
    sql = (MIGRATIONS_DIR / "001_schema.sql").read_text()
    assert re.search(r"repo_id\s+BIGINT PRIMARY KEY", sql)
    assert "UNIQUE (repo_id, captured_date)" in sql

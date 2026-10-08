"""Stage 8 — quality facts by file inspection, never inference."""

from __future__ import annotations

import re
from typing import Any

INSTALL_RE = re.compile(r"^#{1,3}\s*(install|installation|getting started|quick ?start)", re.I | re.M)
USAGE_RE = re.compile(r"^#{1,3}\s*(usage|example|quick ?start)", re.I | re.M)
BADGE_RE = re.compile(r"!\[.*?\]\(https://img\.shields\.io")


def readme_facts(readme: str | None, *, excerpt_chars: int = 8000) -> dict[str, Any]:
    if not readme:
        return {"has_readme": False, "readme_length": 0, "has_install_section": False,
                "has_usage_example": False, "code_block_count": 0, "badge_count": 0,
                "readme_excerpt": None}
    return {
        "has_readme": True,
        "readme_length": len(readme),
        "has_install_section": INSTALL_RE.search(readme) is not None,
        "has_usage_example": USAGE_RE.search(readme) is not None,
        "code_block_count": readme.count("```") // 2,
        "badge_count": len(BADGE_RE.findall(readme)),
        "readme_excerpt": readme[:excerpt_chars],
    }


def listing_facts(names: list[str], workflow_names: list[str] | None = None) -> dict[str, Any]:
    lower = {n.lower() for n in names}
    return {
        "has_tests": bool(lower & {"tests", "test", "spec", "__tests__"}),
        "has_ci": ".github" in lower and bool(workflow_names),
        "has_docs_dir": bool(lower & {"docs", "doc", "documentation"}),
        "has_examples_dir": bool(lower & {"examples", "example", "samples", "demos"}),
        "has_contributing": "contributing.md" in lower,
        "has_changelog": any(n.upper().startswith("CHANGELOG") for n in names),
    }


README_COLUMNS = ["has_readme", "readme_length", "has_install_section", "has_usage_example",
                  "code_block_count", "badge_count", "readme_excerpt"]
LISTING_COLUMNS = ["has_tests", "has_ci", "has_docs_dir", "has_examples_dir",
                   "has_contributing", "has_changelog"]


def upsert_facts(conn, repo_id: int, facts: dict[str, Any]) -> None:
    cols = [c for c in README_COLUMNS + LISTING_COLUMNS if c in facts]
    assignments = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols)
    conn.execute(
        f"""INSERT INTO repo_intelligence.github_repo_quality_facts (repo_id, {', '.join(cols)})
            VALUES (%s, {', '.join(['%s'] * len(cols))})
            ON CONFLICT (repo_id) DO UPDATE SET {assignments}, checked_at=NOW()""",
        (repo_id, *[facts[c] for c in cols]),
    )

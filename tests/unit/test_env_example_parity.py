"""`.env.example` must not document variables that nothing reads.

A variable that looks configured but is ignored is worse than a missing one:
it reports success and changes nothing.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Read by config.py but set per deployment, so they appear in .env.example.
# Keep in sync with the module-level constants in common/config.py.
DIRECT = {
    "DATABASE_URL", "DB_SCHEMA",
    "GITHUB_TOKEN", "GITHUB_API_BASE", "GITHUB_RATE_SLEEP", "GITHUB_SEARCH_SLEEP",
    "HN_API_BASE", "HN_RATE_SLEEP",
    "NPM_API_BASE", "NPM_REGISTRY_BASE", "PYPI_STATS_BASE", "PYPI_JSON_BASE",
    "CRATES_API_BASE", "DOCKERHUB_API_BASE", "REGISTRY_RATE_SLEEP",
    "HTTP_USER_AGENT",
}

# Not read yet. Each entry names the phase that will read it. Removing a name
# from here without the code reading it makes this test fail — that is the
# point: the list cannot grow silently.
FORWARD = {
    "OPENROUTER_API_KEY": "phase 2 — screen/editorial stages",
    "SES_REGION": "phase 4 — health report",
    "SES_FROM": "phase 4 — health report",
    "ALERT_RECIPIENTS": "phase 4 — health report",
}


def documented() -> set[str]:
    """Variable names in .env.example, including commented-out examples."""
    names = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("#").strip()
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match:
            names.add(match.group(1))
    return names


def valid_section_keys() -> set[str]:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    return {
        f"{section}_{key}".upper()
        for section, body in data.items()
        if isinstance(body, dict)
        for key in body
    }


def test_every_documented_variable_is_read_somewhere():
    unaccounted = documented() - DIRECT - set(FORWARD) - valid_section_keys()
    assert not unaccounted, (
        "documented in .env.example but read by nothing: "
        f"{sorted(unaccounted)}. Either the code should read it, or it should "
        "be removed, or added to FORWARD with the phase that will use it."
    )


def test_direct_names_are_actually_read_by_config():
    source = (ROOT / "src" / "repo_intelligence" / "common" / "config.py").read_text(encoding="utf-8")
    missing = [name for name in DIRECT if f'"{name}"' not in source]
    assert not missing, f"listed in DIRECT but not read by config.py: {sorted(missing)}"


def test_secrets_are_not_committed_with_values():
    """.env.example must carry placeholders, never a real credential."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "github_pat_xxxx" in text
    assert "sk-or-v1-xxxx" in text
    for leak in ("AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID"):
        assert leak not in text, f"{leak} must never appear — SES uses the instance role"

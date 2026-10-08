"""Environment + config/settings.yaml loading.

Environment variables win over settings.yaml. A `.env` at the project root is
read if present (values already in the environment are never overwritten).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"
POLICIES_DIR = ROOT / "policies"
PROMPTS_DIR = ROOT / "prompts"
MIGRATIONS_DIR = ROOT / "sql" / "migrations"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


def env(name: str, default: Any = None) -> Any:
    value = os.getenv(name)
    return default if value in (None, "") else value


def env_float(name: str, default: float) -> float:
    return float(env(name, default))


def env_int(name: str, default: int) -> int:
    return int(env(name, default))


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")) or {}


def setting(section: str, key: str, default: Any = None) -> Any:
    """settings.yaml value, overridden by an env var named KEY in upper case."""
    override = os.getenv(key.upper())
    base = (settings().get(section) or {}).get(key, default)
    if override in (None, ""):
        return base
    if isinstance(base, bool):
        return override.lower() in {"1", "true", "yes"}
    if isinstance(base, int):
        return int(override)
    if isinstance(base, float):
        return float(override)
    return override


@lru_cache(maxsize=1)
def seeds() -> dict[str, Any]:
    path = CONFIG_DIR / "seeds.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


DB_SCHEMA = env("DB_SCHEMA", "repo_intelligence")
GITHUB_API_BASE = env("GITHUB_API_BASE", "https://api.github.com")
GITHUB_RATE_SLEEP = env_float("GITHUB_RATE_SLEEP", 0.8)
GITHUB_SEARCH_SLEEP = env_float("GITHUB_SEARCH_SLEEP", 2.5)
HN_API_BASE = env("HN_API_BASE", "https://hn.algolia.com/api/v1")
HN_RATE_SLEEP = env_float("HN_RATE_SLEEP", 0.3)
NPM_API_BASE = env("NPM_API_BASE", "https://api.npmjs.org")
NPM_REGISTRY_BASE = env("NPM_REGISTRY_BASE", "https://registry.npmjs.org")
PYPI_STATS_BASE = env("PYPI_STATS_BASE", "https://pypistats.org/api")
PYPI_JSON_BASE = env("PYPI_JSON_BASE", "https://pypi.org/pypi")
CRATES_API_BASE = env("CRATES_API_BASE", "https://crates.io/api/v1")
DOCKERHUB_API_BASE = env("DOCKERHUB_API_BASE", "https://hub.docker.com/v2")
REGISTRY_RATE_SLEEP = env_float("REGISTRY_RATE_SLEEP", 1.0)
HTTP_USER_AGENT = env("HTTP_USER_AGENT", "RepoIntelligenceV1 (TheNeural newsletter)")

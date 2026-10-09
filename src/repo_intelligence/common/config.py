"""Environment + config/settings.yaml loading.

Secrets and rate limits come from the environment. Tunables come from
settings.yaml and can be overridden by a ``SECTION_KEY`` variable. A ``.env``
at the project root is read if present (values already in the environment are
never overwritten).
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
    """Value from settings.yaml, overridable by `SECTION_KEY` in the environment.

    The override name carries the section (`eligibility.min_stars` →
    `ELIGIBILITY_MIN_STARS`) so that two sections sharing a key name cannot
    collide on one variable. The override is coerced to the type of the YAML
    value, or of `default` when the key is absent from YAML; without either, a
    bare string would reach a numeric comparison and fail far from its cause,
    so that case raises here instead.
    """
    base = (settings().get(section) or {}).get(key, default)
    override = os.getenv(f"{section}_{key}".upper())
    if override in (None, ""):
        return base

    template = base if base is not None else default
    if isinstance(template, bool):
        return override.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(template, int):
        return int(override)
    if isinstance(template, float):
        return float(override)
    if isinstance(template, str):
        return override
    if template is None:
        raise RuntimeError(
            f"{section}_{key}".upper() + " is set, but "
            f"'{section}.{key}' has no value in settings.yaml and no default, "
            "so its type cannot be determined. Add it to settings.yaml."
        )
    raise RuntimeError(
        f"{section}_{key}".upper() + f" cannot override a {type(template).__name__}"
    )


def validate_setting_overrides() -> None:
    """Fail on a SECTION_KEY variable whose key does not exist in that section.

    A misspelled override is otherwise silent — the pipeline runs with the YAML
    value and nothing says the variable was ignored.
    """
    known: set[str] = set()
    prefixes: dict[str, str] = {}
    for section, body in settings().items():
        if not isinstance(body, dict):
            continue
        prefixes[section.upper() + "_"] = section
        for key in body:
            known.add(f"{section}_{key}".upper())

    unknown = [
        name for name in os.environ
        if any(name.startswith(p) for p in prefixes) and name not in known
    ]
    if unknown:
        raise RuntimeError(
            "unrecognised settings override(s) in the environment: "
            + ", ".join(sorted(unknown))
            + ". Check spelling against config/settings.yaml, or remove them."
        )


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


def database_url() -> str:
    """Resolved when a connection is opened, not when this module is imported."""
    url = env("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def github_token() -> str | None:
    return env("GITHUB_TOKEN")

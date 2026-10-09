import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _no_real_db_connections(monkeypatch):
    """No test may open a real connection.

    Stage functions take an open `conn`; tests pass a fake. If a test reaches
    psycopg directly it would hit whatever DATABASE_URL points at — in CI or on
    the EC2 box, that is production.
    """

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "tests must not open a real DB connection — pass a fake conn, "
            "or monkeypatch repo_intelligence.common.db.connect"
        )

    monkeypatch.setattr(psycopg, "connect", _blocked)

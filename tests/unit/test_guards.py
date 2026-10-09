import pytest

from repo_intelligence.common import db


def test_real_connection_is_blocked_in_tests(monkeypatch):
    # database_url() runs before psycopg.connect. A placeholder gets us to the
    # guard without reading .env or depending on a real URL being present.
    monkeypatch.setenv("DATABASE_URL", "postgresql://blocked/blocked")
    with pytest.raises(RuntimeError, match="must not open a real DB connection"):
        with db.connect():
            pass

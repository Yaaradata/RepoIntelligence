"""Postgres connections (psycopg 3, dict rows)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from repo_intelligence.common.config import database_url as _database_url


def database_url() -> str:
    return _database_url()


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()

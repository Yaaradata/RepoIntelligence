#!/usr/bin/env python3
"""Migration state probe — run before diagnosing anything. Read-only."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repo_intelligence.common.config import MIGRATIONS_DIR  # noqa: E402
from repo_intelligence.common.db import connect  # noqa: E402


def expected_objects() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        names = re.findall(r"CREATE (?:TABLE|VIEW) (?:IF NOT EXISTS )?repo_intelligence\.(\w+)", sql)
        out[path.name] = names
    return out


def main() -> int:
    with connect() as conn:
        present = {r["table_name"] for r in conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'repo_intelligence'""").fetchall()}
        ok = True
        for migration, names in expected_objects().items():
            missing = [n for n in names if n not in present]
            state = "APPLIED" if not missing else ("NOT APPLIED" if len(missing) == len(names) else "PARTIAL")
            ok &= not missing
            print(f"{migration:<20} {state:<12} {len(names) - len(missing)}/{len(names)}"
                  + (f"  missing: {', '.join(missing)}" if missing else ""))
        if present:
            for table in sorted(present):
                if table.startswith("v_"):
                    continue
                n = conn.execute(f"SELECT count(*) AS n FROM repo_intelligence.{table}").fetchone()["n"]
                print(f"  {table:<36} {n:>9,} rows")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""pipeline_runs / stage_runs records."""

from __future__ import annotations

import json
import subprocess
import uuid
from typing import Any

from repo_intelligence.common.config import ROOT


def code_commit_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def start_pipeline_run(conn, pipeline_name: str, *, trigger_type: str = "manual",
                       metadata: dict[str, Any] | None = None) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO repo_intelligence.pipeline_runs
           (run_id, pipeline_name, trigger_type, code_commit_sha, status, metadata)
           VALUES (%s, %s, %s, %s, 'running', %s)""",
        (run_id, pipeline_name, trigger_type, code_commit_sha(), json.dumps(metadata or {})),
    )
    conn.commit()
    return run_id


def finish_pipeline_run(conn, run_id: str, *, status: str, items_input: int | None = None,
                        items_succeeded: int | None = None, items_failed: int | None = None,
                        total_cost_usd: float | None = None) -> None:
    conn.execute(
        """UPDATE repo_intelligence.pipeline_runs
           SET status=%s, ended_at=NOW(), items_input=%s, items_succeeded=%s,
               items_failed=%s, total_cost_usd=%s
           WHERE run_id=%s""",
        (status, items_input, items_succeeded, items_failed, total_cost_usd, run_id),
    )
    conn.commit()


def start_stage_run(conn, run_id: str, stage_name: str, *, stage_version: str = "v001",
                    prompt_version: str | None = None, items_input: int | None = None) -> int:
    row = conn.execute(
        """INSERT INTO repo_intelligence.stage_runs
           (run_id, stage_name, stage_version, prompt_version, items_input, status)
           VALUES (%s, %s, %s, %s, %s, 'running') RETURNING stage_run_id""",
        (run_id, stage_name, stage_version, prompt_version, items_input),
    ).fetchone()
    conn.commit()
    return int(row["stage_run_id"])


def finish_stage_run(conn, stage_run_id: int, *, status: str, items_success: int = 0,
                     items_failed: int = 0, items_skipped: int = 0, cost_usd: float | None = None,
                     error_summary: str | None = None) -> None:
    conn.execute(
        """UPDATE repo_intelligence.stage_runs
           SET status=%s, ended_at=NOW(), items_success=%s, items_failed=%s,
               items_skipped=%s, cost_usd=%s, error_summary=%s
           WHERE stage_run_id=%s""",
        (status, items_success, items_failed, items_skipped, cost_usd,
         (error_summary or "")[:2000] or None, stage_run_id),
    )
    conn.commit()

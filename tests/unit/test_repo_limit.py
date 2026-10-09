"""--limit caps snapshot, packages and showhn without resampling."""

import importlib.util
import inspect
from pathlib import Path

import pytest

from repo_intelligence.common.stats import StageStats
from repo_intelligence.snapshot.stage import apply_repo_limit, snapshot_scope

ROOT = Path(__file__).resolve().parents[2]


def _repos(n: int = 10) -> list[dict]:
    """The order snapshot_scope returns: ascending repo_id."""
    return [{"repo_id": i, "full_name": f"acme/r{i}"} for i in range(1, n + 1)]


def test_scope_queries_order_by_repo_id_so_the_slice_is_stable():
    source = inspect.getsource(snapshot_scope)
    assert source.lower().count("order by r.repo_id") == 3
    stage_src = (ROOT / "scripts" / "run_stage.py").read_text(encoding="utf-8")
    assert "ORDER BY repo_id" in stage_src
    assert "RANDOM" not in stage_src


def test_limit_three_of_ten_is_the_lowest_ids():
    chosen = apply_repo_limit(_repos(), 3)
    assert [r["repo_id"] for r in chosen] == [1, 2, 3]


def test_raising_the_limit_extends_the_same_prefix():
    first = apply_repo_limit(_repos(), 3)
    second = apply_repo_limit(_repos(), 5)
    assert [r["repo_id"] for r in first] == [1, 2, 3]
    assert [r["repo_id"] for r in second] == [1, 2, 3, 4, 5]
    assert {r["repo_id"] for r in first} <= {r["repo_id"] for r in second}


def test_absent_limit_processes_all():
    assert apply_repo_limit(_repos(), None) == _repos()


def test_limit_larger_than_scope_processes_all():
    assert [r["repo_id"] for r in apply_repo_limit(_repos(), 50)] == list(range(1, 11))


def test_negative_limit_is_rejected():
    with pytest.raises(ValueError, match="--limit must be >= 0"):
        apply_repo_limit(_repos(), -1)


def _load_run_stage():
    path = ROOT / "scripts" / "run_stage.py"
    spec = importlib.util.spec_from_file_location("run_stage_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_one_applies_limit_on_the_three_per_repo_stages(monkeypatch):
    module = _load_run_stage()
    repos = _repos()
    seen: dict[str, list] = {}

    monkeypatch.setattr(
        "repo_intelligence.snapshot.stage.snapshot_scope", lambda *args, **kwargs: repos)
    monkeypatch.setattr(module, "repos_for_scope", lambda *args, **kwargs: list(repos))

    def capture(name, repos_index):
        def _run(*args, **kwargs):
            seen[name] = args[repos_index]
            seen[name + "_label"] = kwargs["scope_label"]
            return StageStats(name)
        return _run

    # snapshot(conn, gh, repos), packages(conn, gh, reg, repos), showhn(conn, hn, repos)
    monkeypatch.setattr("repo_intelligence.snapshot.stage.run_snapshot", capture("snapshot", 2))
    monkeypatch.setattr("repo_intelligence.packages.stage.run_packages", capture("packages", 3))
    monkeypatch.setattr("repo_intelligence.showhn.match.run_match", capture("showhn", 2))

    for stage in ("snapshot", "packages", "showhn"):
        args = module.build_parser().parse_args(["--stage", stage, "--dry-run", "--limit", "3"])
        module.run_one(object(), stage, args, "run-1")
        assert [r["repo_id"] for r in seen[stage]] == [1, 2, 3]
        assert seen[stage + "_label"] == "scope=new limit=3"


def test_discovery_is_not_capped_by_limit(monkeypatch):
    module = _load_run_stage()
    called = {}

    def fake_discovery(conn, gh, hn, run_id, *, lanes, dry_run):
        called["lanes"] = lanes
        called["dry_run"] = dry_run
        return StageStats("discovery")

    monkeypatch.setattr("repo_intelligence.discovery.lanes.run_discovery", fake_discovery)
    args = module.build_parser().parse_args(["--stage", "discovery", "--dry-run", "--limit", "3"])
    module.run_one(object(), "discovery", args, "run-1")
    assert called == {"lanes": ["new", "popular", "seed"], "dry_run": True}

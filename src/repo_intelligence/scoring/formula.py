"""Stage 12 scoring formula: blinded usefulness × evidence factor + capped boosts."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from repo_intelligence.common.config import POLICIES_DIR


@lru_cache(maxsize=4)
def load_policy(version: str = "v001") -> dict[str, Any]:
    return yaml.safe_load((POLICIES_DIR / "scoring" / f"{version}.yaml").read_text(encoding="utf-8"))


def final_score(dims: dict[str, float], *, momentum_pct: float, adoption_pct: float,
                showhn_pct: float, popularity_pct: float, policy: dict[str, Any]) -> dict[str, float]:
    weights = policy["usefulness_weights"]
    usefulness = sum(w * float(dims[k]) for k, w in weights.items())
    ef = policy["evidence_factor"]
    strength = max(0.0, min(10.0, float(dims["evidence_strength"])))
    evidence_factor = ef["base"] + ef["slope"] * strength
    caps = policy["boost_caps"]

    def _pct(value: float) -> float:
        """Percentiles are [0, 1]. Anything outside that is a caller bug —
        clamp rather than let a negative value subtract from the score."""
        return max(0.0, min(1.0, float(value)))

    boosts = {
        "momentum": caps["momentum"] * _pct(momentum_pct),
        "adoption": caps["adoption"] * _pct(adoption_pct),
        "showhn": caps["showhn"] * _pct(showhn_pct),
        "popularity": caps["popularity"] * _pct(popularity_pct),
    }
    boost_total = min(caps["total"], sum(boosts.values()))
    final = min(10.0, usefulness * evidence_factor + boost_total)
    return {"usefulness": round(usefulness, 4), "evidence_factor": round(evidence_factor, 4),
            **{f"boost_{k}": round(v, 4) for k, v in boosts.items()},
            "boost_total": round(boost_total, 4), "final": round(final, 4)}

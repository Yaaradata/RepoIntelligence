"""The property the design rests on: popularity reorders close calls, never usefulness."""

import pytest

from repo_intelligence.scoring.formula import final_score, load_policy

DIMS = ["technical_usefulness", "product_usefulness", "actionability", "maturity",
        "novelty", "explainability"]


def dims(level: float, evidence: float = 10.0) -> dict[str, float]:
    return {**{k: level for k in DIMS}, "evidence_strength": evidence}


@pytest.mark.parametrize("evidence", [0.0, 2.5, 5.0, 7.5, 7.78, 8.0, 10.0])
def test_usefulness_gap_beats_every_boost_at_all_evidence_levels(evidence):
    """The property the design rests on, at every evidence level — not just 10.

    A 1.5-point usefulness gap must survive every boost maxed. At total=1.4
    this failed below evidence_strength 7.78.
    """
    policy = load_policy("v001")
    strong = final_score(dims(8.5, evidence), momentum_pct=0, adoption_pct=0,
                         showhn_pct=0, popularity_pct=0, policy=policy)
    boosted = final_score(dims(7.0, evidence), momentum_pct=1, adoption_pct=1,
                          showhn_pct=1, popularity_pct=1, policy=policy)
    assert strong["final"] > boosted["final"], (
        f"at evidence_strength={evidence}: {strong['final']} !> {boosted['final']}"
    )


def test_boost_cap_is_derived_from_the_minimum_evidence_factor():
    """Guards the derivation itself, so a future cap rise fails here first."""
    policy = load_policy("v001")
    min_ef = policy["evidence_factor"]["base"]          # evidence_strength = 0
    assert policy["boost_caps"]["total"] < 1.5 * min_ef


def test_total_boost_is_capped():
    policy = load_policy("v001")
    out = final_score(dims(5.0), momentum_pct=1, adoption_pct=1, showhn_pct=1,
                      popularity_pct=1, policy=policy)
    assert out["boost_total"] == pytest.approx(policy["boost_caps"]["total"])


def test_evidence_factor_range():
    policy = load_policy("v001")
    low = final_score(dims(8.0, evidence=0.0), momentum_pct=0, adoption_pct=0, showhn_pct=0,
                      popularity_pct=0, policy=policy)
    high = final_score(dims(8.0, evidence=10.0), momentum_pct=0, adoption_pct=0, showhn_pct=0,
                       popularity_pct=0, policy=policy)
    assert low["evidence_factor"] == pytest.approx(0.70)
    assert high["evidence_factor"] == pytest.approx(1.00)


def test_final_never_exceeds_ten():
    out = final_score(dims(10.0), momentum_pct=1, adoption_pct=1, showhn_pct=1,
                      popularity_pct=1, policy=load_policy("v001"))
    assert out["final"] == 10.0


def test_out_of_range_percentiles_are_clamped_not_subtracted():
    policy = load_policy("v001")
    out = final_score(dims(7.0), momentum_pct=-0.5, adoption_pct=2.0,
                      showhn_pct=0, popularity_pct=0, policy=policy)
    assert out["boost_momentum"] == 0.0
    assert out["boost_adoption"] == pytest.approx(policy["boost_caps"]["adoption"])
    assert out["final"] >= out["usefulness"] * out["evidence_factor"]


def test_out_of_range_evidence_strength_is_clamped():
    policy = load_policy("v001")
    low = final_score(dims(8.0, evidence=-3.0), momentum_pct=0, adoption_pct=0,
                      showhn_pct=0, popularity_pct=0, policy=policy)
    high = final_score(dims(8.0, evidence=99.0), momentum_pct=0, adoption_pct=0,
                       showhn_pct=0, popularity_pct=0, policy=policy)
    assert low["evidence_factor"] == pytest.approx(0.70)
    assert high["evidence_factor"] == pytest.approx(1.00)


def test_lane_weight_rows_share_signals_and_are_non_negative():
    rows = load_policy("v001")["lane_weights"]
    signals = set(rows["new"])
    for lane, weights in rows.items():
        assert set(weights) == signals, lane
        assert all(w >= 0 for w in weights.values()), lane

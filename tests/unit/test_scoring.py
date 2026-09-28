from datetime import UTC, datetime, timedelta

import pytest

from jevtrends import scoring
from jevtrends.models import TrendScore

NOW = datetime(2026, 9, 28, tzinfo=UTC)
WEIGHTS = {"momentum": 0.30, "pain": 0.20, "spend": 0.20, "underserved": 0.20, "breadth": 0.10}


def make_score(trend_id: str, niches: list[str], **kw) -> TrendScore:
    fields = dict(trend_id=trend_id, support=5.0, creators=5, momentum_ratio=1.0, momentum_norm=0.5,
                  breadth_norm=0.5, median_views=100.0, promo_share=0.0, niche_affinity={n: 0.9 for n in niches},
                  niches=niches, primary_niche=niches[0] if niches else None,
                  pain_norm=0.5, spend_norm=0.5, underserved_norm=0.5)
    fields.update(kw)
    return TrendScore(**fields)


def test_support_and_pruning():
    members = {"a": 0.9, "b": 0.8, "c": 0.6, "d": 0.2}
    creator_of = {"a": "x", "b": "y", "c": "y", "d": "z"}
    assert scoring.support(members) == pytest.approx(2.5)
    assert scoring.confident(members, 0.5) == ["a", "b", "c"]
    assert scoring.prune_reason(members, creator_of, 3.0, 3, 0.5).startswith("support 2.5")
    members["e"] = 1.0
    creator_of["e"] = "y"
    assert scoring.prune_reason(members, creator_of, 3.0, 3, 0.5) == "2 distinct creators < 3"
    creator_of["e"] = "w"
    assert scoring.prune_reason(members, creator_of, 3.0, 3, 0.5) is None


def test_top_choices_self_check_none_rate():
    probs = {"v1": {"t01": 0.7, "none_of_these": 0.3}, "v2": {"t01": 0.2, "t02": 0.8}, "v3": {"none_of_these": 0.9, "t01": 0.1}}
    top = scoring.top_choices(probs)
    assert top == {"v1": "t01", "v2": "t02", "v3": "none_of_these"}
    assert scoring.self_check("t01", ["v1", "v2", "missing"], top) == 0.5
    assert scoring.self_check("t01", ["missing"], top) is None
    assert scoring.none_rate(top, "none_of_these") == pytest.approx(1 / 3)
    assert scoring.none_rate({}, "none_of_these") == 0.0


def test_momentum_rising_baseline_and_undefined():
    start = scoring.recent_start(NOW, 30, 1 / 3)
    assert start == NOW - timedelta(days=10)
    recent, old = NOW - timedelta(days=2), NOW - timedelta(days=20)
    posted = {f"r{i}": recent for i in range(10)} | {f"o{i}": old for i in range(20)}
    c = scoring.corpus_recent_share(posted, start)
    assert c == pytest.approx(1 / 3)
    rising = {f"r{i}": 1.0 for i in range(10)}
    ratio, norm = scoring.momentum(rising, posted, start, c, 2)
    assert ratio == pytest.approx((10 + 2 / 3) / (12 / 3))
    assert norm == pytest.approx(0.8538, abs=1e-3)
    baseline = {f"r{i}": 1.0 for i in range(3)} | {f"o{i}": 1.0 for i in range(6)}
    assert scoring.momentum(baseline, posted, start, c, 2) == (pytest.approx(1.0), pytest.approx(0.5))
    assert scoring.momentum(rising, posted, start, 0.0, 2) == (1.0, 0.5)
    assert scoring.momentum(rising, posted, start, 1.0, 2) == (1.0, 0.5)


def test_breadth_niches_promo_views():
    assert scoring.breadth_norm(0) == 0.0
    assert scoring.breadth_norm(20) == pytest.approx(1.0)
    assert scoring.breadth_norm(100) == 1.0
    members = {"a": 1.0, "b": 0.5}
    affinity = scoring.niche_affinity(members, {"a": {"ai": 0.9, "fin": 0.1}, "b": {"ai": 0.3, "fin": 0.9}})
    assert affinity == {"ai": pytest.approx(0.7), "fin": pytest.approx(0.55 / 1.5)}
    assert scoring.assigned_niches(affinity, 0.5, ["fin", "ai"]) == (["ai"], "ai")
    assert scoring.assigned_niches({"ai": 0.2}, 0.5, ["ai"]) == ([], None)
    assert scoring.promo_share(members, {"a": 0.9, "b": 0.1}) == pytest.approx(1 / 1.5)
    assert scoring.median_views(["a", "b", "c"], {"a": 10, "b": 30, "c": 20}) == 20.0
    assert scoring.median_views([], {}) == 0.0


def test_normalized_jev_scores_unknown_underserved_is_neutral():
    assert scoring.normalized_jev_scores(3.0, 1.5, 3.0, 0.2) == (1.0, 0.5, 0.5)
    assert scoring.normalized_jev_scores(0.0, 0.0, 3.0, 0.8) == (0.0, 0.0, 1.0)


def test_rank_scores_and_opportunity():
    high = make_score("t01", ["ai"], momentum_norm=1.0, pain_norm=1.0)
    low = make_score("t02", ["ai"])
    ranked = scoring.rank_scores([low, high], WEIGHTS)
    assert [s.trend_id for s in ranked] == ["t01", "t02"]
    assert [s.rank for s in ranked] == [1, 2]
    assert ranked[0].opportunity == pytest.approx(0.3 + 0.2 + 0.1 + 0.1 + 0.05)


def test_select_for_briefs_covers_each_niche_then_fills_by_rank():
    ranked = scoring.rank_scores([
        make_score("t01", ["ai"], momentum_norm=1.0),
        make_score("t02", ["ai"], momentum_norm=0.9),
        make_score("t03", ["fin"], momentum_norm=0.1),
        make_score("t04", [], momentum_norm=0.8),
    ], WEIGHTS)
    assert scoring.select_for_briefs(ranked, ["ai", "fin", "food"], max_briefs=3) == ["t01", "t02", "t03"]
    assert scoring.select_for_briefs(ranked, ["ai", "fin", "food"], max_briefs=2) == ["t01", "t03"]

import pytest

from jevtrends.opportunities import scoring
from jevtrends.opportunities.models import TrendScore

WEIGHTS = {"momentum": 0.30, "pain": 0.20, "spend": 0.20, "underserved": 0.20, "breadth": 0.10}


def make_score(trend_id: str, niches: list[str], **kw) -> TrendScore:
    fields = dict(trend_id=trend_id, support=5.0, creators=5, momentum_ratio=1.0, momentum_norm=0.5,
                  breadth_norm=0.5, median_views=100.0, promo_share=0.0, niche_affinity={n: 0.9 for n in niches},
                  niches=niches, primary_niche=niches[0] if niches else None,
                  pain_norm=0.5, spend_norm=0.5, underserved_norm=0.5)
    fields.update(kw)
    return TrendScore(**fields)


def test_niche_affinity_and_assigned_niches():
    members = {"a": 1.0, "b": 0.5}
    affinity = scoring.niche_affinity(members, {"a": {"ai": 0.9, "fin": 0.1}, "b": {"ai": 0.3, "fin": 0.9}})
    assert affinity == {"ai": pytest.approx(0.7), "fin": pytest.approx(0.55 / 1.5)}
    assert scoring.niche_affinity({}, {}) == {}
    assert scoring.assigned_niches(affinity, 0.5, ["fin", "ai"]) == (["ai"], "ai")
    assert scoring.assigned_niches({"ai": 0.2}, 0.5, ["ai"]) == ([], None)


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

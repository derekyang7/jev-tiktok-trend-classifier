import math

import pytest

from jevtrends.ugc.models import UgcTrendScore
from jevtrends.ugc.scoring import (business_use, engagement, facet_count_range, log_norm, pair_stats, performance,
                                   rank_ugc, reach, select_briefs, series_momentum, trim_briefs)

WEIGHTS = {"momentum": 0.25, "performance": 0.25, "fit": 0.30, "breadth": 0.10, "ease": 0.10}


def score(trend_id: str, facet: str, **overrides) -> UgcTrendScore:
    fields = dict(trend_id=trend_id, facet=facet, support=5.0, creators=5, momentum_ratio=1.0, momentum_norm=0.5,
                  reach_ratio=1.0, eng_ratio=1.0, performance_norm=0.5, breadth_norm=0.5, fit_norm=0.5, ease_norm=0.5)
    fields.update(overrides)
    return UgcTrendScore(**fields)


def test_facet_count_range_scales_with_the_digest():
    assert facet_count_range(336, 8, 15) == (5, 15)
    assert facet_count_range(40, 8, 15) == (1, 5)
    assert facet_count_range(5, 8, 15) == (1, 1)


def test_reach_uses_the_follower_floor_and_engagement_never_divides_by_zero():
    assert reach(5000, 100, 1000) == 5.0
    assert reach(5000, None, 1000) == 5.0
    assert reach(5000, 0, 1000) == 5.0
    assert reach(5000, 10000, 1000) == 0.5
    assert engagement(0, 0, 0) == 0.0 and engagement(10, 10, 0) == 20.0 and engagement(30, 20, 1000) == 0.05


def test_performance_shrinks_small_trends_and_is_neutral_without_a_baseline():
    reach_ratio, eng_ratio, norm = performance([4.0, 4.0, 4.0], [0.1, 0.1, 0.1], 1.0, 0.1, k=2)
    assert reach_ratio == pytest.approx(2 ** 1.2) and eng_ratio == pytest.approx(1.0)  # log2(4) * 3/5 = 1.2
    assert norm == pytest.approx((log_norm(1.2) + 0.5) / 2)
    assert performance([], [], 1.0, 1.0, 2) == (1.0, 1.0, 0.5)
    assert performance([1.0], [0.1], 0.0, 0.1, 2) == (1.0, 1.0, 0.5)
    _, _, zero = performance([0.0, 0.0], [0.0, 0.0], 1.0, 0.1, k=2)
    assert zero == pytest.approx(log_norm(-1.0))  # a zero median counts as log2 = -2, shrunk by 2/4


def test_series_momentum_compares_the_recent_third_with_the_whole_series():
    assert series_momentum([1, 1, 1, 1, 1, 1], 0.333)[0] == pytest.approx(1.0)
    ratio, norm = series_momentum([0.2, 0.2, 0.2, 0.2, 0.6, 0.6], 0.333)
    assert ratio == pytest.approx(1.8) and norm == pytest.approx(log_norm(math.log2(1.8)))
    assert series_momentum([1.0, 2.0], 0.333) is None
    assert series_momentum([0.0, 0.0, 0.0], 0.333) is None


def test_pair_stats_keeps_frequent_cross_facet_partners():
    members = {"f01": {"a": 1.0, "b": 1.0, "c": 0.9, "d": 0.0}, "h01": {"a": 0.9, "b": 1.0, "c": 1.0, "d": 0.1},
               "f02": {"d": 1.0}, "t01": {"a": 1.0, "d": 1.0}}
    facet_of = {"f01": "format", "h01": "hook", "f02": "format", "t01": "topic"}
    rows = pair_stats(members, facet_of, n_videos=10, min_co=2.0, min_lift=1.5)
    assert [(a, b) for a, b, _, _ in rows] == [("f01", "h01"), ("h01", "f01")]
    assert rows[0][2] == pytest.approx(2.8) and rows[0][3] == pytest.approx(28 / 8.7)


def test_business_use_prefers_the_song_flag_then_the_list_then_a_trusted_raw_flag():
    assert business_use(True, False, {}, "") == ("approved", "popular-songs data")
    assert business_use(False, True, {}, "") == ("organic_only", "popular-songs data")
    assert business_use(None, True, {}, "") == ("approved", "business-use filter")
    flags = {"is_commerce_music_strict": False}
    assert business_use(None, False, flags, "is_commerce_music_strict") == ("organic_only",
                                                                            "TikTok flag is_commerce_music_strict")
    assert business_use(None, False, {"is_commerce_music_strict": True}, "") == ("unknown", "")
    assert business_use(None, False, {}, "is_commerce_music_strict") == ("unknown", "")


def test_ranking_sets_scores_and_ranks_overall_and_within_each_facet():
    ranked = rank_ugc([score("f01", "format", fit_norm=1.0), score("h01", "hook", fit_norm=0.0),
                       score("f02", "format")], WEIGHTS)
    assert [s.trend_id for s in ranked] == ["f01", "f02", "h01"]
    assert [(s.rank_overall, s.rank_in_facet) for s in ranked] == [(1, 1), (2, 2), (3, 1)]
    assert ranked[0].score == pytest.approx(0.125 + 0.125 + 0.3 + 0.05 + 0.05)


def test_select_briefs_fills_quotas_then_the_best_remaining_eligible_trends():
    ranked = rank_ugc([score("f01", "format", fit_norm=1.0), score("f02", "format", fit_norm=0.9),
                       score("f03", "format", fit_norm=0.8), score("h01", "hook", fit_norm=0.7),
                       score("s01", "sound", fit_norm=0.6), score("t01", "topic", fit_norm=0.1)], WEIGHTS)
    quotas = {"format": 1, "hook": 1, "sound": 1, "topic": 1, "need": 1}
    eligible = {"f01", "f02", "f03", "h01", "t01"}  # s01 is not approved
    assert select_briefs(ranked, quotas, eligible) == ["f01", "f02", "f03", "h01", "t01"]
    assert select_briefs(ranked, {**quotas, "format": 0}, eligible) == ["f01", "f02", "h01", "t01"]  # 4 in total
    assert select_briefs(ranked, dict.fromkeys(quotas, 0), eligible) == []


def test_trim_briefs_drops_the_lowest_but_keeps_one_per_facet():
    ranked = rank_ugc([score("f01", "format", fit_norm=1.0), score("f02", "format", fit_norm=0.9),
                       score("h01", "hook", fit_norm=0.2), score("t01", "topic", fit_norm=0.1)], WEIGHTS)
    selected = ["f01", "f02", "h01", "t01"]
    assert trim_briefs(selected, ranked, keep=5) == selected
    assert trim_briefs(selected, ranked, keep=3) == ["f01", "h01", "t01"]  # t01 is lowest but its facet's only one
    assert trim_briefs(selected, ranked, keep=2) == ["f01", "h01"]  # every facet down to one: now the lowest goes

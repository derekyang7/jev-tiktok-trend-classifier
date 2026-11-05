from datetime import UTC, datetime, timedelta

import pytest

from jevtrends.core import scoring

NOW = datetime(2026, 9, 28, tzinfo=UTC)


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
    probs = {"v1": {"t01": 0.7, "none_of_these": 0.3}, "v2": {"t01": 0.2, "t02": 0.8},
             "v3": {"none_of_these": 0.9, "t01": 0.1}}
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
    assert scoring.corpus_recent_share({}, start) == 0.0
    rising = {f"r{i}": 1.0 for i in range(10)}
    ratio, norm = scoring.momentum(rising, posted, start, c, 2)
    assert ratio == pytest.approx((10 + 2 / 3) / (12 / 3))
    assert norm == pytest.approx(0.8538, abs=1e-3)
    baseline = {f"r{i}": 1.0 for i in range(3)} | {f"o{i}": 1.0 for i in range(6)}
    assert scoring.momentum(baseline, posted, start, c, 2) == (pytest.approx(1.0), pytest.approx(0.5))
    assert scoring.momentum(rising, posted, start, 0.0, 2) == (1.0, 0.5)
    assert scoring.momentum(rising, posted, start, 1.0, 2) == (1.0, 0.5)


def test_breadth_promo_and_median_views():
    assert scoring.breadth_norm(0) == 0.0
    assert scoring.breadth_norm(20) == pytest.approx(1.0)
    assert scoring.breadth_norm(100) == 1.0
    members = {"a": 1.0, "b": 0.5}
    assert scoring.promo_share(members, {"a": 0.9, "b": 0.1}) == pytest.approx(1 / 1.5)
    assert scoring.promo_share({}, {}) == 0.0
    assert scoring.median_views(["a", "b", "c"], {"a": 10, "b": 30, "c": 20}) == 20.0
    assert scoring.median_views([], {}) == 0.0


def test_evidence_set_orders_by_probability_then_id_and_excludes_near_zero():
    assert scoring.evidence_set({"b": 0.9, "a": 0.9, "c": 0.1, "d": 0.5}, 3) == ["a", "b", "d"]
    assert scoring.evidence_set({"a": 0.9, "b": 0.3, "c": 0.1, "d": 0.0}, 12) == ["a", "b"]

import pytest

from jevtrends.config import Settings
from jevtrends.evaluation import compute_metrics, sample_for_labeling
from jevtrends.models import Answer
from jevtrends.store import Store
from tests.fakes import NOW, test_niches
from tests.helpers import make_video


def seeded_store(gate: dict[str, float], signal: dict[str, float], fintech: dict[str, float] | None = None):
    store = Store(":memory:")
    run_id = store.create_run({}, Settings(), test_niches(), NOW)
    for video_id, p in gate.items():
        store.upsert_video(make_video(id=video_id))
        store.add_run_video(run_id, video_id, "q")
        store.upsert_judgment(run_id, "video", video_id, "gate.maybe_signal", 1, Answer(value=p))
    for video_id, p in signal.items():
        store.upsert_judgment(run_id, "video", video_id, "judge.is_signal", 1, Answer(value=p))
        store.upsert_judgment(run_id, "video", video_id, "judge.signal_type", 1,
                              Answer(value="behavior_need", probabilities={"behavior_need": 0.9}, confidence=0.9))
        store.upsert_judgment(run_id, "video", video_id, "judge.niche_ai", 1, Answer(value=0.1))
        store.upsert_judgment(run_id, "video", video_id, "judge.niche_fintech_payments", 1,
                              Answer(value=(fintech or {}).get(video_id, 0.1)))
    return store, run_id


def test_sampler_strata_are_unbiased_and_skip_labeled_videos():
    gate = {f"v{i}": 0.9 for i in range(8)} | {"v8": 0.1, "v9": 0.1}
    signal = {"v0": 0.9, "v1": 0.9, "v2": 0.9, "v3": 0.9, "v4": 0.5, "v5": 0.5, "v6": 0.1, "v7": 0.1}
    store, run_id = seeded_store(gate, signal)
    store.add_label("v0", "is_signal", True, "random")
    sample = sample_for_labeling(store, run_id, n=10, seed=1)
    strata = {}
    for video_id, stratum in sample:
        strata.setdefault(stratum, []).append(video_id)
    assert len(strata["random"]) == 5 and set(strata["random"]) <= {f"v{i}" for i in range(1, 8)}
    assert sorted(strata["gate_dropped"]) == ["v8", "v9"]
    assert set(strata.get("borderline", [])) <= {"v4", "v5"}
    assert len({v for v, _ in sample}) == len(sample)
    assert "v0" not in {v for v, _ in sample}


def test_metrics_on_labels():
    gate = {v: 0.9 for v in ("a", "b", "c", "d")} | {"x": 0.1, "y": 0.1}
    signal = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.2}
    store, run_id = seeded_store(gate, signal, fintech={"a": 0.9, "b": 0.2, "c": 0.8, "d": 0.1})
    for video_id, is_signal, niches in (("a", True, ["fintech_payments"]), ("b", True, ["fintech_payments"]),
                                        ("c", False, []), ("d", True, [])):
        store.add_label(video_id, "is_signal", is_signal, "random")
        store.add_label(video_id, "niches", niches, "random")
    store.add_label("a", "signal_type", "behavior_need", "random")
    store.add_label("b", "signal_type", "complaint_workaround", "random")
    store.add_label("x", "is_signal", True, "gate_dropped")
    store.add_label("y", "is_signal", False, "gate_dropped")
    metrics = compute_metrics(store, run_id)
    assert metrics["is_signal"]["precision"] == pytest.approx(2 / 3)
    assert metrics["is_signal"]["recall"] == pytest.approx(2 / 3)
    assert metrics["niches"]["precision"] == pytest.approx(0.5)
    assert metrics["niches"]["recall"] == pytest.approx(0.5)
    assert metrics["gate_miss_rate"] == pytest.approx(0.5)
    assert metrics["signal_type_accuracy"] == pytest.approx(0.5)
    assert metrics["suggested_is_signal_threshold"] == pytest.approx(0.75)
    top_bucket = metrics["calibration"][-1]
    assert (top_bucket["count"], top_bucket["observed"]) == (2, 1.0)

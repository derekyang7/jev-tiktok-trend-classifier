from datetime import UTC, datetime

from jevtrends.config import NicheConfig, Settings
from jevtrends.models import Answer, Comment, Enrichment, Trend, TrendScore
from jevtrends.store import Store
from tests.helpers import make_video

NICHES = NicheConfig.model_validate({
    "niches": [{"id": "ai", "name": "AI", "covers": "c", "not_for": "n", "seed_queries": ["ai app"]}],
    "global_seed_queries": [],
})
T0 = datetime(2026, 9, 28, 12, tzinfo=UTC)


def new_store_and_run() -> tuple[Store, int]:
    store = Store(":memory:")
    run_id = store.create_run({"lookback_days": 30}, Settings(), NICHES, T0)
    return store, run_id


def test_run_lifecycle():
    store, run_id = new_store_and_run()
    run = store.get_run(run_id)
    assert run["status"] == "running"
    assert run["started_at"] == T0
    assert run["settings"].models.jev == "typesafe/jev-1.13"
    assert run["niches"].ids() == ["ai"]
    assert not store.stage_done(run_id, "collect")
    store.mark_stage_done(run_id, "collect")
    assert store.stage_done(run_id, "collect")
    store.set_run_status(run_id, "completed", finished=True)
    run = store.get_run(run_id)
    assert run["status"] == "completed" and run["finished_at"] is not None
    assert [r["id"] for r in store.list_runs()] == [run_id]


def test_videos_and_seed_query_merge():
    store, run_id = new_store_and_run()
    video = make_video()
    store.upsert_video(video)
    store.add_run_video(run_id, video.id, "budgeting app")
    store.add_run_video(run_id, video.id, "credit card hack")
    store.add_run_video(run_id, video.id, "budgeting app")
    assert store.get_video(video.id) == video
    assert store.run_video_ids(run_id) == [video.id]
    row = store.conn.execute("SELECT seed_queries FROM run_videos").fetchone()
    assert row["seed_queries"] == '["budgeting app", "credit card hack"]'
    store.set_short_id(run_id, video.id, "v001")
    assert store.short_ids(run_id) == {"v001": video.id}


def test_enrichment_roundtrip():
    store, _ = new_store_and_run()
    enrichment = Enrichment(video_id="1", transcript="hello", transcript_status="ok",
                            transcript_fetched_at=T0, comments=[Comment(text="same", likes=3)], comments_fetched_at=T0)
    store.upsert_enrichment(enrichment)
    assert store.get_enrichment("1") == enrichment
    assert store.get_enrichment("missing") is None


def test_judgments_are_idempotent_and_versioned():
    store, run_id = new_store_and_run()
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 1, Answer(value=0.2))
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 1, Answer(value=0.9))
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 2, Answer(value=0.1))
    store.upsert_judgment(run_id, "video", "2", "judge.signal_type", 1,
                          Answer(value="behavior_need", probabilities={"behavior_need": 0.8, "other": 0.2}, confidence=0.7))
    assert store.get_answers(run_id, "video", "judge.is_signal", 1) == {"1": Answer(value=0.9)}
    answer = store.get_answers(run_id, "video", "judge.signal_type", 1)["2"]
    assert answer.value == "behavior_need" and answer.probabilities["other"] == 0.2
    count = store.conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    assert count == 3


def test_trends_members_scores_briefs():
    store, run_id = new_store_and_run()
    trend = Trend(trend_id="t01", name="Rent splitting", kind="behavior_need", definition="d",
                  example_video_ids=["1"])
    store.upsert_trend(run_id, trend)
    store.upsert_trend(run_id, trend.model_copy(update={"status": "kept"}))
    assert store.list_trends(run_id, status="kept")[0].trend_id == "t01"
    store.replace_trend_members(run_id, [("t01", "1", 0.9), ("t01", "2", 0.4)])
    store.replace_trend_members(run_id, [("t01", "1", 0.8)])
    assert store.trend_members(run_id) == {"t01": {"1": 0.8}}
    score = TrendScore(trend_id="t01", support=0.8, creators=1, momentum_ratio=1.0, momentum_norm=0.5,
                       breadth_norm=0.2, median_views=100.0, promo_share=0.0, niche_affinity={"ai": 0.9},
                       niches=["ai"], primary_niche="ai", opportunity=0.6, rank=1)
    store.upsert_trend_score(run_id, score)
    assert store.list_trend_scores(run_id) == [score]
    store.upsert_brief(run_id, "t01", "anthropic/claude-opus-5", {"headline": "h"}, "ok")
    assert store.list_briefs(run_id) == {"t01": {"status": "ok", "brief": {"headline": "h"}}}


def test_spend_and_labels():
    store, run_id = new_store_and_run()
    store.record_api_call(run_id, "gate", "jev", "systemone", {"input_tokens": 100}, 0.01, "ok")
    store.record_api_call(run_id, "enrich", "scrapecreators", "transcript", {"credits": 1}, 0.00188, "ok")
    store.record_api_call(run_id, "judge", "jev", "systemone", {"input_tokens": 100}, 0.02, "ok")
    assert store.spend_by_provider(run_id) == {"jev": 0.03, "scrapecreators": 0.00188}
    assert round(store.total_spend(run_id), 5) == 0.03188
    store.add_label("1", "is_signal", True, "random")
    store.add_label("1", "is_signal", False, "random")
    assert store.list_labels() == [{"video_id": "1", "field": "is_signal", "value": False, "stratum": "random"}]


def test_run_notes_are_deduplicated_and_persisted():
    store, run_id = new_store_and_run()
    store.add_note(run_id, "momentum undefined")
    store.add_note(run_id, "momentum undefined")
    store.add_note(run_id, "budget trim: 11 briefs written instead of 20")
    assert store.notes(run_id) == ["momentum undefined", "budget trim: 11 briefs written instead of 20"]
    assert store.get_run(run_id)["params"]["lookback_days"] == 30


def test_failures_by_stage():
    store, run_id = new_store_and_run()
    store.record_api_call(run_id, "judge", "jev", "judge", {"item": "1"}, 0.0, "failed")
    store.record_api_call(run_id, "judge", "jev", "systemone", {}, 0.01, "ok")
    assert store.failures_by_stage(run_id) == {"judge": 1}

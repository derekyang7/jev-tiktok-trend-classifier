from datetime import UTC, datetime

from jevtrends.opportunities.config import NicheConfig, Settings
from jevtrends.opportunities.models import Trend, TrendScore
from jevtrends.opportunities.store import OpportunitiesStore

NICHES = NicheConfig.model_validate({
    "niches": [{"id": "ai", "name": "AI", "covers": "c", "not_for": "n", "seed_queries": ["ai app"]}],
    "global_seed_queries": [],
})
T0 = datetime(2026, 9, 28, 12, tzinfo=UTC)


def new_store_and_run() -> tuple[OpportunitiesStore, int]:
    store = OpportunitiesStore(":memory:")
    run_id = store.create_run({"lookback_days": 30}, Settings(), NICHES, T0)
    return store, run_id


def test_run_lifecycle_roundtrips_settings_and_niches():
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


def test_trends_members_scores_briefs_and_labels():
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
    store.add_label("1", "is_signal", True, "random")
    store.add_label("1", "is_signal", False, "random")
    assert store.list_labels() == [{"video_id": "1", "field": "is_signal", "value": False, "stratum": "random"}]

from datetime import UTC, datetime

from jevtrends.ugc.config import NicheProfile, ProductProfile, RunProfiles, UgcSettings
from jevtrends.ugc.models import FacetTrend, SoundCandidate, UgcTrendScore
from jevtrends.ugc.store import UgcStore
from tests.helpers import make_video

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
NICHE = NicheProfile(id="apps", name="Apps", covers="c", not_for="x", seed_queries=["q"])
PRODUCT = ProductProfile(id="p", name="P", what_it_does="w", claims_allowed=[{"id": "c1", "text": "Free"}])


def new_store_and_run(product: ProductProfile | None = None) -> tuple[UgcStore, int]:
    store = UgcStore(":memory:")
    return store, store.create_run({"niche": "apps"}, UgcSettings(), RunProfiles(niche=NICHE, product=product), T0)


def score(trend_id: str, facet: str, rank: int) -> UgcTrendScore:
    return UgcTrendScore(trend_id=trend_id, facet=facet, support=3.0, creators=3, momentum_ratio=1.0,
                         momentum_norm=0.5, reach_ratio=1.0, eng_ratio=1.0, performance_norm=0.5, breadth_norm=0.4,
                         score=1 - rank / 10, rank_overall=rank, rank_in_facet=1)


def test_runs_roundtrip_ugc_settings_and_profiles_and_share_v1_helpers():
    store, run_id = new_store_and_run(PRODUCT)
    run = store.get_run(run_id)
    assert run["settings"].scan.lookback_days == 14 and run["niche"] == NICHE and run["product"] == PRODUCT
    assert new_store_and_run()[0].get_run(1)["product"] is None
    store.add_note(run_id, "n")
    store.mark_stage_done(run_id, "collect")
    assert store.notes(run_id) == ["n"] and store.stage_done(run_id, "collect")
    store.upsert_video(make_video(id="v1"))
    assert store.get_video("v1").id == "v1"


def test_facet_trends_filter_by_facet_and_status():
    store, run_id = new_store_and_run()
    store.upsert_facet_trend(run_id, FacetTrend(trend_id="h01", facet="hook", name="POV", template="POV: ___"))
    store.upsert_facet_trend(run_id, FacetTrend(trend_id="f01", facet="format", name="Green screen"))
    store.upsert_facet_trend(run_id, FacetTrend(trend_id="f01", facet="format", name="Green screen", status="kept"))
    assert [t.trend_id for t in store.list_facet_trends(run_id)] == ["f01", "h01"]
    assert [t.trend_id for t in store.list_facet_trends(run_id, facet="format", status="kept")] == ["f01"]
    assert store.list_facet_trends(run_id, facet="hook")[0].template == "POV: ___"


def test_replace_members_only_touches_the_listed_trends():
    store, run_id = new_store_and_run()
    store.replace_members(run_id, ["f01"], [("f01", "a", 0.9), ("f01", "b", 0.2)])
    store.replace_members(run_id, ["s01"], [("s01", "a", 1.0)])
    store.replace_members(run_id, ["f01"], [("f01", "a", 0.8)])
    assert store.facet_members(run_id) == {"f01": {"a": 0.8}, "s01": {"a": 1.0}}


def test_sounds_and_samples_keep_insertion_order_and_relevance():
    store, run_id = new_store_and_run()
    store.upsert_sound(run_id, SoundCandidate(sound_id="9", title="B", source=["popular"]))
    store.upsert_sound(run_id, SoundCandidate(sound_id="1", title="A", source=["niche"]))
    store.upsert_sound(run_id, SoundCandidate(sound_id="9", title="B", source=["popular"], sampled=True,
                                              niche_creators=2, niche_share=0.5))
    assert [(s.sound_id, s.sampled) for s in store.list_sounds(run_id)] == [("9", True), ("1", False)]
    store.upsert_sound_sample(run_id, "9", "v1", None)
    store.upsert_sound_sample(run_id, "9", "v2", None)
    store.upsert_sound_sample(run_id, "9", "v1", 0.8)
    assert store.sound_samples(run_id) == {"9": {"v1": 0.8, "v2": None}}


def test_scores_pairs_briefs_and_reviews():
    store, run_id = new_store_and_run()
    store.replace_ugc_scores(run_id, [score("h01", "hook", 2), score("f01", "format", 1)])
    assert [s.trend_id for s in store.list_ugc_scores(run_id)] == ["f01", "h01"]
    store.replace_ugc_scores(run_id, [score("h01", "hook", 1)])
    assert [s.trend_id for s in store.list_ugc_scores(run_id)] == ["h01"]
    store.replace_pairs(run_id, [("f01", "h01", 2.5, 1.8), ("f01", "s01", 4.0, 2.0)])
    assert store.pairs(run_id) == {"f01": [("s01", 4.0, 2.0), ("h01", 2.5, 1.8)]}
    store.upsert_ugc_brief(run_id, "f01", "opus", {"title": "t"}, "ok")
    store.upsert_ugc_brief(run_id, "h01", "opus", None, "failed")
    assert store.list_ugc_briefs(run_id) == {"f01": {"status": "ok", "brief": {"title": "t"}},
                                            "h01": {"status": "failed", "brief": None}}
    store.add_review(run_id, "f01", "", "would_brief", True)
    store.add_review(run_id, "f01", "", "would_brief", False)
    store.add_review(run_id, "f01", "v1", "fits", True)
    assert store.list_reviews(run_id) == [
        {"trend_id": "f01", "video_id": "", "field": "would_brief", "value": False},
        {"trend_id": "f01", "video_id": "v1", "field": "fits", "value": True}]

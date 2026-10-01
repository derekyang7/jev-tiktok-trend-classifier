import math
from datetime import UTC, datetime

import pytest

from jevtrends.models import Answer
from jevtrends.ugc.models import FacetTrend, SoundCandidate
from jevtrends.ugc.stages.score import run_score
from tests.fakes import FakeJev
from tests.helpers import make_video
from tests.ugc.fakes import make_ugc_ctx

RECENT, OLD = datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
RULES = {"fit": lambda s, k: 3.0 if s["trend"]["facet"] == "format" else 1.5,
         "product_fit": lambda s, k: 2.0,
         "ease": lambda s, k: 2.0,
         "brand_risk": lambda s, k: 0.9 if s["trend"]["facet"] == "sound" else 0.1}


def scored_world(with_product: bool = False):
    jev = FakeJev(rules=RULES)
    ctx = make_ugc_ctx(jev=jev, with_product=with_product)
    members = [make_video(id=f"m{i}", author_handle=f"a{i}", posted_at=RECENT, views=10_000, author_followers=1_000,
                          saves=400, shares=100, ad_flags={"is_ad": i == 0}) for i in range(4)]
    others = [make_video(id=f"o{i}", author_handle=f"b{i}", posted_at=OLD, views=1_000, author_followers=1_000,
                         saves=5, shares=5) for i in range(3)]
    zero = make_video(id="o3", author_handle="b3", posted_at=OLD, views=0, author_followers=None, saves=0, shares=0)
    for video in [*members, *others, zero]:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "keyword:apps you need")
        for question in ("ugc_gate.relevant", "ugc_judge.relevant"):
            ctx.store.upsert_judgment(ctx.run_id, "video", video.id, question, 1, Answer(value=0.9))
    ctx.store.upsert_sound(ctx.run_id, SoundCandidate(sound_id="777", title="Song", source=["popular"],
                                                      trend=[0.1, 0.1, 0.1, 0.1, 0.4, 0.4], niche_creators=5))
    for trend in (FacetTrend(trend_id="f01", facet="format", name="Green screen", status="kept"),
                  FacetTrend(trend_id="h01", facet="hook", name="POV", template="POV: ___", status="kept"),
                  FacetTrend(trend_id="s01", facet="sound", name="Song", sound_id="777", status="kept"),
                  FacetTrend(trend_id="f02", facet="format", name="Pruned", status="pruned")):
        ctx.store.upsert_facet_trend(ctx.run_id, trend)
    shared = [(tid, v.id, 0.9) for tid in ("f01", "h01") for v in members]
    shared += [(tid, v.id, 0.05) for tid in ("f01", "h01") for v in [*others, zero]]
    ctx.store.replace_members(ctx.run_id, ["f01", "h01", "s01"], shared + [("s01", "m0", 1.0), ("s01", "m1", 1.0)])
    return ctx, jev


async def test_score_computes_code_metrics_jev_scores_ranks_and_pairs():
    ctx, jev = scored_world()
    await run_score(ctx)
    scores = {s.trend_id: s for s in ctx.store.list_ugc_scores(ctx.run_id)}
    assert set(scores) == {"f01", "h01", "s01"}  # pruned trends are not scored
    f01 = scores["f01"]
    assert f01.support == pytest.approx(3.8) and f01.creators == 4
    assert f01.momentum_ratio == pytest.approx(4.6 / 2.9)  # (3.6 + 2*0.5) / ((3.8 + 2) * 0.5)
    assert f01.reach_ratio > 1 and f01.eng_ratio > 1 and f01.performance_norm > 0.6
    assert (f01.fit_norm, f01.ease_norm, f01.risky) == (1.0, pytest.approx(2 / 3), False)
    assert f01.ad_share == pytest.approx(0.9 / 3.8) and f01.median_views == 10_000
    s01 = scores["s01"]
    assert s01.momentum_ratio == pytest.approx(2.0)  # from the usage series
    assert s01.performance_norm == 0.5  # only 2 corpus uses
    assert s01.breadth_norm == pytest.approx(math.log(6) / math.log(21)) and s01.risky
    assert f01.rank_overall == 1 and scores["h01"].rank_in_facet == 1
    pairs = ctx.store.pairs(ctx.run_id)
    assert [p for p, _, _ in pairs["f01"]] == ["h01"] and "s01" not in pairs
    state = next(s for s, q in jev.calls if s["trend"]["name"] == "Green screen")
    assert set(state) == {"niche", "trend", "evidence"} and len(state["evidence"]) == 4
    assert set(jev.calls[0][1]) == {"fit", "ease", "brand_risk"}
    calls = len(jev.calls)
    await run_score(ctx)
    assert len(jev.calls) == calls


async def test_a_product_profile_switches_fit_for_product_fit():
    ctx, jev = scored_world(with_product=True)
    await run_score(ctx)
    state, questions = jev.calls[0]
    assert set(questions) == {"product_fit", "ease", "brand_risk"}
    assert state["product"]["name"] == "StreakBuddy"
    assert all(s.fit_norm == pytest.approx(2 / 3) for s in ctx.store.list_ugc_scores(ctx.run_id))

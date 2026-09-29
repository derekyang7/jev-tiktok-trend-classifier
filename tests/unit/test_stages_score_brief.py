from datetime import UTC, datetime

import pytest

from jevtrends.llm.prompts import BriefOut, EvidenceRef, StartupAngle
from jevtrends.models import Trend
from jevtrends.stages.assign import run_assign
from jevtrends.stages.brief import run_brief, selected_trends
from jevtrends.stages.gate import run_gate
from jevtrends.stages.judge import run_judge
from jevtrends.stages.score import evidence_set, run_score
from tests.fakes import FakeJev, FakeLLM, make_ctx
from tests.helpers import make_video

RECENT, OLD = datetime(2026, 9, 25, tzinfo=UTC), datetime(2026, 9, 5, tzinfo=UTC)
RULES = {
    "is_signal": lambda state, key: 0.2 if state["caption"] == "just vibes" else 0.9,
    "is_promotional": lambda state, key: 0.1,
    "niche_*": lambda state, key: 0.8 if key == "niche_fintech_payments" else 0.1,
    "trend": lambda state, key: "t01" if "rent" in state["caption"] else "none_of_these",
    "pain": lambda state, key: 3.0,
    "spend": lambda state, key: 1.5,
    "underserved": lambda state, key: 3.0,
    "mentions_solutions": lambda state, key: 0.2,
}


def brief_out(*video_ids: str) -> BriefOut:
    return BriefOut(headline="Renters want painless bill splitting", whats_happening="w", who="renters",
                    underlying_need="n", evidence=[EvidenceRef(video_id=v, why="shows it") for v in video_ids],
                    existing_solutions=["Venmo"], startup_angles=[StartupAngle(idea="i", why_now="now")],
                    risks=["r"])


async def scored_ctx(recent_for=("a", "b"), llm=None):
    ctx = make_ctx(jev=FakeJev(rules=RULES), llm=llm)
    captions = {"a": "splitting rent with venmo", "b": "rent split app please", "c": "our rent spreadsheet",
                "d": "rent day again", "e": "new phone who dis", "x": "just vibes"}
    handles = {"a": "c1", "b": "c2", "c": "c3", "d": "c3", "e": "c4", "x": "c5"}
    for vid, caption in captions.items():
        video = make_video(id=vid, author_handle=handles[vid], caption=caption,
                           posted_at=RECENT if vid in recent_for else OLD)
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, vid, "q")
    await run_gate(ctx)
    await run_judge(ctx)
    ctx.store.upsert_trend(ctx.run_id, Trend(trend_id="t01", name="Rent splitting", kind="behavior_need",
                                             definition="Roommates split rent.", example_video_ids=["a"]))
    ctx.store.upsert_trend(ctx.run_id, Trend(trend_id="t02", name="Phones", kind="product_traction", definition="d"))
    await run_assign(ctx)
    await run_score(ctx)
    return ctx


def test_evidence_set_orders_by_probability_then_id():
    assert evidence_set({"b": 0.9, "a": 0.9, "c": 0.1, "d": 0.5}, 3) == ["a", "b", "d"]


async def test_score_computes_metrics_jev_scores_and_rank():
    ctx = await scored_ctx()
    [score] = ctx.store.list_trend_scores(ctx.run_id)
    assert score.trend_id == "t01" and score.rank == 1
    assert score.support == pytest.approx(3.65)
    assert score.creators == 3
    assert score.momentum_ratio == pytest.approx(2.6 / 2.26)
    assert score.momentum_norm == pytest.approx(0.5505, abs=1e-3)
    assert (score.niches, score.primary_niche) == (["fintech_payments"], "fintech_payments")
    assert (score.pain_norm, score.spend_norm, score.underserved_norm) == (1.0, 0.5, 0.5)
    assert (score.promo_share, score.median_views) == (0.0, 1000.0)
    assert score.opportunity == pytest.approx(0.6107, abs=1e-3)
    state = ctx.jev.calls[-1][0]
    assert state["trend"]["name"] == "Rent splitting" and len(state["evidence"]) == 4  # e (p=0.05) excluded
    assert ctx.store.notes(ctx.run_id) == []


async def test_score_notes_undefined_momentum():
    ctx = await scored_ctx(recent_for=("a", "b", "c", "d", "e", "x"))
    [score] = ctx.store.list_trend_scores(ctx.run_id)
    assert score.momentum_norm == 0.5
    assert "Momentum is undefined" in ctx.store.notes(ctx.run_id)[0]


async def test_brief_maps_short_evidence_ids_and_drops_unknown_ones():
    llm = FakeLLM(lambda system, user, schema: brief_out("e01", "e99"))
    ctx = await scored_ctx(llm=llm)
    assert selected_trends(ctx) == ["t01"]
    await run_brief(ctx)
    stored = ctx.store.list_briefs(ctx.run_id)["t01"]
    assert stored["status"] == "ok"
    assert [e["video_id"] for e in stored["brief"]["evidence"]] == ["a"]
    assert '"video_id": "e01"' in llm.calls[0][1]
    await run_brief(ctx)
    assert len(llm.calls) == 1


async def test_brief_marks_failure_when_no_valid_evidence():
    ctx = await scored_ctx(llm=FakeLLM(lambda system, user, schema: brief_out("e99")))
    await run_brief(ctx)
    assert ctx.store.list_briefs(ctx.run_id)["t01"] == {"status": "failed", "brief": None}
    assert ctx.store.spend_by_provider(ctx.run_id)["llm"] > 0


async def test_brief_respects_budget_limit():
    llm = FakeLLM(lambda system, user, schema: brief_out("e01"))
    ctx = await scored_ctx(llm=llm)
    ctx.limits["max_briefs"] = 0
    await run_brief(ctx)
    assert llm.calls == []


def test_evidence_set_excludes_near_zero_probabilities():
    # Real Jev choice probabilities are mostly exactly 0; those videos are not evidence for the trend.
    assert evidence_set({"a": 0.9, "b": 0.3, "c": 0.1, "d": 0.0}, 12) == ["a", "b"]

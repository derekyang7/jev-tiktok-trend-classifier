import pytest

from jevtrends.jev.questions import IS_SIGNAL
from jevtrends.llm.prompts import DiscoverOut, TrendProposal
from jevtrends.models import Comment, Enrichment, Trend
from jevtrends.stages.assign import run_assign
from jevtrends.stages.discover import clean_proposals, digest_line, run_discover
from jevtrends.stages.gate import run_gate
from jevtrends.stages.judge import run_judge, signal_videos, truncate_words, video_state
from tests.fakes import FakeJev, FakeLLM, make_ctx
from tests.helpers import make_video

RULES = {
    "is_signal": lambda state, key: 0.2 if state["caption"] == "just vibes" else 0.9,
    "is_promotional": lambda state, key: 0.1,
    "niche_*": lambda state, key: 0.8 if key == "niche_fintech_payments" else 0.1,
    "trend": lambda state, key: "t01" if "rent" in state["caption"] else "none_of_these",
}


async def judged_ctx(videos, llm=None, rules=None):
    ctx = make_ctx(jev=FakeJev(rules=rules or RULES), llm=llm)
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "q")
    await run_gate(ctx)
    await run_judge(ctx)
    return ctx


def rent_videos():
    return [make_video(id="a", author_handle="c1", caption="splitting rent with venmo"),
            make_video(id="b", author_handle="c2", caption="rent split app please"),
            make_video(id="c", author_handle="c3", caption="our rent spreadsheet"),
            make_video(id="d", author_handle="c3", caption="rent day again"),
            make_video(id="e", author_handle="c4", caption="new phone who dis"),
            make_video(id="x", author_handle="c5", caption="just vibes")]


def test_video_state_with_empty_fields_and_truncation():
    video = make_video(caption="", hashtags=[])
    assert video_state(video, None, 1500) == {"caption": "", "hashtags": [], "transcript": "", "top_comments": [],
                                              "creator_bio": ""}
    enrichment = Enrichment(video_id=video.id, transcript="one two three four", comments=[Comment(text="hi")])
    state = video_state(video, enrichment, 2)
    assert (state["transcript"], state["top_comments"]) == ("one two", ["hi"])
    assert truncate_words(None, 5) == ""


async def test_judge_asks_all_questions_once_and_filters_signals():
    ctx = await judged_ctx(rent_videos())
    keys = set(ctx.jev.calls[-1][1])
    assert keys == {"is_signal", "signal_type", "is_promotional", "niche_ai", "niche_fintech_payments"}
    assert signal_videos(ctx) == ["a", "b", "c", "d", "e"]
    calls = len(ctx.jev.calls)
    await run_judge(ctx)
    assert len(ctx.jev.calls) == calls


def test_digest_line_handles_empty_fields():
    line = digest_line("v001", make_video(caption="", author_handle="c1"), None, "behavior_need", [], False)
    assert line == '[v001] @c1 | behavior_need | niches: none | promo: no | "" | transcript: "" | top comment: ""'


def test_clean_proposals_drops_unknown_ids_and_renumbers():
    out = DiscoverOut(trends=[
        TrendProposal(id="x1", name="Rent splitting", kind="behavior_need", definition="d",
                      example_video_ids=["v001", "v999", " v002 "]),
        TrendProposal(id="x1", name="Second", kind="complaint_workaround", definition="d2", example_video_ids=[]),
    ])
    trends = clean_proposals(out, {"v001": "a", "v002": "b"}, max_candidates=60)
    assert [(t.trend_id, t.example_video_ids) for t in trends] == [("t01", ["a", "b"]), ("t02", [])]
    assert len(clean_proposals(out, {}, max_candidates=1)) == 1


async def test_discover_builds_digest_calls_llm_once_and_stores_trends():
    proposal = DiscoverOut(trends=[TrendProposal(id="t01", name="Rent splitting", kind="behavior_need",
                                                 definition="Roommates split rent.", example_video_ids=["v001", "v002"])])
    llm = FakeLLM(lambda system, user, schema: proposal)
    ctx = await judged_ctx(rent_videos(), llm=llm)
    await run_discover(ctx)
    user_prompt = llm.calls[0][1]
    assert user_prompt.count("\n[v") == 5 and "niches: fintech_payments" in user_prompt
    assert [t.name for t in ctx.store.list_trends(ctx.run_id)] == ["Rent splitting"]
    assert set(ctx.store.short_ids(ctx.run_id).values()) == {"a", "b", "c", "d", "e"}
    assert ctx.store.spend_by_provider(ctx.run_id)["llm"] == pytest.approx((1000 * 5 + 200 * 25) / 1e6)
    await run_discover(ctx)
    assert len(llm.calls) == 1


async def test_discover_skips_llm_when_there_are_no_signals():
    llm = FakeLLM(lambda *args: pytest.fail("LLM must not be called"))
    rules = {**RULES, "is_signal": lambda state, key: 0.1}
    ctx = await judged_ctx(rent_videos(), llm=llm, rules=rules)
    await run_discover(ctx)
    assert ctx.store.list_trends(ctx.run_id) == []
    assert "No signal videos" in ctx.store.notes(ctx.run_id)[0]


async def test_assign_prunes_weak_trends_and_self_checks():
    ctx = await judged_ctx(rent_videos())
    ctx.store.upsert_trend(ctx.run_id, Trend(trend_id="t01", name="Rent splitting", kind="behavior_need",
                                             definition="d", example_video_ids=["a", "b"]))
    ctx.store.upsert_trend(ctx.run_id, Trend(trend_id="t02", name="Phones", kind="product_traction",
                                             definition="d", example_video_ids=["e"]))
    await run_assign(ctx)
    trends = {t.trend_id: t for t in ctx.store.list_trends(ctx.run_id)}
    assert (trends["t01"].status, trends["t01"].self_check_agreement) == ("kept", 1.0)
    assert trends["t02"].status == "pruned" and trends["t02"].prune_reason.startswith("support")
    assert trends["t02"].self_check_agreement == 0.0
    members = ctx.store.trend_members(ctx.run_id)
    assert members["t01"]["a"] == pytest.approx(0.9) and len(members["t02"]) == 5
    assert ctx.store.notes(ctx.run_id) == []


async def test_assign_warns_when_none_rate_is_high():
    rules = {**RULES, "trend": lambda state, key: "none_of_these"}
    ctx = await judged_ctx(rent_videos(), rules=rules)
    ctx.store.upsert_trend(ctx.run_id, Trend(trend_id="t01", name="Rent", kind="behavior_need", definition="d"))
    await run_assign(ctx)
    assert "fit none of the proposed trends" in ctx.store.notes(ctx.run_id)[0]

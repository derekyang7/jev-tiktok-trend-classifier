from datetime import UTC, datetime, timedelta

import pytest

from jevtrends.config import Settings
from jevtrends.http import TransientAPIError
from jevtrends.jev.questions import MAYBE_SIGNAL
from jevtrends.models import Comment, Enrichment
from jevtrends.stages.collect import is_english_or_unknown, run_collect
from jevtrends.stages.context import StageFailed, run_items
from jevtrends.stages.enrich import run_enrich
from jevtrends.stages.gate import gate_state, gate_survivors, run_gate
from tests.fakes import NOW, FakeJev, FakeSource, make_ctx
from tests.helpers import make_video


def sequential_settings(**scan) -> Settings:
    settings = Settings()
    settings.scan = settings.scan.model_copy(update=scan)
    settings.concurrency = settings.concurrency.model_copy(update={"scraper": 1, "jev": 1})
    return settings


def search_pages() -> dict:
    v = {i: make_video(id=f"v{i}", author_handle=f"c{i}") for i in range(1, 9)}
    v[2] = make_video(id="v2", posted_at=datetime(2026, 8, 1, tzinfo=UTC))
    v[3] = make_video(id="v3", language="es")
    return {"ai app": [[v[1], v[1], v[2], v[3]], [v[4]]],
            "budgeting app": [[v[1], v[5], v[6]]],
            "rant": [[v[7], v[8]]]}


def add_videos(ctx, *videos) -> None:
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "q")


def test_is_english_or_unknown():
    assert [is_english_or_unknown(x) for x in (None, "", "en", "un", "es")] == [True, True, True, True, False]


async def test_collect_dedupes_filters_and_caps_per_query():
    source = FakeSource(pages=search_pages())
    ctx = make_ctx(source=source, settings=sequential_settings(max_videos=6))
    await run_collect(ctx)
    assert ctx.store.run_video_ids(ctx.run_id) == ["v1", "v4", "v5", "v6", "v7", "v8"]
    seeds = ctx.store.conn.execute("SELECT seed_queries FROM run_videos WHERE video_id = 'v1'").fetchone()[0]
    assert seeds == '["ai app", "budgeting app"]'
    assert [c for c in source.calls if c[0] == "search"] == [
        ("search", "ai app", None), ("search", "ai app", 1), ("search", "budgeting app", None), ("search", "rant", None)]
    assert ctx.store.spend_by_provider(ctx.run_id)["scrapecreators"] == pytest.approx(4 * 0.00188)


async def test_collect_respects_global_max_videos():
    ctx = make_ctx(source=FakeSource(pages=search_pages()), settings=sequential_settings(max_videos=2))
    await run_collect(ctx)
    assert ctx.store.run_video_ids(ctx.run_id) == ["v1", "v5"]


async def test_gate_handles_empty_caption_applies_threshold_and_resumes():
    jev = FakeJev(rules={"maybe_signal": lambda state, key: 0.1 if "dance" in state["caption"] else 0.5})
    ctx = make_ctx(jev=jev)
    add_videos(ctx, make_video(id="a", caption="", hashtags=[]),
               make_video(id="b", caption="dance challenge", hashtags=["dance"]), make_video(id="c"))
    assert gate_state(ctx.store.get_video("a")) == {"caption": "", "hashtags": []}
    await run_gate(ctx)
    assert gate_survivors(ctx) == ["a", "c"]
    await run_gate(ctx)
    assert len(jev.calls) == 3


async def test_enrich_transcripts_for_survivors_and_comments_for_top_videos():
    source = FakeSource(transcripts={"a": "hello world", "c": None},
                        comments={"c": [Comment(text="what app is this", likes=9)], "a": [Comment(text="same", likes=1)]})
    ctx = make_ctx(source=source, jev=FakeJev(rules={"maybe_signal": lambda s, k: 0.1 if s["caption"] == "dance" else 0.9}))
    add_videos(ctx, make_video(id="a", comment_count=5), make_video(id="b", caption="dance"),
               make_video(id="c", comment_count=50))
    await run_gate(ctx)
    ctx.limits["comments_top_videos"] = 1
    await run_enrich(ctx)
    a, c = ctx.store.get_enrichment("a"), ctx.store.get_enrichment("c")
    assert (a.transcript, a.transcript_status) == ("hello world", "ok")
    assert (c.transcript, c.transcript_status) == (None, "missing")
    assert ctx.store.get_enrichment("b") is None
    assert c.comments == [Comment(text="what app is this", likes=9)]
    assert a.comments is None
    calls_before = list(source.calls)
    await run_enrich(ctx)
    assert source.calls == calls_before


async def test_enrich_refreshes_stale_comments_but_not_transcripts():
    source = FakeSource(transcripts={"a": "t"}, comments={"a": [Comment(text="new", likes=1)]})
    ctx = make_ctx(source=source)
    add_videos(ctx, make_video(id="a"))
    ctx.store.upsert_enrichment(Enrichment(video_id="a", transcript="t", transcript_status="ok",
                                           comments=[Comment(text="old")], comments_fetched_at=NOW - timedelta(days=8)))
    await run_gate(ctx)
    await run_enrich(ctx)
    assert ctx.store.get_enrichment("a").comments == [Comment(text="new", likes=1)]
    assert ("transcript", "a") not in source.calls


async def test_run_items_failure_rate_uses_the_stage_total():
    ctx = make_ctx()

    async def always_fails(item):
        raise TransientAPIError("jev", 503, "busy")

    assert await run_items(ctx, "judge", "jev", list(range(7)), always_fails, 2, total=100) == 7
    with pytest.raises(StageFailed):
        await run_items(ctx, "judge", "jev", list(range(7)), always_fails, 2)


async def test_gate_resume_is_not_stuck_by_a_few_persistent_failures():
    failing = {"v0", "v1", "v2"}
    jev = FakeJev(fail_when=lambda s, q: TransientAPIError("jev", 503, "busy") if s["caption"] in failing else None)
    ctx = make_ctx(jev=jev)
    add_videos(ctx, *(make_video(id=f"x{i}", caption=f"v{i}") for i in range(10)))
    with pytest.raises(StageFailed):
        await run_gate(ctx)  # 3 of 10 fail: 30% of the stage
    failing.intersection_update({"v0"})
    await run_gate(ctx)  # one persistent failure is 10% of the stage, not 1 of the 3 retried
    assert len(ctx.answers(MAYBE_SIGNAL)) == 9

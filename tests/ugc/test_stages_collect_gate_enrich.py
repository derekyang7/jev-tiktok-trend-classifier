from datetime import UTC, datetime

import pytest

from jevtrends.http import FatalAPIError, TransientAPIError
from jevtrends.models import Answer, Comment
from jevtrends.ugc.stages.collect import run_collect
from jevtrends.ugc.stages.enrich import run_enrich
from jevtrends.ugc.stages.gate import gate_survivors, run_gate
from tests.fakes import FakeJev
from tests.helpers import make_video
from tests.ugc.fakes import FakeUgcSource, make_ugc_ctx, sequential


def add_videos(ctx, *videos, passed: bool = False) -> None:
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "keyword:apps you need")
        if passed:
            ctx.store.upsert_judgment(ctx.run_id, "video", video.id, "ugc_gate.relevant", 1, Answer(value=0.9))


async def test_collect_runs_keyword_hashtag_and_top_searches_and_dedupes_across_them():
    v = {i: make_video(id=f"v{i}", author_handle=f"c{i}") for i in range(1, 5)}
    old = make_video(id="old", posted_at=datetime(2026, 9, 1, tzinfo=UTC))
    photo = make_video(id="p1", is_slideshow=True, slide_urls=["https://cdn/p1a", "https://cdn/p1b"])
    source = FakeUgcSource(pages={"apps you need": [[v[1], v[2], old]]},
                           hashtag_pages={"appsyouneed": [[v[2], v[3]]]},
                           top_pages={"apps you need": [[photo, v[4]]]})
    ctx = make_ugc_ctx(source=source, settings=sequential(max_videos=30))
    await run_collect(ctx)
    assert ctx.store.run_video_ids(ctx.run_id) == ["v1", "v2", "v3", "p1", "v4"]
    seeds = ctx.store.conn.execute("SELECT seed_queries FROM run_videos WHERE video_id = 'v2'").fetchone()[0]
    assert seeds == '["keyword:apps you need", "hashtag:appsyouneed"]'
    assert ctx.store.done_queries(ctx.run_id) == {"keyword:apps you need", "hashtag:appsyouneed",
                                                  "top:apps you need"}
    assert ctx.store.spend_by_provider(ctx.run_id)["scrapecreators"] == pytest.approx(3 * 0.00188)
    await run_collect(ctx)
    assert len(source.calls) == 3  # every search is done, so a resume makes no requests


async def test_top_search_failures_degrade_but_account_errors_stop_the_run():
    source = FakeUgcSource(pages={"apps you need": [[make_video(id="a")]]},
                           fail_top=TransientAPIError("scrapecreators", 503, "down"))
    ctx = make_ugc_ctx(source=source)
    await run_collect(ctx)
    assert ctx.store.run_video_ids(ctx.run_id) == ["a"]
    assert any("Top search was unavailable" in note for note in ctx.store.notes(ctx.run_id))
    broke = make_ugc_ctx(source=FakeUgcSource(fail_top=FatalAPIError("scrapecreators", 402, "no credits")))
    with pytest.raises(FatalAPIError):
        await run_collect(broke)


async def test_gate_uses_the_niche_question_and_threshold_and_resumes():
    jev = FakeJev(rules={"relevant": lambda state, key: 0.1 if "cat" in state["caption"] else 0.6})
    ctx = make_ugc_ctx(jev=jev)
    add_videos(ctx, make_video(id="a", caption="5 apps you need"), make_video(id="b", caption="my cat"),
               make_video(id="c", caption="", hashtags=[]))
    await run_gate(ctx)
    assert gate_survivors(ctx) == ["a", "c"]
    state, questions = jev.calls[0]
    assert set(state) == {"caption", "hashtags"}
    assert questions["relevant"]["instructions"]["niche"]["name"] == "Consumer apps"
    await run_gate(ctx)
    assert len(jev.calls) == 3


async def test_enrich_skips_slideshow_transcripts_and_fetches_comments_for_top_videos():
    source = FakeUgcSource(transcripts={"a": "hello"}, comments={"b": [Comment(text="which app?", likes=3)]})
    ctx = make_ugc_ctx(source=source)
    add_videos(ctx, make_video(id="a", comment_count=1), make_video(id="b", comment_count=50),
               make_video(id="s", is_slideshow=True, slide_urls=["https://cdn/s1"], comment_count=5), passed=True)
    ctx.limits["comments_top_videos"] = 1
    await run_enrich(ctx)
    assert ctx.store.get_enrichment("s").transcript_status == "not_applicable"
    assert ("transcript", "s") not in source.calls
    assert ctx.store.get_enrichment("a").transcript == "hello"
    assert ctx.store.get_enrichment("b").transcript_status == "missing"
    assert [call for call in source.calls if call[0] == "comments"] == [("comments", "b")]
    calls = len(source.calls)
    await run_enrich(ctx)
    assert len(source.calls) == calls

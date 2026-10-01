import pytest

from jevtrends.http import FatalAPIError, TransientAPIError
from jevtrends.models import Answer, Enrichment, SoundInfo, VisionRead
from jevtrends.sources.base import Song
from jevtrends.ugc.stages.judge import promotional_videos, relevant_videos, run_judge, ugc_video_state
from jevtrends.ugc.stages.sounds import interleave, run_sounds
from tests.fakes import FakeJev
from tests.helpers import make_video
from tests.ugc.fakes import FakeUgcSource, make_ugc_ctx

RULES = {"relevant": lambda state, key: 0.1 if "cat" in state["caption"] or "dance" in state["caption"] else 0.9,
         "is_promotional": lambda state, key: 0.8 if "#ad" in state["caption"] else 0.1}


def passed(ctx, *videos) -> None:
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "keyword:apps you need")
        ctx.store.upsert_judgment(ctx.run_id, "video", video.id, "ugc_gate.relevant", 1, Answer(value=0.9))


def song(sound_id: str, rank: int, commercial: bool | None = None) -> Song:
    return Song(sound_id=sound_id, title=f"Song {sound_id}", author="Artist", rank=rank,
                link=f"https://www.tiktok.com/music/song-{sound_id}", commercial=commercial,
                trend=[0.1, 0.2, 0.3, 0.4, 0.5, 0.9])


def sound(sound_id: str, **flags) -> SoundInfo:
    return SoundInfo(id=sound_id, title=f"sound {sound_id}", author="someone", use_count=500, licensing=flags)


async def test_judge_reads_on_screen_text_and_marks_relevant_and_promotional_videos():
    jev = FakeJev(rules=RULES)
    ctx = make_ugc_ctx(jev=jev)
    passed(ctx, make_video(id="a", caption="5 apps you need"), make_video(id="b", caption="my cat"),
           make_video(id="c", caption="app haul #ad"), make_video(id="d", caption="app of the day",
                                                                  ad_flags={"is_paid_partnership": True}))
    ctx.store.upsert_enrichment(Enrichment(video_id="a", vision=VisionRead(on_screen_text="APPS YOU NEED",
                                                                           setup="phone screen")))
    await run_judge(ctx)
    state = next(s for s, q in jev.calls if s["caption"] == "5 apps you need")
    assert state["on_screen_text"] == "APPS YOU NEED" and state["setup"] == "phone screen"
    assert set(jev.calls[0][1]) == {"relevant", "is_promotional"}
    assert relevant_videos(ctx) == ["a", "c", "d"]
    assert promotional_videos(ctx) == {"c", "d"}
    await run_judge(ctx)
    assert len(jev.calls) == 4


def test_ugc_video_state_has_empty_strings_without_an_enrichment():
    assert ugc_video_state(make_video(caption="", hashtags=[]), None, 1500) == {
        "caption": "", "hashtags": [], "on_screen_text": "", "setup": "", "transcript": "", "top_comments": []}


def test_interleave_alternates_without_repeats():
    a, b = [song("1", 1), song("2", 2), song("3", 3)], [song("2", 1), song("9", 2)]
    assert [s.sound_id for s in interleave(a, b, limit=10)] == ["1", "2", "9", "3"]
    assert [s.sound_id for s in interleave(a, b, limit=2)] == ["1", "2"]


def niche_world(source: FakeUgcSource, jev=None):
    ctx = make_ugc_ctx(source=source, jev=jev or FakeJev(rules=RULES))
    uses = [make_video(id=f"n{i}", author_handle=f"c{i}", caption="app tip", sound_info=sound("777")) for i in range(3)]
    passed(ctx, *uses, make_video(id="x", caption="app", sound_info=sound("A")))
    return ctx


async def test_sounds_labels_samples_and_links_popular_and_niche_sounds():
    samples = {"A": [[make_video(id="sa1", author_handle="q1", caption="app review", sound_info=sound("A")),
                      make_video(id="sa2", author_handle="q2", caption="dance", sound_info=sound("A"))]],
               "B": [[make_video(id="sb1", author_handle="q3", caption="dance", sound_info=sound("B"))]]}
    source = FakeUgcSource(songs=[song("A", 1, commercial=True), song("B", 2, commercial=False)], song_pages=samples)
    ctx = niche_world(source)
    await run_judge(ctx)
    await run_sounds(ctx)
    sounds = {s.sound_id: s for s in ctx.store.list_sounds(ctx.run_id)}
    assert list(sounds) == ["A", "B", "777"]
    assert sounds["A"].source == ["popular"] and sounds["777"].source == ["niche"]
    assert (sounds["A"].business_use, sounds["B"].business_use, sounds["777"].business_use) == (
        "approved", "organic_only", "unknown")
    assert sounds["A"].niche_share == pytest.approx(0.5) and sounds["A"].niche_creators == 2  # corpus x + sample sa1
    assert sounds["777"].niche_creators == 3 and sounds["777"].niche_share is None
    trends = ctx.store.list_facet_trends(ctx.run_id, facet="sound")
    assert [(t.trend_id, t.sound_id, t.status) for t in trends] == [("s01", "A", "kept"), ("s02", "B", "kept"),
                                                                     ("s03", "777", "kept")]
    members = ctx.store.facet_members(ctx.run_id)
    assert members["s03"] == {"n0": 1.0, "n1": 1.0, "n2": 1.0} and members["s01"] == {"x": 1.0}
    assert ctx.store.sound_samples(ctx.run_id)["A"] == {"sa1": 0.9, "sa2": 0.1}
    calls = len(source.calls)
    await run_sounds(ctx)
    assert len(source.calls) == calls  # candidates and samples are persisted; a resume fetches nothing


async def test_business_list_labels_when_songs_carry_no_flag():
    source = FakeUgcSource(songs=[song("A", 1), song("B", 2)], business_songs=[song("B", 1), song("C", 2)])
    ctx = niche_world(source)
    await run_judge(ctx)
    await run_sounds(ctx)
    labels = {s.sound_id: (s.business_use, s.business_use_source) for s in ctx.store.list_sounds(ctx.run_id)}
    assert labels["B"] == ("approved", "business-use filter") and labels["C"] == ("approved", "business-use filter")
    assert labels["A"] == ("unknown", "")


async def test_no_verified_licensing_keeps_the_run_going_with_niche_sounds():
    down = FakeUgcSource(fail_songs=TransientAPIError("scrapecreators", 503, "down"))
    ctx = niche_world(down)
    await run_judge(ctx)
    await run_sounds(ctx)
    assert [s.sound_id for s in ctx.store.list_sounds(ctx.run_id)] == ["777"]
    notes = ctx.store.notes(ctx.run_id)
    assert any("popular-songs list was unavailable" in note for note in notes)
    assert any("No sound's business use could be verified" in note for note in notes)
    ignored = niche_world(FakeUgcSource(songs=[song("A", 1)]))  # the filter returns the same list
    await run_judge(ignored)
    await run_sounds(ignored)
    assert any("business-use filter had no effect" in note for note in ignored.store.notes(ignored.run_id))


async def test_a_rejected_key_on_the_songs_list_stops_the_run():
    ctx = niche_world(FakeUgcSource(fail_songs=FatalAPIError("scrapecreators", 401, "bad key")))
    await run_judge(ctx)
    with pytest.raises(FatalAPIError):
        await run_sounds(ctx)


async def test_the_observed_outage_response_also_degrades():
    # During the contract check TikTok's source was down and ScrapeCreators answered 400 "service_unavailable" (D3).
    ctx = niche_world(FakeUgcSource(fail_songs=FatalAPIError("scrapecreators", 400, "service_unavailable")))
    await run_judge(ctx)
    await run_sounds(ctx)
    assert [s.sound_id for s in ctx.store.list_sounds(ctx.run_id)] == ["777"]
    assert any("popular-songs list was unavailable" in note for note in ctx.store.notes(ctx.run_id))

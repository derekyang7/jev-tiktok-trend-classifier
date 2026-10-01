import pytest

from jevtrends.models import Answer, Comment, Enrichment, SoundInfo, VisionRead
from jevtrends.stages.context import StageFailed
from jevtrends.ugc.models import FacetTrend, SoundCandidate
from jevtrends.ugc.prompts import Candidate, DiscoverOut, SoundNote
from jevtrends.ugc.stages.assign import run_assign
from jevtrends.ugc.stages.discover import clean_candidates, run_discover, sound_digest_line, video_digest_line
from tests.fakes import FakeJev, FakeLLM
from tests.helpers import make_video
from tests.ugc.fakes import make_ugc_ctx


def relevant(ctx, *videos) -> None:
    for video in videos:
        ctx.store.upsert_video(video)
        ctx.store.add_run_video(ctx.run_id, video.id, "keyword:apps you need")
        ctx.store.upsert_judgment(ctx.run_id, "video", video.id, "ugc_gate.relevant", 1, Answer(value=0.9))
        ctx.store.upsert_judgment(ctx.run_id, "video", video.id, "ugc_judge.relevant", 1, Answer(value=0.9))


def candidate(name: str, *examples: str, template: str = "") -> Candidate:
    return Candidate(name=name, definition=f"{name} def.", includes=[], excludes=[],
                     example_video_ids=list(examples), template=template)


def test_video_and_slideshow_digest_lines():
    video = make_video(id="a", author_handle="ann", caption="best apps #apps", duration_ms=32400,
                       editing_features=["text"], anchors=["Green Screen"],
                       sound_info=SoundInfo(id="9", title="original sound - ann", is_original=True))
    enrichment = Enrichment(video_id="a", transcript="okay so these five apps changed my whole routine this year",
                            comments=[Comment(text="what's the third app?", likes=5)],
                            vision=VisionRead(on_screen_text="5 apps you need", setup="woman talking to camera"))
    line = video_digest_line("v001", video, enrichment, promotional=False)
    assert line.startswith("[v001] @ann | video 32s | edits: text, Green Screen | promo: no")
    assert 'on-screen: "5 apps you need"' in line and 'setup: "woman talking to camera"' in line
    assert 'speech: "okay so these five apps' in line and 'sound: "original sound - ann" (original)' in line
    assert 'top comment: "what\'s the third app?"' in line
    slides = make_video(id="s", caption="", is_slideshow=True, slide_urls=["u1", "u2", "u3"])
    slide_line = video_digest_line("v002", slides, None, promotional=True)
    assert "| slideshow 3 |" in slide_line and "speech:" not in slide_line and "promo: yes" in slide_line
    sound = SoundCandidate(sound_id="7", title="Song", author="Artist", popular_rank=4, business_use="approved")
    assert sound_digest_line("s01", sound, ["app review", "my setup"], sampled=30, niche_uses=5) == (
        '[s01] "Song" by Artist | popular #4 | business use: approved | niche uses: 5 of 30 sampled | '
        'captions: "app review" / "my setup"')


def test_clean_candidates_numbers_per_facet_caps_and_drops_hooks_without_templates():
    out = DiscoverOut(formats=[candidate("Green screen", "v001", "v999"), candidate("Screen tour"),
                               candidate("Third")],
                      hooks=[candidate("No template"), candidate("POV", template="POV: you finally found ___")],
                      topics=[], needs=[candidate("Too many subscriptions", "v002")], sound_notes=[])
    trends = clean_candidates(out, {"v001": "a", "v002": "b"}, high=2)
    assert [(t.trend_id, t.facet, t.name) for t in trends] == [
        ("f01", "format", "Green screen"), ("f02", "format", "Screen tour"), ("h01", "hook", "POV"),
        ("n01", "need", "Too many subscriptions")]
    assert trends[0].example_video_ids == ["a"] and trends[2].template == "POV: you finally found ___"


def discover_world(llm_out: DiscoverOut):
    llm = FakeLLM(lambda system, user, schema: llm_out)
    ctx = make_ugc_ctx(llm=llm)
    relevant(ctx, *[make_video(id=f"r{i}", author_handle=f"c{i}", caption=f"app tip {i}", views=100 * (i + 1))
                    for i in range(6)])
    ctx.store.upsert_sound(ctx.run_id, SoundCandidate(sound_id="7", title="Song", source=["popular"]))
    ctx.store.upsert_facet_trend(ctx.run_id, FacetTrend(trend_id="s01", facet="sound", name="Song", sound_id="7",
                                                        status="kept"))
    return ctx, llm


async def test_discover_stores_candidates_and_sound_notes_once():
    out = DiscoverOut(formats=[candidate("Green screen", "v001", "v002")], hooks=[], topics=[], needs=[],
                      sound_notes=[SoundNote(sound_id="s01", usage="Used for before-and-after reveals")])
    ctx, llm = discover_world(out)
    await run_discover(ctx)
    system, user, _ = llm.calls[0]
    assert "Propose up to 1 formats" in system
    assert user.count("\n[v0") == 6 and "[s01]" in user
    assert ctx.store.short_ids(ctx.run_id)["v001"] == "r5"  # most views first
    trends = {t.trend_id: t for t in ctx.store.list_facet_trends(ctx.run_id)}
    assert trends["f01"].example_video_ids == ["r5", "r4"]
    assert trends["s01"].usage == "Used for before-and-after reveals"
    await run_discover(ctx)
    assert len(llm.calls) == 1


async def test_discover_fails_the_stage_after_invalid_output_and_skips_without_relevant_videos():
    ctx, _ = discover_world(DiscoverOut(formats=[], hooks=[], topics=[], needs=[], sound_notes=[]))
    with pytest.raises(StageFailed):
        await run_discover(ctx)
    empty = make_ugc_ctx(llm=FakeLLM(lambda *args: pytest.fail("LLM must not be called")))
    await run_discover(empty)
    assert "No relevant videos, so no formats, hooks, topics or needs were proposed." in empty.store.notes(empty.run_id)


async def test_assign_tags_every_facet_prunes_and_warns_on_formats():
    rules = {"format": lambda s, k: "f01" if "pov" in s["caption"] else "none_of_these",
             "hook": lambda s, k: "h01" if "pov" in s["caption"] else "none_of_these"}
    jev = FakeJev(rules=rules)
    ctx = make_ugc_ctx(jev=jev)
    relevant(ctx, *[make_video(id=f"p{i}", author_handle=f"c{i}", caption=f"pov {i}") for i in range(4)],
             *[make_video(id=f"o{i}", author_handle=f"d{i}", caption=f"other {i}") for i in range(3)])
    for trend in (FacetTrend(trend_id="f01", facet="format", name="POV skit", example_video_ids=["p0", "o0"]),
                  FacetTrend(trend_id="f02", facet="format", name="Rare"),
                  FacetTrend(trend_id="h01", facet="hook", name="POV hook", template="POV: ___")):
        ctx.store.upsert_facet_trend(ctx.run_id, trend)
    await run_assign(ctx)
    state, questions = jev.calls[0]
    assert set(questions) == {"format", "hook"} and "on_screen_text" in state
    trends = {t.trend_id: t for t in ctx.store.list_facet_trends(ctx.run_id)}
    assert (trends["f01"].status, trends["h01"].status, trends["f02"].status) == ("kept", "kept", "pruned")
    assert trends["f01"].self_check_agreement == pytest.approx(0.5)
    members = ctx.store.facet_members(ctx.run_id)
    assert members["f01"]["p0"] == pytest.approx(0.9) and set(members) == {"f01", "f02", "h01"}
    assert any("fit none of the proposed formats" in note for note in ctx.store.notes(ctx.run_id))  # 3 of 7
    await run_assign(ctx)
    assert len(jev.calls) == 7

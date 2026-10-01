from datetime import UTC, datetime
from pathlib import Path

import pytest

from jevtrends.http import FatalAPIError
from jevtrends.llm.prompts import EvidenceRef
from jevtrends.models import SoundInfo
from jevtrends.pipeline import BudgetExceeded
from jevtrends.sources.base import Song
from jevtrends.ugc.config import load_niche, load_ugc_settings
from jevtrends.ugc.pipeline import estimate_ugc, run_ugc_pipeline
from jevtrends.ugc.prompts import Beat, Candidate, DiscoverOut, SoundNote, SoundPick, UgcBriefOut
from jevtrends.ugc.store import UgcStore
from tests.fakes import FakeJev, FakeLLM
from tests.helpers import make_video
from tests.ugc.fakes import FakeImages, FakeUgcSource, FakeVision, make_ugc_ctx, sequential, tiny_png

CONFIG = Path(__file__).resolve().parents[2] / "config" / "ugc"
RECENT, OLD = datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
RULES = {
    "relevant": lambda s, k: 0.1 if "cat" in s["caption"] or "dance" in s["caption"] else 0.9,
    "is_promotional": lambda s, k: 0.1,
    "format": lambda s, k: "f01" if "pov" in s["caption"] else ("f02" if "apps you need" in s["caption"]
                                                                  else "none_of_these"),
    "hook": lambda s, k: "h01" if "pov" in s["caption"] else "none_of_these",
    "fit": lambda s, k: 2.5, "ease": lambda s, k: 3.0, "brand_risk": lambda s, k: 0.1,
}


def world() -> tuple[FakeUgcSource, FakeImages]:
    """12 POV videos (4 share a sound), 8 slideshows, 4 off-niche videos, and two popular songs."""
    pov = [make_video(id=f"p{i}", author_handle=f"pov{i % 6}", caption=f"pov you found the app #{i}",
                      posted_at=RECENT if i % 2 else OLD, views=5_000 + i, author_followers=1_000, saves=50,
                      shares=10, cover_url=f"https://cdn/p{i}",
                      sound_info=SoundInfo(id="snd-pov", title="original sound - pov") if i < 4 else None)
           for i in range(12)]
    slides = [make_video(id=f"s{i}", author_handle=f"list{i % 4}", caption=f"5 apps you need {i}", is_slideshow=True,
                         slide_urls=[f"https://cdn/s{i}a", f"https://cdn/s{i}b"], views=3_000, author_followers=2_000)
              for i in range(8)]
    cats = [make_video(id=f"c{i}", author_handle=f"cat{i}", caption=f"my cat {i}") for i in range(4)]
    samples = {"A": [[make_video(id=f"a{i}", author_handle=f"aa{i}", caption="app review with song a",
                                 sound_info=SoundInfo(id="A", title="Song A")) for i in range(3)]],
               "B": [[make_video(id="b0", author_handle="bb", caption="dance challenge",
                                 sound_info=SoundInfo(id="B", title="Song B"))]]}
    source = FakeUgcSource(
        pages={"apps you need": [pov]}, hashtag_pages={"appsyouneed": [slides[:4] + cats]},
        top_pages={"apps you need": [slides[4:] + pov[:2]]},
        transcripts={v.id: f"okay so {v.caption}" for v in pov},
        songs=[Song("A", "Song A", "Artist", 1, "https://www.tiktok.com/music/song-a-A", True,
                    [0.2, 0.2, 0.2, 0.4, 0.5, 0.6]),
               Song("B", "Song B", "Artist", 2, "", False, [])],
        song_pages=samples)
    urls = [*(v.cover_url for v in pov), *(url for v in slides for url in v.slide_urls)]
    return source, FakeImages({url: tiny_png((n, 0, 0)) for n, url in enumerate(urls)})


def candidate(name: str, *examples: str, template: str = "") -> Candidate:
    return Candidate(name=name, definition=f"{name}.", includes=[], excludes=[], example_video_ids=list(examples),
                     template=template)


def responder(system: str, user: str, schema: type):
    if schema is DiscoverOut:
        return DiscoverOut(formats=[candidate("POV app discovery", "v001", "v002"),
                                    candidate("Apps-you-need slideshow", "v013")],
                           hooks=[candidate("POV hook", "v001", template="POV: you finally found an app that ___")],
                           topics=[], needs=[], sound_notes=[SoundNote(sound_id="s01", usage="App reviews")])
    return UgcBriefOut(title="Brief", why_its_working="w", concept="c", hooks=["h"],
                       beats=[Beat(time="0-3s", action="a", on_screen_text="")],
                       sound=SoundPick(sound_id="original_audio", why="voice"), pairs_with=[],
                       dos=["Disclose the partnership with #ad"], donts=["d"], cta="cta", claims_used=[],
                       evidence=[EvidenceRef(video_id="e01", why="y")], risks=["r"])


def run_ctx(store=None, run_id=None, jev=None, vision=None, settings=None):
    source, images = world()
    ctx = make_ugc_ctx(source=source, jev=jev or FakeJev(rules=RULES), llm=FakeLLM(responder),
                       vision=vision or FakeVision(), images=images, settings=settings or sequential(max_videos=60),
                       store=store, run_id=run_id)
    return ctx, source


async def test_full_ugc_pipeline_offline(tmp_path):
    ctx, _ = run_ctx()
    text = (await run_ugc_pipeline(ctx, tmp_path)).read_text()
    assert ctx.store.get_run(ctx.run_id)["status"] == "completed"
    assert all(ctx.store.stage_done(ctx.run_id, s) for s in ("collect", "look", "sounds", "brief", "report"))
    assert "24 collected (keyword 12, hashtag 8, top 4) → 20 passed gate → 20 relevant → 20 images read" in text
    assert "## Formats and hooks" in text and "POV app discovery" in text and "## Sounds" in text
    assert len(ctx.llm.calls) == 5  # discover + briefs for f01, f02, h01 and s01 (s02 organic only, s03 unverified)
    assert len(ctx.vision.calls) == 20
    assert ctx.store.total_spend(ctx.run_id) < 5.0


async def test_resume_after_a_fatal_error_in_look_repeats_nothing(tmp_path):
    store = UgcStore(":memory:")
    _, images = world()
    first, _ = run_ctx(store=store, vision=FakeVision(fatal_on={images.images["https://cdn/p5"]}))
    with pytest.raises(FatalAPIError):
        await run_ugc_pipeline(first, tmp_path)
    assert store.get_run(first.run_id)["status"] == "failed_resumable"
    assert any("Attempt stopped at look" in note for note in store.notes(first.run_id))
    read_before = sum(1 for v in store.run_video_ids(first.run_id)
                      if (e := store.get_enrichment(v)) is not None and e.vision is not None)
    vision = FakeVision()
    second, source = run_ctx(store=store, run_id=first.run_id, vision=vision)
    store.set_run_status(first.run_id, "running")
    await run_ugc_pipeline(second, tmp_path)
    assert store.get_run(first.run_id)["status"] == "completed"
    assert [c for c in source.calls if c[0] in ("search", "hashtag", "top", "transcript")] == []
    assert len(vision.calls) == 20 - read_before


async def test_resume_after_a_fatal_error_in_assign_matches_a_clean_run(tmp_path):
    clean, _ = run_ctx()
    await run_ugc_pipeline(clean, tmp_path / "clean")
    expected = [(s.trend_id, round(s.score, 6)) for s in clean.store.list_ugc_scores(clean.run_id)]

    store = UgcStore(":memory:")
    boom = lambda s, q: (FatalAPIError("jev", 401, "bad key")  # noqa: E731
                         if "format" in q and s["caption"] == "5 apps you need 2" else None)
    first, _ = run_ctx(store=store, jev=FakeJev(rules=RULES, fail_when=boom))
    with pytest.raises(FatalAPIError):
        await run_ugc_pipeline(first, tmp_path / "first")
    assert store.stage_done(first.run_id, "discover") and not store.stage_done(first.run_id, "assign")
    answered = len(store.get_answers(first.run_id, "video", "ugc_assign.format", 1))
    jev = FakeJev(rules=RULES)
    second, _ = run_ctx(store=store, run_id=first.run_id, jev=jev)
    store.set_run_status(first.run_id, "running")
    await run_ugc_pipeline(second, tmp_path / "second")
    assert len([q for _, q in jev.calls if "format" in q]) == 20 - answered
    assert not any("relevant" in q for _, q in jev.calls)  # gate, judge and sound checks are not repeated
    assert [(s.trend_id, round(s.score, 6)) for s in store.list_ugc_scores(first.run_id)] == expected


async def test_budget_guard_stops_before_spending(tmp_path):
    settings = sequential(max_videos=60)
    settings.budget = settings.budget.model_copy(update={"max_usd_per_scan": 0.01})
    ctx, source = run_ctx(settings=settings)
    with pytest.raises(BudgetExceeded):
        await run_ugc_pipeline(ctx, tmp_path)
    assert ctx.store.get_run(ctx.run_id)["status"] == "budget_exceeded" and source.calls == []


async def test_no_vision_runs_the_text_only_pipeline(tmp_path):
    settings = sequential(max_videos=60)
    settings.vision = settings.vision.model_copy(update={"enabled": False})
    vision = FakeVision()
    ctx, _ = run_ctx(settings=settings, vision=vision)
    text = (await run_ugc_pipeline(ctx, tmp_path)).read_text()
    assert vision.calls == [] and "→ 0 images read →" in text


def test_estimate_for_the_first_niche_fits_the_cap():
    projection, decision = estimate_ugc(load_ugc_settings(CONFIG / "settings.yaml"), load_niche(CONFIG, "consumer_apps"))
    assert 4.5 < projection.total < 4.95 and decision.ok and decision.trims == []

import pytest

from jevtrends.ugc.models import SoundCandidate
from jevtrends.ugc.stages.brief import DISCLOSURE_LINE, run_brief
from jevtrends.ugc.stages.report import build_ugc_report_data, render_ugc_report, sound_url, write_ugc_report
from tests.fakes import FakeLLM
from tests.ugc.fakes import make_ugc_ctx
from tests.ugc.test_stage_brief import brief_out, ranked_world


async def briefed_ctx():
    ctx = ranked_world(FakeLLM(lambda system, user, schema: brief_out()))
    await run_brief(ctx)
    return ctx


def test_sound_url_prefers_the_listed_link():
    assert sound_url(SoundCandidate(sound_id="7", title="x", link="https://www.tiktok.com/music/x-7")).endswith("x-7")
    assert sound_url(SoundCandidate(sound_id="9", title="Stargazing (Slowed)")) == (
        "https://www.tiktok.com/music/stargazing-slowed-9")


async def test_report_has_header_top_picks_sections_sounds_and_diagnostics():
    ctx = await briefed_ctx()
    text = render_ugc_report(ctx.store, ctx.run_id)
    assert text.startswith(f"# TikTok trends for UGC and ads #{ctx.run_id}: Consumer apps, 2026-10-01")
    assert "Product: generic (no product profile)" in text
    assert ("8 collected (keyword 8) → 8 passed gate → 8 relevant → 0 images read → formats 1/2, hooks 1/1, "
            "topics 0/0, needs 0/0 kept → 1 sound candidates") in text
    assert "| 1 | Format | Green screen |" in text
    assert "## Formats and hooks" in text and "### 1. Green-screen app reveal" in text
    assert "*Format:* Green screen" in text and "*Template:* \"POV: ___\"" in text
    assert "[@a0](https://www.tiktok.com/@a0/video/m0)" in text and DISCLOSURE_LINE in text
    assert "| 1 | [Song](https://www.tiktok.com/music/song-777) | approved |" in text
    assert "## Topics and memes\n\nNo trends of this kind in this run." in text
    assert "## Diagnostics" in text and "Settings used" in text and "Sound licensing: approved 1" in text


async def test_weights_override_reranks_without_model_calls():
    ctx = await briefed_ctx()
    calls = (len(ctx.jev.calls), len(ctx.llm.calls))
    weights = {"momentum": 0.0, "performance": 0.0, "fit": 0.0, "breadth": 0.0, "ease": 1.0}
    data = build_ugc_report_data(ctx.store, ctx.run_id, weights=weights)
    assert data["top_picks"][0]["score"].score == pytest.approx(0.67)
    assert (len(ctx.jev.calls), len(ctx.llm.calls)) == calls


def test_an_empty_run_still_renders_a_valid_report():
    ctx = make_ugc_ctx()
    ctx.store.add_note(ctx.run_id, "No relevant videos, so no formats, hooks, topics or needs were proposed.")
    text = render_ugc_report(ctx.store, ctx.run_id)
    assert "0 collected → 0 passed gate → 0 relevant → 0 images read" in text
    assert "No trends were kept in this run." in text and "No sounds in this run." in text
    assert "- No relevant videos, so no formats, hooks, topics or needs were proposed." in text
    assert '"None of these" rates: n/a' in text


async def test_write_names_the_file_by_date_niche_and_run(tmp_path):
    ctx = await briefed_ctx()
    path = write_ugc_report(ctx.store, ctx.run_id, tmp_path)
    assert path == tmp_path / f"2026-10-01-consumer_apps-run-{ctx.run_id}.md"

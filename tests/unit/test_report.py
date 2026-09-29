from jevtrends.stages.brief import run_brief
from jevtrends.stages.report import build_report_data, render_report, write_report
from tests.fakes import FakeLLM, make_ctx
from tests.unit.test_stages_score_brief import brief_out, scored_ctx


async def briefed_ctx():
    ctx = await scored_ctx(llm=FakeLLM(lambda system, user, schema: brief_out("e01", "e02")))
    await run_brief(ctx)
    return ctx


async def test_report_contains_header_table_sections_and_evidence():
    ctx = await briefed_ctx()
    text = render_report(ctx.store, ctx.run_id)
    assert text.startswith(f"# TikTok opportunity scan #{ctx.run_id}: 2026-09-28")
    assert "6 collected → 6 passed filter → 5 signals → 2 trends proposed → 1 kept" in text
    assert "\n\n## Top opportunities" in text  # blank line before the heading even without notes
    assert "| 1 | Rent splitting | Fintech & payments | behavior_need |" in text
    assert "## Fintech & payments" in text
    assert "## AI\n\nNo trends in this niche this scan." in text
    assert "**Renters want painless bill splitting**" in text
    assert "[@c1](https://www.tiktok.com/@c1/video/a)" in text
    assert "## Outside your niches" in text
    assert "## Diagnostics" in text and "Settings used" in text


async def test_weights_override_reranks_without_model_calls():
    ctx = await briefed_ctx()
    calls = (len(ctx.jev.calls), len(ctx.llm.calls))
    data = build_report_data(ctx.store, ctx.run_id,
                             weights={"momentum": 0.0, "pain": 1.0, "spend": 0.0, "underserved": 0.0, "breadth": 0.0})
    assert data["entries"][0]["score"].opportunity == 1.0
    assert (len(ctx.jev.calls), len(ctx.llm.calls)) == calls


async def test_report_for_empty_scan_is_valid():
    ctx = make_ctx()
    ctx.store.add_note(ctx.run_id, "No signal videos, so no trends were proposed.")
    text = render_report(ctx.store, ctx.run_id)
    assert "0 collected → 0 passed filter → 0 signals → 0 trends proposed → 0 kept" in text
    assert "No trends were kept in this scan." in text
    assert "- No signal videos, so no trends were proposed." in text
    assert '"None of these" rate: n/a' in text


async def test_write_report_names_file_by_date_and_run(tmp_path):
    ctx = await briefed_ctx()
    path = write_report(ctx.store, ctx.run_id, tmp_path)
    assert path == tmp_path / f"2026-09-28-scan-{ctx.run_id}.md"
    assert path.read_text().startswith(f"# TikTok opportunity scan #{ctx.run_id}")

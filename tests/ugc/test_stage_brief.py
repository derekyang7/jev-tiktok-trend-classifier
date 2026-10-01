import json

from jevtrends.llm.prompts import EvidenceRef
from jevtrends.ugc.models import SoundCandidate, UgcTrendScore
from jevtrends.ugc.prompts import Beat, SoundPick, UgcBriefOut
from jevtrends.ugc.stages.brief import DISCLOSURE_LINE, ensure_disclosure, run_brief, selected_briefs
from tests.fakes import FakeLLM
from tests.ugc.test_stage_score import scored_world


def brief_out(**overrides) -> UgcBriefOut:
    fields = dict(title="Green-screen app reveal", why_its_working="w", concept="c", hooks=["POV: you found it"],
                  beats=[Beat(time="0-3s", action="hook", on_screen_text="POV")],
                  sound=SoundPick(sound_id="original_audio", why="voice carries it"), pairs_with=[],
                  dos=["Show the app on screen"], donts=["Don't read a script"], cta="Download it", claims_used=[],
                  evidence=[EvidenceRef(video_id="e01", why="shows it")], risks=["crowded"])
    fields.update(overrides)
    return UgcBriefOut(**fields)


def ranked_world(llm, sound_use: str = "approved", sound_risky: bool = False, with_product: bool = False):
    ctx, _ = scored_world(with_product=with_product)
    ctx.llm = llm
    ctx.store.upsert_sound(ctx.run_id, SoundCandidate(sound_id="777", title="Song", source=["popular"],
                                                      business_use=sound_use))
    rows = [("f01", "format", 0.9, False), ("h01", "hook", 0.8, False), ("s01", "sound", 0.7, sound_risky)]
    ctx.store.replace_ugc_scores(ctx.run_id, [
        UgcTrendScore(trend_id=tid, facet=facet, support=3.8, creators=4, momentum_ratio=1.2, momentum_norm=0.6,
                      reach_ratio=1.5, eng_ratio=1.4, performance_norm=0.6, breadth_norm=0.5, fit_norm=1.0,
                      ease_norm=0.67, fit_value=3.0, ease_value=2.0, fit_confidence=0.8, ease_confidence=0.8,
                      risky=risky, score=value, rank_overall=rank, rank_in_facet=1)
        for rank, (tid, facet, value, risky) in enumerate(rows, start=1)])
    ctx.store.replace_pairs(ctx.run_id, [("f01", "h01", 3.25, 1.8)])
    return ctx


def dossier_of(user: str) -> dict:
    return json.loads(user.split("<trend_data>\n", 1)[1].split("\n</trend_data>", 1)[0])


def test_ensure_disclosure_appends_only_when_missing():
    assert ensure_disclosure(["Use #ad in the caption"]) == ["Use #ad in the caption"]
    assert ensure_disclosure(["Show the app"]) == ["Show the app", DISCLOSURE_LINE]


def test_selection_respects_quotas_eligibility_and_budget_cuts():
    assert selected_briefs(ranked_world(FakeLLM(lambda *a: None))) == ["f01", "h01", "s01"]
    assert selected_briefs(ranked_world(FakeLLM(lambda *a: None), sound_use="unknown")) == ["f01", "h01"]
    assert selected_briefs(ranked_world(FakeLLM(lambda *a: None), sound_risky=True)) == ["f01", "h01"]
    trimmed = ranked_world(FakeLLM(lambda *a: None))
    trimmed.limits["max_briefs"] = 2
    assert selected_briefs(trimmed) == ["f01", "h01"]


async def test_briefs_get_mapped_evidence_known_pairs_and_the_disclosure_line():
    llm = FakeLLM(lambda system, user, schema: brief_out(
        evidence=[EvidenceRef(video_id="e01", why="shows it"), EvidenceRef(video_id="e99", why="made up")],
        pairs_with=["h01", "zz"], sound=SoundPick(sound_id="s01", why="it fits")))
    ctx = ranked_world(llm)
    await run_brief(ctx)
    briefs = ctx.store.list_ugc_briefs(ctx.run_id)
    assert {tid: row["status"] for tid, row in briefs.items()} == {"f01": "ok", "h01": "ok", "s01": "ok"}
    brief = briefs["f01"]["brief"]
    assert brief["evidence"] == [{"video_id": "m0", "why": "shows it"}]
    assert brief["pairs_with"] == ["h01"] and brief["dos"][-1] == DISCLOSURE_LINE
    dossier = dossier_of(next(user for _, user, _ in llm.calls if '"id": "f01"' in user))
    assert dossier["approved_sounds"] == [{"id": "s01", "title": "Song", "usage": ""}]
    assert [p["id"] for p in dossier["pairs"]] == ["h01"] and "product" not in dossier
    assert dossier["evidence"][0]["video_id"] == "e01" and dossier["evidence"][0]["promotional"] is True
    await run_brief(ctx)
    assert len(llm.calls) == 3


async def test_invented_claims_are_rejected_and_leave_the_trend_without_a_brief():
    invented = ranked_world(FakeLLM(lambda *a: brief_out(claims_used=["c9"])), with_product=True)
    await run_brief(invented)
    assert {row["status"] for row in invented.store.list_ugc_briefs(invented.run_id).values()} == {"failed"}
    no_product = ranked_world(FakeLLM(lambda *a: brief_out(claims_used=["c1"])))
    await run_brief(no_product)
    assert {row["status"] for row in no_product.store.list_ugc_briefs(no_product.run_id).values()} == {"failed"}
    allowed = ranked_world(FakeLLM(lambda *a: brief_out(claims_used=["c1"])), with_product=True)
    await run_brief(allowed)
    briefs = allowed.store.list_ugc_briefs(allowed.run_id)
    assert briefs["f01"]["brief"]["claims_used"] == ["c1"]
    assert dossier_of(allowed.llm.calls[0][1])["product"]["claims_allowed"] == [{"id": "c1", "text": "Free to download"}]


async def test_without_approved_sounds_briefs_must_use_original_audio():
    picked = ranked_world(FakeLLM(lambda *a: brief_out(sound=SoundPick(sound_id="s01", why="x"))), sound_use="unknown")
    await run_brief(picked)
    assert {row["status"] for row in picked.store.list_ugc_briefs(picked.run_id).values()} == {"failed"}
    assert dossier_of(picked.llm.calls[0][1])["approved_sounds"] == []
    original = ranked_world(FakeLLM(lambda *a: brief_out()), sound_use="unknown")
    await run_brief(original)
    assert {row["status"] for row in original.store.list_ugc_briefs(original.run_id).values()} == {"ok"}

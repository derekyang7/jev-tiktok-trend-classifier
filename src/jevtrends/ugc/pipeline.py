"""Runs the UGC stages in order with budget checks, resume support and run status (UGC spec §5.1, §12)."""

from pathlib import Path

from jevtrends.pipeline import BudgetExceeded, run_stages
from jevtrends.ugc.budget import (GATE_PASS_RATE, SLIDESHOW_RATE, UGC_STAGE_ORDER, UgcDecision, UgcProjection,
                                  decide_ugc, project_ugc, ugc_remaining_work)
from jevtrends.ugc.config import NicheProfile, UgcSettings
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.stages.assign import run_assign
from jevtrends.ugc.stages.brief import run_brief
from jevtrends.ugc.stages.collect import run_collect
from jevtrends.ugc.stages.discover import run_discover
from jevtrends.ugc.stages.enrich import run_enrich
from jevtrends.ugc.stages.gate import gate_survivors, run_gate
from jevtrends.ugc.stages.judge import relevant_videos, run_judge
from jevtrends.ugc.stages.look import run_look
from jevtrends.ugc.stages.report import write_ugc_report
from jevtrends.ugc.stages.score import run_score
from jevtrends.ugc.stages.sounds import run_sounds

UGC_STAGES = [("collect", run_collect), ("gate", run_gate), ("enrich", run_enrich), ("look", run_look),
              ("judge", run_judge), ("sounds", run_sounds), ("discover", run_discover), ("assign", run_assign),
              ("score", run_score), ("brief", run_brief)]


def known_counts(ctx: UgcRunContext) -> dict[str, int]:
    store, run_id = ctx.store, ctx.run_id
    counts = {"searches": len(ctx.niche.searches(ctx.settings.scan.top_search))}
    if store.stage_done(run_id, "collect"):
        counts["collected"] = len(store.run_video_ids(run_id))
    if store.stage_done(run_id, "gate"):
        survivors = gate_survivors(ctx)
        counts["gate_passed"] = len(survivors)
        counts["slideshows"] = sum(1 for video in store.get_videos(survivors).values() if video.is_slideshow)
    if store.stage_done(run_id, "judge"):
        counts["relevant"] = len(relevant_videos(ctx))
    if store.stage_done(run_id, "sounds"):
        counts["sounds"] = len(store.list_sounds(run_id))
    if store.stage_done(run_id, "assign"):
        counts["kept"] = sum(1 for t in store.list_facet_trends(run_id, status="kept") if t.facet != "sound")
    return counts


def check_budget(ctx: UgcRunContext, stage: str) -> None:
    settings = ctx.settings
    counts = known_counts(ctx)
    slides = ctx.limits.get("slides_per_post", settings.vision.slides_per_post)
    work = ugc_remaining_work(stage, counts, settings,
                              comment_videos=ctx.limits.get("comments_top_videos", settings.enrich.comments_top_videos),
                              slides_per_post=slides,
                              max_briefs=ctx.limits.get("max_briefs", settings.briefs.max_briefs))
    gate_passed = counts.get("gate_passed", round(counts.get("collected", settings.scan.max_videos) * GATE_PASS_RATE))
    slideshows = counts.get("slideshows", round(gate_passed * SLIDESHOW_RATE))
    spent = ctx.store.total_spend(ctx.run_id)
    decision = decide_ugc(spent, work, settings, slideshows, slides)
    position = UGC_STAGE_ORDER.index(stage)
    if position <= UGC_STAGE_ORDER.index("enrich"):
        ctx.limits["comments_top_videos"] = decision.comment_requests
    if position <= UGC_STAGE_ORDER.index("look"):
        ctx.limits["slides_per_post"] = decision.slides_per_post
    ctx.limits["max_briefs"] = decision.brief_count
    for trim in decision.trims:
        ctx.store.add_note(ctx.run_id, f"Budget cut before {stage}: {trim}")
    if not decision.ok:
        raise BudgetExceeded(f"about ${decision.projected:.2f} more would exceed the "
                             f"${settings.budget.max_usd_per_scan:.2f} cap (already spent ${spent:.2f})")


async def run_ugc_pipeline(ctx: UgcRunContext, reports_dir: Path) -> Path:
    await run_stages(ctx, UGC_STAGES, check_budget)
    path = write_ugc_report(ctx.store, ctx.run_id, reports_dir)
    ctx.store.mark_stage_done(ctx.run_id, "report")
    return path


def estimate_ugc(settings: UgcSettings, niche: NicheProfile) -> tuple[UgcProjection, UgcDecision]:
    """The whole run's projection before anything is spent, and the cuts the budget guard would make."""
    work = ugc_remaining_work("collect", {"searches": len(niche.searches(settings.scan.top_search))}, settings,
                              settings.enrich.comments_top_videos, settings.vision.slides_per_post,
                              settings.briefs.max_briefs)
    slideshows = round(round(settings.scan.max_videos * GATE_PASS_RATE) * SLIDESHOW_RATE)
    return project_ugc(work, settings), decide_ugc(0.0, work, settings, slideshows, settings.vision.slides_per_post)

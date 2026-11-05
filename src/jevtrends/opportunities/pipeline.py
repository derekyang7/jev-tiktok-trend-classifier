"""Runs the startup opportunities stages in order with budget checks, resume support and run status updates (spec §5.1, §12)."""

from pathlib import Path

from jevtrends.core.budget import BudgetGuard
from jevtrends.core.context import BudgetExceeded, run_stages
from jevtrends.opportunities.budget import (STAGE_ORDER, Decision, Projection, decide_opportunities,
                                            project_opportunities, remaining_work)
from jevtrends.opportunities.config import NicheConfig, Settings
from jevtrends.opportunities.context import RunContext
from jevtrends.opportunities.stages.assign import run_assign
from jevtrends.opportunities.stages.brief import run_brief
from jevtrends.opportunities.stages.collect import run_collect
from jevtrends.opportunities.stages.discover import run_discover
from jevtrends.opportunities.stages.enrich import run_enrich
from jevtrends.opportunities.stages.gate import gate_survivors, run_gate
from jevtrends.opportunities.stages.judge import run_judge, signal_videos
from jevtrends.opportunities.stages.report import write_report
from jevtrends.opportunities.stages.score import run_score

STAGES = {"collect": run_collect, "gate": run_gate, "enrich": run_enrich, "judge": run_judge,
          "discover": run_discover, "assign": run_assign, "score": run_score, "brief": run_brief}


def known_counts(ctx: RunContext) -> dict[str, int]:
    store, run_id = ctx.store, ctx.run_id
    counts = {"queries": len(ctx.niches.all_queries())}
    if store.stage_done(run_id, "collect"):
        counts["collected"] = len(store.run_video_ids(run_id))
    if store.stage_done(run_id, "gate"):
        counts["gate_passed"] = len(gate_survivors(ctx))
    if store.stage_done(run_id, "judge"):
        counts["signals"] = len(signal_videos(ctx))
    if store.stage_done(run_id, "assign"):
        counts["kept"] = len(store.list_trends(run_id, status="kept"))
    return counts


def check_budget(ctx: RunContext, stage: str) -> None:
    settings = ctx.settings
    work = remaining_work(stage, known_counts(ctx), settings,
                          comment_videos=ctx.limits.get("comments_top_videos", settings.enrich.comments_top_videos),
                          max_briefs=ctx.limits.get("max_briefs", settings.briefs.max_briefs))
    spent = ctx.store.total_spend(ctx.run_id)
    decision = decide_opportunities(ctx.budget, spent, work, settings.briefs.min_briefs)
    if STAGE_ORDER.index(stage) <= STAGE_ORDER.index("enrich"):
        ctx.limits["comments_top_videos"] = decision.comment_requests
    ctx.limits["max_briefs"] = decision.brief_count
    for trim in decision.trims:
        ctx.store.add_note(ctx.run_id, f"Budget trim before {stage}: {trim}")
    if not decision.ok:
        raise BudgetExceeded(f"about ${decision.projected:.2f} more would exceed the ${ctx.budget.cap:.2f} cap "
                             f"(already spent ${spent:.2f})")


async def run_pipeline(ctx: RunContext, reports_dir: Path) -> Path:
    await run_stages(ctx, [(stage, STAGES[stage]) for stage in STAGE_ORDER[:-1]], check_budget)
    path = write_report(ctx.store, ctx.run_id, reports_dir)
    ctx.store.mark_stage_done(ctx.run_id, "report")
    return path


def estimate_scan(settings: Settings, niches: NicheConfig, guard: BudgetGuard) -> tuple[Projection, Decision]:
    """Full-pipeline projection before anything is spent, and what the budget guard would trim to fit."""
    work = remaining_work("collect", {"queries": len(niches.all_queries())}, settings,
                          settings.enrich.comments_top_videos, settings.briefs.max_briefs)
    return project_opportunities(guard, work), decide_opportunities(guard, 0.0, work, settings.briefs.min_briefs)

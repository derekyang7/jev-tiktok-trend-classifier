"""Runs the stages in order with budget checks, resume support and run status updates (spec §5.1, §12)."""

from pathlib import Path

from jevtrends.budget import STAGE_ORDER, BudgetGuard, Projection, remaining_work
from jevtrends.config import NicheConfig, Settings
from jevtrends.http import FatalAPIError
from jevtrends.stages.assign import run_assign
from jevtrends.stages.brief import run_brief
from jevtrends.stages.collect import run_collect
from jevtrends.stages.context import RunContext, StageFailed
from jevtrends.stages.discover import run_discover
from jevtrends.stages.enrich import run_enrich
from jevtrends.stages.gate import gate_survivors, run_gate
from jevtrends.stages.judge import run_judge, signal_videos
from jevtrends.stages.report import write_report
from jevtrends.stages.score import run_score

STAGES = {"collect": run_collect, "gate": run_gate, "enrich": run_enrich, "judge": run_judge,
          "discover": run_discover, "assign": run_assign, "score": run_score, "brief": run_brief}


class BudgetExceeded(Exception):
    """The remaining pipeline cannot fit under the budget cap, even after trimming."""


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
    decision = ctx.budget.decide(spent, work, settings.briefs.min_briefs)
    if STAGE_ORDER.index(stage) <= STAGE_ORDER.index("enrich"):
        ctx.limits["comments_top_videos"] = decision.comment_requests
    ctx.limits["max_briefs"] = decision.brief_count
    for trim in decision.trims:
        ctx.store.add_note(ctx.run_id, f"Budget trim before {stage}: {trim}")
    if not decision.ok:
        raise BudgetExceeded(f"about ${decision.projected:.2f} more would exceed the ${ctx.budget.cap:.2f} cap "
                             f"(already spent ${spent:.2f})")


async def run_pipeline(ctx: RunContext, reports_dir: Path) -> Path:
    stage = "collect"
    try:
        for stage in STAGE_ORDER[:-1]:
            if ctx.store.stage_done(ctx.run_id, stage):
                continue
            check_budget(ctx, stage)
            await STAGES[stage](ctx)
            ctx.store.mark_stage_done(ctx.run_id, stage)
    except BudgetExceeded as exc:
        ctx.store.set_run_status(ctx.run_id, "budget_exceeded")
        ctx.store.add_note(ctx.run_id, f"Attempt stopped at {stage}: {exc}")
        raise
    except (StageFailed, FatalAPIError) as exc:
        ctx.store.set_run_status(ctx.run_id, "failed_resumable")
        ctx.store.add_note(ctx.run_id, f"Attempt stopped at {stage}: {exc}")
        raise
    except BaseException as exc:  # unexpected errors and Ctrl-C must not leave the run marked "running"
        ctx.store.set_run_status(ctx.run_id, "failed_resumable")
        ctx.store.add_note(ctx.run_id, f"Attempt stopped at {stage}: {exc!r}")
        raise
    ctx.store.set_run_status(ctx.run_id, "completed", finished=True)
    path = write_report(ctx.store, ctx.run_id, reports_dir)
    ctx.store.mark_stage_done(ctx.run_id, "report")
    return path


def estimate_scan(settings: Settings, niches: NicheConfig, guard: BudgetGuard) -> Projection:
    work = remaining_work("collect", {"queries": len(niches.all_queries())}, settings,
                          settings.enrich.comments_top_videos, settings.briefs.max_briefs)
    return guard.project(work)

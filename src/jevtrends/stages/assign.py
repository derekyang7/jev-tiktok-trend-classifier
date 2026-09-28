"""Stage 6: Jev assigns each signal video to one candidate trend or none; weak trends are pruned (spec §6.6)."""

from jevtrends import scoring
from jevtrends.jev.questions import NONE_OF_THESE, Question, assign_question
from jevtrends.models import Trend
from jevtrends.stages.context import RunContext, run_items
from jevtrends.stages.judge import signal_videos, video_state


async def run_assign(ctx: RunContext) -> None:
    trends = ctx.store.list_trends(ctx.run_id)
    if not trends:
        return
    question = assign_question(trends)
    done = ctx.answers(question)
    todo = [video_id for video_id in signal_videos(ctx) if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def assign_one(video_id: str) -> None:
        state = video_state(videos[video_id], ctx.store.get_enrichment(video_id),
                            ctx.settings.enrich.transcript_max_words)
        await ctx.ask_jev("assign", "video", video_id, state, [question])

    await run_items(ctx, "assign", "jev", todo, assign_one, ctx.settings.concurrency.jev)
    finalize_assignment(ctx, trends, question)


def finalize_assignment(ctx: RunContext, trends: list[Trend], question: Question) -> None:
    cfg, thresholds = ctx.settings.trends, ctx.settings.thresholds
    probs = {video_id: answer.probabilities or {} for video_id, answer in ctx.answers(question).items()}
    ctx.store.replace_trend_members(
        ctx.run_id, [(t.trend_id, video_id, p.get(t.trend_id, 0.0)) for t in trends for video_id, p in probs.items()])
    members = ctx.store.trend_members(ctx.run_id)
    creator_of = {video_id: video.author_id for video_id, video in ctx.store.get_videos(list(probs)).items()}
    top = scoring.top_choices(probs)
    for trend in trends:
        reason = scoring.prune_reason(members.get(trend.trend_id, {}), creator_of, cfg.min_support,
                                      cfg.min_creators, thresholds.trend_member)
        ctx.store.upsert_trend(ctx.run_id, trend.model_copy(update={
            "status": "pruned" if reason else "kept",
            "prune_reason": reason,
            "self_check_agreement": scoring.self_check(trend.trend_id, trend.example_video_ids, top),
        }))
    rate = scoring.none_rate(top, NONE_OF_THESE)
    if rate > cfg.none_rate_warning:
        ctx.store.add_note(ctx.run_id, f"{rate:.0%} of signal videos fit none of the proposed trends; "
                                       "the LLM may have missed trends.")

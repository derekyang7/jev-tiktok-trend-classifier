"""Stage 8: Jev tags each relevant video on every facet with candidates; weak candidates are pruned (UGC spec §6.8)."""

from jevtrends import scoring as base
from jevtrends.jev.questions import NONE_OF_THESE, Question
from jevtrends.stages.context import run_items
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.models import LLM_FACETS, FacetTrend
from jevtrends.ugc.questions import assign_question
from jevtrends.ugc.stages.judge import relevant_videos, ugc_video_state

WARN_FACETS = ("format", "hook")  # every video has a format and a hook, so a high none rate means missed candidates


def facet_groups(ctx: UgcRunContext) -> dict[str, list[FacetTrend]]:
    groups: dict[str, list[FacetTrend]] = {}
    for trend in ctx.store.list_facet_trends(ctx.run_id):
        if trend.facet in LLM_FACETS:
            groups.setdefault(trend.facet, []).append(trend)
    return groups


def assign_questions(groups: dict[str, list[FacetTrend]]) -> list[Question]:
    return [assign_question(facet, groups[facet]) for facet in LLM_FACETS if groups.get(facet)]


async def run_assign(ctx: UgcRunContext) -> None:
    groups = facet_groups(ctx)
    questions = assign_questions(groups)
    if not questions:
        return
    done = ctx.answers(questions[0])  # every question is asked in the same request
    relevant = relevant_videos(ctx)
    todo = [video_id for video_id in relevant if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def assign_one(video_id: str) -> None:
        state = ugc_video_state(videos[video_id], ctx.store.get_enrichment(video_id),
                                ctx.settings.enrich.transcript_max_words)
        await ctx.ask_jev("assign", "video", video_id, state, questions)

    await run_items(ctx, "assign", "jev", todo, assign_one, ctx.settings.concurrency.jev, total=len(relevant))
    finalize_assignment(ctx, groups, questions)


def finalize_assignment(ctx: UgcRunContext, groups: dict[str, list[FacetTrend]], questions: list[Question]) -> None:
    cfg, thresholds = ctx.settings.trends, ctx.settings.thresholds
    rows: list[tuple[str, str, float]] = []
    trend_ids: list[str] = []
    for question in questions:
        facet = question.key
        probs = {video_id: answer.probabilities or {} for video_id, answer in ctx.answers(question).items()}
        creator_of = {video_id: video.author_id for video_id, video in ctx.store.get_videos(list(probs)).items()}
        top = base.top_choices(probs)
        for trend in groups[facet]:
            members = {video_id: p.get(trend.trend_id, 0.0) for video_id, p in probs.items()}
            rows += [(trend.trend_id, video_id, p) for video_id, p in members.items()]
            trend_ids.append(trend.trend_id)
            reason = base.prune_reason(members, creator_of, cfg.min_support, cfg.min_creators,
                                       thresholds.trend_member)
            ctx.store.upsert_facet_trend(ctx.run_id, trend.model_copy(update={
                "status": "pruned" if reason else "kept", "prune_reason": reason,
                "self_check_agreement": base.self_check(trend.trend_id, trend.example_video_ids, top)}))
        rate = base.none_rate(top, NONE_OF_THESE)
        if facet in WARN_FACETS and rate > cfg.none_rate_warning:
            ctx.store.add_note(ctx.run_id, f"{rate:.0%} of relevant videos fit none of the proposed {facet}s; the "
                                           "LLM may have missed some.")
    ctx.store.replace_members(ctx.run_id, trend_ids, rows)

"""Stage 8: LLM opportunity briefs for the selected trends (spec §6.8)."""

from jevtrends import scoring
from jevtrends.jev.questions import IS_PROMOTIONAL, TREND_QUESTIONS
from jevtrends.llm.client import LLMOutputError
from jevtrends.llm.prompts import BRIEF_SYSTEM, BriefOut, brief_user_prompt
from jevtrends.stages.context import RunContext, run_items
from jevtrends.stages.judge import truncate_words
from jevtrends.stages.score import evidence_set

BRIEF_MAX_TOKENS = 8_000


def selected_trends(ctx: RunContext) -> list[str]:
    ranked = ctx.store.list_trend_scores(ctx.run_id)
    limit = ctx.limits.get("max_briefs", ctx.settings.briefs.max_briefs)
    return scoring.select_for_briefs(ranked, ctx.niches.ids(), ctx.settings.briefs.max_briefs)[:limit]


def brief_dossier(ctx: RunContext, trend_id: str, evidence_ids: list[str]) -> dict:
    trend = next(t for t in ctx.store.list_trends(ctx.run_id) if t.trend_id == trend_id)
    score = next(s for s in ctx.store.list_trend_scores(ctx.run_id) if s.trend_id == trend_id)
    names = {niche.id: niche.name for niche in ctx.niches.niches}
    promo = ctx.answers(IS_PROMOTIONAL)
    scores = {}
    for question in TREND_QUESTIONS:
        answer = ctx.answers(question, subject_type="trend")[trend_id]
        scores[question.key] = {"value": answer.value, "confidence": answer.confidence}
    evidence = []
    for index, video_id in enumerate(evidence_ids, start=1):
        video, enrichment = ctx.store.get_video(video_id), ctx.store.get_enrichment(video_id)
        evidence.append({
            "video_id": f"e{index:02d}",
            "handle": f"@{video.author_handle}",
            "caption": video.caption,
            "transcript_excerpt": truncate_words(enrichment.transcript if enrichment else None, 200),
            "top_comments": [c.text for c in ((enrichment.comments if enrichment else None) or [])[:3]],
            "views": video.views,
            "posted": video.posted_at.date().isoformat(),
            "promotional": video_id in promo and float(promo[video_id].value) >= 0.5,
        })
    return {
        "trend": {"name": trend.name, "kind": trend.kind, "definition": trend.definition},
        "stats": {"support": round(score.support, 1), "creators": score.creators,
                  "momentum_ratio": round(score.momentum_ratio, 2), "median_views": int(score.median_views),
                  "promotional_share": round(score.promo_share, 2), "niches": [names[n] for n in score.niches]},
        "scores": scores,
        "evidence": evidence,
    }


async def run_brief(ctx: RunContext) -> None:
    existing = ctx.store.list_briefs(ctx.run_id)
    todo = [trend_id for trend_id in selected_trends(ctx) if trend_id not in existing]
    members = ctx.store.trend_members(ctx.run_id)

    async def brief_one(trend_id: str) -> None:
        evidence_ids = evidence_set(members.get(trend_id, {}), ctx.settings.trends.evidence_per_trend)
        short_to_video = {f"e{i:02d}": video_id for i, video_id in enumerate(evidence_ids, start=1)}

        def validate(out: BriefOut) -> list[str]:
            if any(ref.video_id in short_to_video for ref in out.evidence):
                return []
            return ["evidence must cite video_id values copied exactly from the evidence list (e01, e02, ...)"]

        try:
            result = await ctx.llm.complete_json(BRIEF_SYSTEM, brief_user_prompt(brief_dossier(ctx, trend_id, evidence_ids)),
                                                 BriefOut, max_tokens=BRIEF_MAX_TOKENS, validate=validate)
        except LLMOutputError as exc:
            ctx.record_llm("brief", exc.input_tokens, exc.output_tokens, exc.cost_usd)
            ctx.store.upsert_brief(ctx.run_id, trend_id, ctx.llm.model, None, "failed")
            return
        ctx.record_llm("brief", result.input_tokens, result.output_tokens, result.cost_usd)
        brief = result.parsed.model_dump()
        brief["evidence"] = [{**ref, "video_id": short_to_video[ref["video_id"]]}
                             for ref in brief["evidence"] if ref["video_id"] in short_to_video]
        ctx.store.upsert_brief(ctx.run_id, trend_id, ctx.llm.model, brief, "ok")

    await run_items(ctx, "brief", "llm", todo, brief_one, ctx.settings.concurrency.llm)

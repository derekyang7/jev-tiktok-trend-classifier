"""Stage 10: creator briefs for the selected trends (UGC spec §6.10)."""

import re

from jevtrends.llm.client import LLMOutputError
from jevtrends.models import Video
from jevtrends.stages.context import run_items
from jevtrends.stages.judge import truncate_words
from jevtrends.ugc import scoring
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.models import FacetTrend, UgcTrendScore
from jevtrends.ugc.prompts import BRIEF_SYSTEM, UgcBriefOut, brief_user_prompt
from jevtrends.ugc.stages.judge import promotional_videos, relevant_videos
from jevtrends.ugc.stages.score import evidence_ids

BRIEF_MAX_TOKENS = 16_000
APPROVED_SOUNDS_IN_BRIEF = 5
DISCLOSURE_LINE = "Disclose the paid partnership with TikTok's branded-content setting or #ad."
DISCLOSURE = re.compile(r"disclos|#ad\b|branded[- ]content|paid partnership", re.IGNORECASE)


def ensure_disclosure(dos: list[str]) -> list[str]:
    return dos if any(DISCLOSURE.search(item) for item in dos) else [*dos, DISCLOSURE_LINE]


def eligible_trends(ctx: UgcRunContext, ranked: list[UgcTrendScore]) -> set[str]:
    """Not risky; sounds must also be approved for business use (spec §6.10)."""
    trends = {t.trend_id: t for t in ctx.store.list_facet_trends(ctx.run_id)}
    sounds = {s.sound_id: s for s in ctx.store.list_sounds(ctx.run_id)}
    eligible = set()
    for score in ranked:
        trend = trends[score.trend_id]
        if score.risky or (trend.facet == "sound" and sounds[trend.sound_id].business_use != "approved"):
            continue
        eligible.add(score.trend_id)
    return eligible


def selected_briefs(ctx: UgcRunContext) -> list[str]:
    ranked = ctx.store.list_ugc_scores(ctx.run_id)
    cfg = ctx.settings.briefs
    chosen = scoring.select_briefs(ranked, cfg.quotas, eligible_trends(ctx, ranked))
    return scoring.trim_briefs(chosen, ranked, ctx.limits.get("max_briefs", cfg.max_briefs))


def approved_sounds(ctx: UgcRunContext, ranked: list[UgcTrendScore], trends: dict[str, FacetTrend]) -> list[dict]:
    sounds = {s.sound_id: s for s in ctx.store.list_sounds(ctx.run_id)}
    rows = [{"id": s.trend_id, "title": sounds[trends[s.trend_id].sound_id].title, "usage": trends[s.trend_id].usage}
            for s in ranked if trends[s.trend_id].facet == "sound" and not s.risky
            and sounds[trends[s.trend_id].sound_id].business_use == "approved"]
    return rows[:APPROVED_SOUNDS_IN_BRIEF]


def video_format(video: Video) -> str:
    return (f"slideshow {len(video.slide_urls)}" if video.is_slideshow
            else f"video {round((video.duration_ms or 0) / 1000)}s")


def brief_dossier(ctx: UgcRunContext, trend: FacetTrend, score: UgcTrendScore, evidence: list[str],
                  videos: dict[str, Video], trends: dict[str, FacetTrend], pairs: list[tuple[str, float, float]],
                  sounds: list[dict], promotional: set[str]) -> dict:
    niche = {"name": ctx.niche.name, "covers": ctx.niche.covers}
    if ctx.niche.audience:
        niche["audience"] = ctx.niche.audience
    trend_obj = {"id": trend.trend_id, "facet": trend.facet, "name": trend.name, "definition": trend.definition}
    if trend.template:
        trend_obj["template"] = trend.template
    if trend.usage:
        trend_obj["usage"] = trend.usage
    items = []
    for index, video_id in enumerate(evidence, start=1):
        video, enrichment = videos[video_id], ctx.store.get_enrichment(video_id)
        vision = enrichment.vision if enrichment else None
        items.append({
            "video_id": f"e{index:02d}", "handle": f"@{video.author_handle}", "caption": video.caption,
            "on_screen_text": vision.on_screen_text if vision else "", "setup": vision.setup if vision else "",
            "transcript_excerpt": truncate_words(enrichment.transcript if enrichment else None, 200),
            "top_comments": [c.text for c in ((enrichment.comments if enrichment else None) or [])[:3]],
            "views": video.views, "followers": video.author_followers, "saves": video.saves, "shares": video.shares,
            "posted": video.posted_at.date().isoformat(), "promotional": video_id in promotional,
            "format": video_format(video)})
    dossier = {
        "niche": niche,
        "trend": trend_obj,
        "stats": {"support": round(score.support, 1), "creators": score.creators,
                  "momentum_ratio": round(score.momentum_ratio, 2), "reach_ratio": round(score.reach_ratio, 2),
                  "engagement_ratio": round(score.eng_ratio, 2), "ad_share": round(score.ad_share, 2),
                  "median_views": int(score.median_views)},
        "scores": {"fit": {"value": score.fit_value, "confidence": score.fit_confidence},
                   "ease": {"value": score.ease_value, "confidence": score.ease_confidence}},
        "evidence": items,
        "pairs": [{"id": pid, "facet": trends[pid].facet, "name": trends[pid].name,
                   "definition": trends[pid].template or trends[pid].definition or trends[pid].usage}
                  for pid, _, _ in pairs if pid in trends],
        "approved_sounds": sounds,
    }
    if ctx.product:
        product = ctx.product
        dossier["product"] = {"name": product.name, "one_liner": product.one_liner,
                              "what_it_does": product.what_it_does, "audience": product.audience,
                              "key_benefits": product.key_benefits,
                              "claims_allowed": [{"id": c.id, "text": c.text} for c in product.claims_allowed],
                              "claims_to_avoid": product.claims_to_avoid, "tone": product.tone}
    return dossier


def brief_errors(out: UgcBriefOut, evidence_ids: set[str], claim_ids: set[str], sound_ids: set[str]) -> list[str]:
    errors = []
    if not any(ref.video_id in evidence_ids for ref in out.evidence):
        errors.append("evidence must cite video_id values copied exactly from the evidence list (e01, e02, ...)")
    if any(claim not in claim_ids for claim in out.claims_used):
        allowed = ", ".join(sorted(claim_ids)) or "none, because no product was given"
        errors.append(f"claims_used may only hold these claim ids: {allowed}. Remove every other claim from the "
                      "brief.")
    if out.sound.sound_id not in sound_ids | {"original_audio"}:
        errors.append("sound.sound_id must be one of the approved sound ids listed, or original_audio")
    return errors


async def run_brief(ctx: UgcRunContext) -> None:
    existing = ctx.store.list_ugc_briefs(ctx.run_id)
    selected = selected_briefs(ctx)
    todo = [trend_id for trend_id in selected if trend_id not in existing]
    if not todo:
        return
    ranked = ctx.store.list_ugc_scores(ctx.run_id)
    scores = {s.trend_id: s for s in ranked}
    trends = {t.trend_id: t for t in ctx.store.list_facet_trends(ctx.run_id)}
    members = ctx.store.facet_members(ctx.run_id)
    samples = ctx.store.sound_samples(ctx.run_id)
    ids = list(dict.fromkeys([*relevant_videos(ctx), *(v for videos in samples.values() for v in videos)]))
    videos = ctx.store.get_videos(ids)
    pairs = ctx.store.pairs(ctx.run_id)
    sounds = approved_sounds(ctx, ranked, trends)
    sound_ids = {row["id"] for row in sounds}
    claim_ids = {claim.id for claim in ctx.product.claims_allowed} if ctx.product else set()
    promotional = promotional_videos(ctx)

    async def brief_one(trend_id: str) -> None:
        evidence = evidence_ids(trends[trend_id], members, samples, videos, ctx.settings.trends.evidence_per_trend,
                                ctx.settings.thresholds.relevant)
        short_to_video = {f"e{i:02d}": video_id for i, video_id in enumerate(evidence, start=1)}
        pair_ids = {pid for pid, _, _ in pairs.get(trend_id, []) if pid in trends}
        dossier = brief_dossier(ctx, trends[trend_id], scores[trend_id], evidence, videos, trends,
                                pairs.get(trend_id, []), sounds, promotional)

        def validate(out: UgcBriefOut) -> list[str]:
            return brief_errors(out, set(short_to_video), claim_ids, sound_ids)

        try:
            result = await ctx.llm.complete_json(BRIEF_SYSTEM, brief_user_prompt(dossier), UgcBriefOut,
                                                 max_tokens=BRIEF_MAX_TOKENS, validate=validate)
        except LLMOutputError as exc:
            ctx.record_llm("brief", exc.input_tokens, exc.output_tokens, exc.cost_usd)
            ctx.store.upsert_ugc_brief(ctx.run_id, trend_id, ctx.llm.model, None, "failed")
            return
        ctx.record_llm("brief", result.input_tokens, result.output_tokens, result.cost_usd)
        brief = result.parsed.model_dump()
        brief["evidence"] = [{**ref, "video_id": short_to_video[ref["video_id"]]}
                             for ref in brief["evidence"] if ref["video_id"] in short_to_video]
        brief["pairs_with"] = [pid for pid in brief["pairs_with"] if pid in pair_ids]
        brief["dos"] = ensure_disclosure(brief["dos"])
        ctx.store.upsert_ugc_brief(ctx.run_id, trend_id, ctx.llm.model, brief, "ok")

    await run_items(ctx, "brief", "llm", todo, brief_one, ctx.settings.concurrency.llm, total=len(selected))

"""Stage 9: code metrics plus Jev's fit, ease and brand-risk judgments per trend, then ranking (UGC spec §6.9)."""

import statistics

from jevtrends import scoring as base
from jevtrends.jev.questions import Question
from jevtrends.models import Enrichment, Video
from jevtrends.stages.context import run_items
from jevtrends.stages.judge import truncate_words
from jevtrends.stages.score import evidence_set
from jevtrends.ugc import scoring
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.models import FacetTrend, UgcTrendScore
from jevtrends.ugc.questions import trend_questions
from jevtrends.ugc.stages.judge import promotional_videos, relevant_videos

MIN_SOUND_USES = 3  # below this, a sound's momentum and performance from the sample are too thin to use


def evidence_ids(trend: FacetTrend, members: dict[str, dict[str, float]], samples: dict[str, dict[str, float | None]],
                 videos: dict[str, Video], size: int, relevant_threshold: float) -> list[str]:
    if trend.facet != "sound":
        return evidence_set(members.get(trend.trend_id, {}), size)
    corpus = sorted(members.get(trend.trend_id, {}), key=lambda v: (-videos[v].views, v))
    sampled = sorted((v for v, p in samples.get(trend.sound_id or "", {}).items()
                      if p is not None and p >= relevant_threshold and v not in corpus),
                     key=lambda v: (-videos[v].views, v))
    return (corpus + sampled)[:size]


def ugc_trend_state(ctx: UgcRunContext, trend: FacetTrend, evidence: list[str], videos: dict[str, Video],
                    enrichments: dict[str, Enrichment | None]) -> dict:
    niche = {"name": ctx.niche.name, "covers": ctx.niche.covers}
    if ctx.niche.audience:
        niche["audience"] = ctx.niche.audience
    trend_obj = {"facet": trend.facet, "name": trend.name, "definition": trend.definition}
    if trend.template:
        trend_obj["template"] = trend.template
    if trend.usage:
        trend_obj["usage"] = trend.usage
    items = []
    for video_id in evidence:
        enrichment = enrichments.get(video_id)
        vision = enrichment.vision if enrichment else None
        items.append({
            "caption": videos[video_id].caption or "",
            "on_screen_text": vision.on_screen_text if vision else "",
            "setup": vision.setup if vision else "",
            "transcript_excerpt": truncate_words(enrichment.transcript if enrichment else None, 150),
            "top_comments": [c.text for c in ((enrichment.comments if enrichment else None) or [])[:3]],
        })
    state = {"niche": niche, "trend": trend_obj, "evidence": items}
    if ctx.product:
        state["product"] = {"name": ctx.product.name, "what_it_does": ctx.product.what_it_does,
                            "audience": ctx.product.audience}
    return state


async def run_score(ctx: UgcRunContext) -> None:
    cfg, thresholds = ctx.settings.trends, ctx.settings.thresholds
    trends = ctx.store.list_facet_trends(ctx.run_id, status="kept")
    if not trends:
        return
    members = ctx.store.facet_members(ctx.run_id)
    samples = ctx.store.sound_samples(ctx.run_id)
    relevant = relevant_videos(ctx)
    ids = list(dict.fromkeys([*relevant, *(v for videos in samples.values() for v in videos)]))
    videos = ctx.store.get_videos(ids)
    enrichments = {video_id: ctx.store.get_enrichment(video_id) for video_id in ids}
    questions = trend_questions(with_product=ctx.product is not None)
    evidence = {t.trend_id: evidence_ids(t, members, samples, videos, cfg.evidence_per_trend, thresholds.relevant)
                for t in trends}
    done = ctx.answers(questions[0], subject_type="trend")

    async def score_one(trend: FacetTrend) -> None:
        state = ugc_trend_state(ctx, trend, evidence[trend.trend_id], videos, enrichments)
        await ctx.ask_jev("score", "trend", trend.trend_id, state, questions)

    await run_items(ctx, "score", "jev", [t for t in trends if t.trend_id not in done], score_one,
                    ctx.settings.concurrency.jev, total=len(trends))
    rank_trends(ctx, trends, members, relevant, videos, questions)


def rank_trends(ctx: UgcRunContext, trends: list[FacetTrend], members: dict[str, dict[str, float]],
                relevant: list[str], videos: dict[str, Video], questions: list[Question]) -> None:
    cfg, thresholds = ctx.settings.trends, ctx.settings.thresholds
    relevant_set = set(relevant)
    posted = {v: videos[v].posted_at for v in relevant}
    start = base.recent_start(ctx.now, ctx.settings.scan.lookback_days, cfg.momentum_recent_fraction)
    baseline = base.corpus_recent_share(posted, start)
    if baseline <= 0 or baseline >= 1:
        ctx.store.add_note(ctx.run_id, "Momentum is undefined for this run (all relevant videos fall on one side of "
                                       "the recent window); trends without a usage series got a neutral score.")
    reach_of = {v: scoring.reach(videos[v].views, videos[v].author_followers, cfg.follower_floor) for v in relevant}
    eng_of = {v: scoring.engagement(videos[v].saves, videos[v].shares, videos[v].views) for v in relevant}
    reach_base = statistics.median(reach_of.values()) if reach_of else 0.0
    eng_base = statistics.median(eng_of.values()) if eng_of else 0.0
    promo = {video_id: 1.0 for video_id in promotional_videos(ctx)}
    sounds = {sound.sound_id: sound for sound in ctx.store.list_sounds(ctx.run_id)}
    answers = {q.key: ctx.answers(q, subject_type="trend") for q in questions}
    fit_key = questions[0].key
    scores: list[UgcTrendScore] = []
    neutral_sounds = 0
    for trend in trends:
        tid = trend.trend_id
        if tid not in answers[fit_key]:
            continue  # its Jev request failed and was counted; the trend stays unscored
        trend_members = {v: p for v, p in members.get(tid, {}).items() if v in relevant_set}
        confident = base.confident(trend_members, thresholds.trend_member)
        if trend.facet == "sound":
            sound = sounds[trend.sound_id]
            series = scoring.series_momentum(sound.trend, cfg.momentum_recent_fraction)
            enough = len(confident) >= MIN_SOUND_USES
            if series:
                ratio, momentum_norm = series
            elif enough:
                ratio, momentum_norm = base.momentum(trend_members, posted, start, baseline,
                                                     cfg.momentum_pseudo_count)
            else:
                ratio, momentum_norm = 1.0, 0.5
                neutral_sounds += 1
            perf_ids = confident if enough else []  # sampled song videos are not a random sample
            creators = sound.niche_creators
        else:
            ratio, momentum_norm = base.momentum(trend_members, posted, start, baseline, cfg.momentum_pseudo_count)
            perf_ids = confident
            creators = len({videos[v].author_id for v in confident})
        reach_ratio, eng_ratio, performance_norm = scoring.performance(
            [reach_of[v] for v in perf_ids], [eng_of[v] for v in perf_ids], reach_base, eng_base,
            cfg.performance_pseudo_count)
        fit, ease, risk = answers[fit_key][tid], answers["ease"][tid], answers["brand_risk"][tid]
        scores.append(UgcTrendScore(
            trend_id=tid, facet=trend.facet, support=base.support(trend_members), creators=creators,
            momentum_ratio=ratio, momentum_norm=momentum_norm, reach_ratio=reach_ratio, eng_ratio=eng_ratio,
            performance_norm=performance_norm, breadth_norm=base.breadth_norm(creators),
            fit_norm=float(fit.value) / 3, ease_norm=float(ease.value) / 3, fit_value=float(fit.value),
            ease_value=float(ease.value), fit_confidence=fit.confidence, ease_confidence=ease.confidence,
            risky=float(risk.value) >= thresholds.brand_risk, ad_share=base.promo_share(trend_members, promo),
            median_views=base.median_views(confident, {v: videos[v].views for v in confident})))
    if neutral_sounds:
        ctx.store.add_note(ctx.run_id, f"{neutral_sounds} sounds had no usage series and too few uses in the "
                                       "sample, so they got neutral momentum and performance scores.")
    ctx.store.replace_ugc_scores(ctx.run_id, scoring.rank_ugc(scores, ctx.settings.ranking.weights))
    facet_of = {t.trend_id: t.facet for t in trends}
    kept_members = {t.trend_id: {v: p for v, p in members.get(t.trend_id, {}).items() if v in relevant_set}
                    for t in trends}
    ctx.store.replace_pairs(ctx.run_id, scoring.pair_stats(kept_members, facet_of, len(relevant),
                                                           cfg.pair_min_videos, cfg.pair_min_lift))

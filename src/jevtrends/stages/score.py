"""Stage 7: code metrics plus Jev opportunity scores per kept trend, then ranking (spec §6.7)."""

from jevtrends import scoring
from jevtrends.jev.questions import IS_PROMOTIONAL, PAIN, TREND_QUESTIONS, niche_question
from jevtrends.models import Enrichment, Trend, TrendScore, Video
from jevtrends.stages.context import RunContext, run_items
from jevtrends.stages.judge import signal_videos, truncate_words


EVIDENCE_MIN_P = 0.2  # below this a video is not evidence for the trend (most Jev probabilities are exactly 0)


def evidence_set(members: dict[str, float], size: int, min_p: float = EVIDENCE_MIN_P) -> list[str]:
    ranked = sorted(((v, p) for v, p in members.items() if p >= min_p), key=lambda kv: (-kv[1], kv[0]))
    return [video_id for video_id, _ in ranked[:size]]


def trend_state(trend: Trend, evidence_ids: list[str], videos: dict[str, Video],
                enrichments: dict[str, Enrichment | None]) -> dict:
    evidence = []
    for video_id in evidence_ids:
        enrichment = enrichments.get(video_id)
        evidence.append({
            "caption": videos[video_id].caption or "",
            "transcript_excerpt": truncate_words(enrichment.transcript if enrichment else None, 150),
            "top_comments": [c.text for c in ((enrichment.comments if enrichment else None) or [])[:3]],
        })
    return {"trend": {"name": trend.name, "kind": trend.kind, "definition": trend.definition}, "evidence": evidence}


async def run_score(ctx: RunContext) -> None:
    trends = ctx.store.list_trends(ctx.run_id, status="kept")
    if not trends:
        return
    cfg, thresholds = ctx.settings.trends, ctx.settings.thresholds
    members = ctx.store.trend_members(ctx.run_id)
    signals = signal_videos(ctx)
    videos = ctx.store.get_videos(signals)
    enrichments = {video_id: ctx.store.get_enrichment(video_id) for video_id in signals}

    done = ctx.answers(PAIN, subject_type="trend")

    async def score_one(trend: Trend) -> None:
        evidence_ids = evidence_set(members.get(trend.trend_id, {}), cfg.evidence_per_trend)
        await ctx.ask_jev("score", "trend", trend.trend_id, trend_state(trend, evidence_ids, videos, enrichments),
                          TREND_QUESTIONS)

    await run_items(ctx, "score", "jev", [t for t in trends if t.trend_id not in done], score_one,
                    ctx.settings.concurrency.jev)

    posted = {video_id: videos[video_id].posted_at for video_id in signals}
    start = scoring.recent_start(ctx.now, ctx.settings.scan.lookback_days, cfg.momentum_recent_fraction)
    baseline = scoring.corpus_recent_share(posted, start)
    if baseline <= 0 or baseline >= 1:
        ctx.store.add_note(ctx.run_id, "Momentum is undefined for this scan (all signal videos fall on one side of "
                                       "the recent window); every trend got a neutral momentum score.")
    promo = {video_id: float(a.value) for video_id, a in ctx.answers(IS_PROMOTIONAL).items()}
    niche_probs: dict[str, dict[str, float]] = {}
    for niche in ctx.niches.niches:
        for video_id, answer in ctx.answers(niche_question(niche)).items():
            niche_probs.setdefault(video_id, {})[niche.id] = float(answer.value)
    creator_of = {video_id: video.author_id for video_id, video in videos.items()}
    views = {video_id: video.views for video_id, video in videos.items()}
    jev = {q.key: ctx.answers(q, subject_type="trend") for q in TREND_QUESTIONS}

    scores: list[TrendScore] = []
    for trend in trends:
        tid = trend.trend_id
        if tid not in jev["pain"]:
            continue  # its Jev request failed and was counted; the trend stays unscored
        trend_members = {v: p for v, p in members.get(tid, {}).items() if v in posted}
        confident = scoring.confident(trend_members, thresholds.trend_member)
        ratio, momentum_norm = scoring.momentum(trend_members, posted, start, baseline, cfg.momentum_pseudo_count)
        affinity = scoring.niche_affinity(trend_members, niche_probs)
        niches, primary = scoring.assigned_niches(affinity, thresholds.niche_member, ctx.niches.ids())
        pain, spend, underserved = scoring.normalized_jev_scores(
            float(jev["pain"][tid].value), float(jev["spend"][tid].value),
            float(jev["underserved"][tid].value), float(jev["mentions_solutions"][tid].value))
        creators = len({creator_of[v] for v in confident})
        scores.append(TrendScore(
            trend_id=tid, support=scoring.support(trend_members), creators=creators, momentum_ratio=ratio,
            momentum_norm=momentum_norm, breadth_norm=scoring.breadth_norm(creators),
            median_views=scoring.median_views(confident, views), promo_share=scoring.promo_share(trend_members, promo),
            niche_affinity=affinity, niches=niches, primary_niche=primary,
            pain_norm=pain, spend_norm=spend, underserved_norm=underserved))
    for score in scoring.rank_scores(scores, ctx.settings.ranking.weights):
        ctx.store.upsert_trend_score(ctx.run_id, score)

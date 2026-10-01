"""Quality review of a run's top trends and their tags (UGC spec §14.4)."""

import random
from dataclasses import dataclass

from jevtrends.ugc.context import ugc_report_context
from jevtrends.ugc.models import FacetTrend
from jevtrends.ugc.stages.score import evidence_ids
from jevtrends.ugc.store import UgcStore

PRECISION_TARGET = 0.80
THRESHOLDS = (0.35, 0.50, 0.65)
BORDERLINE_FLOOR = 0.35
CONFIDENT_SAMPLE = 4
BORDERLINE_SAMPLE = 2


@dataclass
class ReviewItem:
    trend: FacetTrend
    evidence: list[str]
    members: list[tuple[str, float]]  # (video id, p) to check; empty for sounds, whose membership is exact


def review_items(store: UgcStore, run_id: int, n_trends: int = 20, seed: int = 0) -> list[ReviewItem]:
    ctx = ugc_report_context(store, run_id)
    rng = random.Random(seed)
    trends = {t.trend_id: t for t in store.list_facet_trends(run_id)}
    members, samples = store.facet_members(run_id), store.sound_samples(run_id)
    threshold = ctx.settings.thresholds.trend_member
    ids = sorted({v for m in members.values() for v in m} | {v for s in samples.values() for v in s})
    videos = store.get_videos(ids)
    items = []
    for score in store.list_ugc_scores(run_id)[:n_trends]:
        trend = trends[score.trend_id]
        trend_members = members.get(trend.trend_id, {})
        picks: list[str] = []
        if trend.facet != "sound":
            confident = sorted(v for v, p in trend_members.items() if p >= threshold)
            borderline = sorted(v for v, p in trend_members.items() if BORDERLINE_FLOOR <= p < threshold)
            picks = (rng.sample(confident, min(CONFIDENT_SAMPLE, len(confident)))
                     + rng.sample(borderline, min(BORDERLINE_SAMPLE, len(borderline))))
        evidence = evidence_ids(trend, members, samples, videos, 3, ctx.settings.thresholds.relevant)
        items.append(ReviewItem(trend=trend, evidence=evidence, members=[(v, trend_members[v]) for v in picks]))
    return items


def compute_review_metrics(store: UgcStore, run_id: int) -> dict:
    ctx = ugc_report_context(store, run_id)
    threshold = ctx.settings.thresholds.trend_member
    trends = {t.trend_id: t for t in store.list_facet_trends(run_id)}
    members = store.facet_members(run_id)
    per_facet: dict[str, dict] = {}
    tagged: list[tuple[float, bool]] = []
    for row in store.list_reviews(run_id):
        trend = trends.get(row["trend_id"])
        if trend is None:
            continue
        stats = per_facet.setdefault(trend.facet, {"reviewed": 0, "real": 0, "would_brief": 0, "checked": 0,
                                                   "fits": 0})
        value = bool(row["value"])
        if row["video_id"] == "" and row["field"] == "real":
            stats["reviewed"] += 1
            stats["real"] += value
        elif row["video_id"] == "" and row["field"] == "would_brief":
            stats["would_brief"] += value
        elif row["field"] == "fits":
            p = members.get(row["trend_id"], {}).get(row["video_id"], 0.0)
            tagged.append((p, value))
            if p >= threshold:
                stats["checked"] += 1
                stats["fits"] += value
    for stats in per_facet.values():
        stats["precision"] = stats["fits"] / stats["checked"] if stats["checked"] else None
    suggested = None
    for candidate in THRESHOLDS:
        above = [fits for p, fits in tagged if p >= candidate]
        if above and sum(above) / len(above) >= PRECISION_TARGET:
            suggested = candidate
            break
    return {"per_facet": per_facet, "reviewed": sum(s["reviewed"] for s in per_facet.values()),
            "real": sum(s["real"] for s in per_facet.values()),
            "would_brief": sum(s["would_brief"] for s in per_facet.values()), "suggested_threshold": suggested}

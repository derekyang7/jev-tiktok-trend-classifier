"""Pure scoring functions (spec §6.6–§6.8). No I/O; members maps video id -> p(v, t) for one trend."""

import math
import statistics
from datetime import datetime, timedelta

from jevtrends.models import TrendScore


def support(members: dict[str, float]) -> float:
    return sum(members.values())


def confident(members: dict[str, float], threshold: float) -> list[str]:
    return [video_id for video_id, p in members.items() if p >= threshold]


def prune_reason(members: dict[str, float], creator_of: dict[str, str], min_support: float,
                 min_creators: int, threshold: float) -> str | None:
    total = support(members)
    if total < min_support:
        return f"support {total:.1f} < {min_support}"
    creators = {creator_of[video_id] for video_id in confident(members, threshold)}
    if len(creators) < min_creators:
        return f"{len(creators)} distinct creators < {min_creators}"
    return None


def top_choices(probs_by_video: dict[str, dict[str, float]]) -> dict[str, str]:
    return {video_id: max(probs, key=probs.get) for video_id, probs in probs_by_video.items() if probs}


def self_check(trend_id: str, example_ids: list[str], top_choice: dict[str, str]) -> float | None:
    judged = [video_id for video_id in example_ids if video_id in top_choice]
    if not judged:
        return None
    return sum(top_choice[video_id] == trend_id for video_id in judged) / len(judged)


def none_rate(top_choice: dict[str, str], none_key: str) -> float:
    if not top_choice:
        return 0.0
    return sum(choice == none_key for choice in top_choice.values()) / len(top_choice)


def recent_start(now: datetime, lookback_days: int, recent_fraction: float) -> datetime:
    return now - timedelta(days=lookback_days * recent_fraction)


def corpus_recent_share(posted_at: dict[str, datetime], start: datetime) -> float:
    if not posted_at:
        return 0.0
    return sum(ts >= start for ts in posted_at.values()) / len(posted_at)


def momentum(members: dict[str, float], posted_at: dict[str, datetime], start: datetime,
             c: float, k: float) -> tuple[float, float]:
    """Shrunk recent-share ratio against the corpus baseline c, and its 0-1 normalization."""
    if c <= 0 or c >= 1:
        return 1.0, 0.5
    total = support(members)
    recent = sum(p for video_id, p in members.items() if posted_at[video_id] >= start)
    ratio = (recent + k * c) / ((total + k) * c)
    return ratio, min(1.0, max(0.0, (math.log2(ratio) + 2) / 4))


def breadth_norm(creators: int) -> float:
    return min(1.0, math.log(1 + creators) / math.log(21))


def niche_affinity(members: dict[str, float], niche_probs: dict[str, dict[str, float]]) -> dict[str, float]:
    total = support(members)
    if total == 0:
        return {}
    niches = sorted({niche for video_id in members for niche in niche_probs.get(video_id, {})})
    return {niche: sum(p * niche_probs.get(video_id, {}).get(niche, 0.0) for video_id, p in members.items()) / total
            for niche in niches}


def assigned_niches(affinity: dict[str, float], threshold: float, order: list[str]) -> tuple[list[str], str | None]:
    niches = [niche for niche in order if affinity.get(niche, 0.0) >= threshold]
    return niches, (max(niches, key=lambda n: affinity[n]) if niches else None)


def promo_share(members: dict[str, float], promo_prob: dict[str, float]) -> float:
    total = support(members)
    if total == 0:
        return 0.0
    return sum(p for video_id, p in members.items() if promo_prob.get(video_id, 0.0) >= 0.5) / total


def median_views(video_ids: list[str], views: dict[str, int]) -> float:
    return float(statistics.median(views[v] for v in video_ids)) if video_ids else 0.0


def normalized_jev_scores(pain: float, spend: float, underserved: float,
                          mentions_solutions: float) -> tuple[float, float, float]:
    """Scores are on 0-3 levels. Underserved is neutral (0.5) when the evidence says nothing about solutions."""
    return pain / 3, spend / 3, (underserved / 3 if mentions_solutions >= 0.5 else 0.5)


def opportunity(score: TrendScore, weights: dict[str, float]) -> float:
    return (weights["momentum"] * score.momentum_norm + weights["pain"] * score.pain_norm
            + weights["spend"] * score.spend_norm + weights["underserved"] * score.underserved_norm
            + weights["breadth"] * score.breadth_norm)


def rank_scores(scores: list[TrendScore], weights: dict[str, float]) -> list[TrendScore]:
    scored = sorted((s.model_copy(update={"opportunity": opportunity(s, weights)}) for s in scores),
                    key=lambda s: (-s.opportunity, s.trend_id))
    return [s.model_copy(update={"rank": rank}) for rank, s in enumerate(scored, start=1)]


def select_for_briefs(ranked: list[TrendScore], niche_order: list[str], max_briefs: int) -> list[str]:
    """Top trend per niche (config order) first, then best remaining by rank; returned in rank order."""
    selected: list[str] = []
    for niche in niche_order:
        pick = next((s.trend_id for s in ranked if niche in s.niches and s.trend_id not in selected), None)
        if pick is not None and len(selected) < max_briefs:
            selected.append(pick)
    for s in ranked:
        if len(selected) >= max_briefs:
            break
        if s.trend_id not in selected:
            selected.append(s.trend_id)
    return [s.trend_id for s in ranked if s.trend_id in selected]

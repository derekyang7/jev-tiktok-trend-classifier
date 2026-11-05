"""Pure scoring functions for startup opportunities (spec §6.6–§6.8). No I/O."""

from jevtrends.core.scoring import support
from jevtrends.opportunities.models import TrendScore


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

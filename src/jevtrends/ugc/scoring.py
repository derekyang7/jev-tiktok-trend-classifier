"""Pure scoring functions for the UGC version (UGC spec §6.6–§6.10). No I/O."""

import math
import statistics
from collections import Counter

from jevtrends.ugc.models import UgcTrendScore

BRIEF_FACET_ORDER = ("format", "hook", "sound", "topic", "need")


def facet_count_range(digest_videos: int, videos_per_candidate: int, max_candidates: int) -> tuple[int, int]:
    """(low, high) candidates per facet: about one per `videos_per_candidate` digest videos (spec §6.7)."""
    high = min(max_candidates, max(1, digest_videos // videos_per_candidate))
    return max(1, high // 3), high


def reach(views: int, followers: int | None, floor: int) -> float:
    return views / max(followers or 0, floor)


def engagement(saves: int, shares: int, views: int) -> float:
    return (saves + shares) / max(views, 1)


def log_norm(log_ratio: float) -> float:
    """0.25x -> 0, 1x -> 0.5, 4x -> 1: the same mapping as V1's momentum."""
    return min(1.0, max(0.0, (log_ratio + 2) / 4))


def _shrunk_log(ratio: float, n: int, k: float) -> float:
    log_ratio = math.log2(ratio) if ratio > 0 else -2.0
    return log_ratio * n / (n + k)


def performance(reach_values: list[float], eng_values: list[float], reach_baseline: float, eng_baseline: float,
                k: float) -> tuple[float, float, float]:
    """(reach ratio, engagement ratio, performance_norm) of a trend's confident members against the sample."""
    if not reach_values or reach_baseline <= 0 or eng_baseline <= 0:
        return 1.0, 1.0, 0.5
    n = len(reach_values)
    r = _shrunk_log(statistics.median(reach_values) / reach_baseline, n, k)
    e = _shrunk_log(statistics.median(eng_values) / eng_baseline, n, k)
    return 2 ** r, 2 ** e, (log_norm(r) + log_norm(e)) / 2


def series_momentum(series: list[float], recent_fraction: float) -> tuple[float, float] | None:
    """Mean of the most recent part of a usage series over the whole series' mean (spec §6.9)."""
    if len(series) < 3:
        return None
    overall = sum(series) / len(series)
    if overall <= 0:
        return None
    n = max(1, round(len(series) * recent_fraction))
    ratio = (sum(series[-n:]) / n) / overall
    return ratio, log_norm(math.log2(ratio) if ratio > 0 else -2.0)


def pair_stats(members: dict[str, dict[str, float]], facet_of: dict[str, str], n_videos: int, min_co: float,
               min_lift: float, top: int = 3) -> list[tuple[str, str, float, float]]:
    """For each trend, up to `top` partners from other facets that share its videos more than chance (spec §6.9)."""
    support = {trend_id: sum(m.values()) for trend_id, m in members.items()}
    rows: list[tuple[str, str, float, float]] = []
    for a, a_members in members.items():
        partners = []
        for b, b_members in members.items():
            if facet_of[a] == facet_of[b] or not support[a] or not support[b]:
                continue
            co = sum(p * b_members.get(video_id, 0.0) for video_id, p in a_members.items())
            lift = co * n_videos / (support[a] * support[b])
            if co >= min_co and lift >= min_lift:
                partners.append((b, co, lift))
        partners.sort(key=lambda item: (-item[1], item[0]))
        rows += [(a, b, co, lift) for b, co, lift in partners[:top]]
    return rows


def business_use(listed_commercial: bool | None, in_business_list: bool, raw_flags: dict,
                 trusted_flag: str) -> tuple[str, str]:
    """The business-use label of a sound and the verified source it comes from (spec §4.4)."""
    if listed_commercial is not None:
        return ("approved" if listed_commercial else "organic_only"), "popular-songs data"
    if in_business_list:
        return "approved", "business-use filter"
    if trusted_flag and raw_flags.get(trusted_flag) is not None:
        return ("approved" if raw_flags[trusted_flag] else "organic_only"), f"TikTok flag {trusted_flag}"
    return "unknown", ""


def composite(score: UgcTrendScore, weights: dict[str, float]) -> float:
    return (weights["momentum"] * score.momentum_norm + weights["performance"] * score.performance_norm
            + weights["fit"] * score.fit_norm + weights["breadth"] * score.breadth_norm
            + weights["ease"] * score.ease_norm)


def rank_ugc(scores: list[UgcTrendScore], weights: dict[str, float]) -> list[UgcTrendScore]:
    scored = sorted((s.model_copy(update={"score": composite(s, weights)}) for s in scores),
                    key=lambda s: (-s.score, s.trend_id))
    in_facet: Counter = Counter()
    ranked = []
    for rank, s in enumerate(scored, start=1):
        in_facet[s.facet] += 1
        ranked.append(s.model_copy(update={"rank_overall": rank, "rank_in_facet": in_facet[s.facet]}))
    return ranked


def select_briefs(ranked: list[UgcTrendScore], quotas: dict[str, int], eligible: set[str]) -> list[str]:
    """Each facet's top eligible trends up to its quota, then the best remaining eligible trends (spec §6.10)."""
    selected: list[str] = []
    for facet in BRIEF_FACET_ORDER:
        picks = [s.trend_id for s in ranked if s.facet == facet and s.trend_id in eligible]
        selected += picks[:quotas.get(facet, 0)]
    total = sum(quotas.values())
    for s in ranked:
        if len(selected) >= total:
            break
        if s.trend_id in eligible and s.trend_id not in selected:
            selected.append(s.trend_id)
    order = {s.trend_id: s.rank_overall for s in ranked}
    return sorted(selected, key=lambda trend_id: order[trend_id])


def trim_briefs(selected: list[str], ranked: list[UgcTrendScore], keep: int) -> list[str]:
    """Drops the lowest-scoring briefs until `keep` remain; a facet's last brief goes only when no facet has two."""
    by_id = {s.trend_id: s for s in ranked}
    chosen = list(selected)
    while len(chosen) > max(keep, 0):
        counts = Counter(by_id[t].facet for t in chosen)
        spread = all(n <= 1 for n in counts.values())
        victim = next(t for t in sorted(chosen, key=lambda t: (by_id[t].score, -by_id[t].rank_overall))
                      if spread or counts[by_id[t].facet] > 1)
        chosen.remove(victim)
    return chosen

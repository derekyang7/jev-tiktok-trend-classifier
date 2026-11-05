"""Pure scoring functions shared across pipelines (spec §6.6–§6.8)."""

import math
import statistics
from datetime import datetime, timedelta

EVIDENCE_MIN_P = 0.2  # below this a video is not evidence for the trend (most Jev probabilities are exactly 0)


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


def promo_share(members: dict[str, float], promo_prob: dict[str, float]) -> float:
    total = support(members)
    if total == 0:
        return 0.0
    return sum(p for video_id, p in members.items() if promo_prob.get(video_id, 0.0) >= 0.5) / total


def median_views(video_ids: list[str], views: dict[str, int]) -> float:
    return float(statistics.median(views[v] for v in video_ids)) if video_ids else 0.0


def evidence_set(members: dict[str, float], size: int, min_p: float = EVIDENCE_MIN_P) -> list[str]:
    ranked = sorted(((v, p) for v, p in members.items() if p >= min_p), key=lambda kv: (-kv[1], kv[0]))
    return [video_id for video_id, _ in ranked[:size]]

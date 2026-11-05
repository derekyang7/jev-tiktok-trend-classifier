"""Domain models for the startup opportunities pipeline (spec §6, §8)."""

from typing import Literal

from pydantic import BaseModel, Field

TrendKind = Literal["behavior_need", "product_traction", "complaint_workaround"]


class Trend(BaseModel):
    trend_id: str
    name: str
    kind: TrendKind
    definition: str
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    example_video_ids: list[str] = Field(default_factory=list)  # TikTok ids, not short ids
    status: Literal["proposed", "kept", "pruned"] = "proposed"
    prune_reason: str | None = None
    self_check_agreement: float | None = None


class TrendScore(BaseModel):
    trend_id: str
    support: float
    creators: int
    momentum_ratio: float
    momentum_norm: float
    breadth_norm: float
    median_views: float
    promo_share: float
    niche_affinity: dict[str, float]
    niches: list[str]
    primary_niche: str | None
    pain_norm: float = 0.0
    spend_norm: float = 0.0
    underserved_norm: float = 0.5
    opportunity: float = 0.0
    rank: int = 0

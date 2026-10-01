"""Domain models for the UGC version (UGC spec §6, §8)."""

from typing import Literal

from pydantic import BaseModel, Field

FACETS = ("format", "hook", "sound", "topic", "need")
LLM_FACETS = ("format", "hook", "topic", "need")  # proposed by the LLM and assigned by Jev; sounds match by id
Facet = Literal["format", "hook", "sound", "topic", "need"]
BusinessUse = Literal["approved", "organic_only", "unknown"]


class FacetTrend(BaseModel):
    """A candidate trend on one facet. Each sound candidate is also a FacetTrend, with `sound_id` set."""

    trend_id: str
    facet: Facet
    name: str
    definition: str = ""
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    template: str = ""
    usage: str = ""
    example_video_ids: list[str] = Field(default_factory=list)  # TikTok ids, not short ids
    sound_id: str | None = None
    status: Literal["proposed", "kept", "pruned"] = "proposed"
    prune_reason: str | None = None
    self_check_agreement: float | None = None


class SoundCandidate(BaseModel):
    sound_id: str
    title: str = ""
    author: str = ""
    source: list[Literal["popular", "niche"]] = Field(default_factory=list)
    popular_rank: int | None = None
    link: str = ""
    trend: list[float] = Field(default_factory=list)
    use_count: int = 0
    listed_commercial: bool | None = None  # the popular list's per-song business-use flag
    in_business_list: bool = False  # appeared in the approved-for-business list
    business_use: BusinessUse = "unknown"
    business_use_source: str = ""
    sampled: bool = False
    niche_creators: int = 0
    niche_share: float | None = None


class UgcTrendScore(BaseModel):
    trend_id: str
    facet: Facet
    support: float
    creators: int
    momentum_ratio: float
    momentum_norm: float
    reach_ratio: float
    eng_ratio: float
    performance_norm: float
    breadth_norm: float
    fit_norm: float = 0.0
    ease_norm: float = 0.0
    fit_value: float = 0.0
    ease_value: float = 0.0
    fit_confidence: float | None = None
    ease_confidence: float | None = None
    risky: bool = False
    ad_share: float = 0.0
    median_views: float = 0.0
    score: float = 0.0
    rank_overall: int = 0
    rank_in_facet: int = 0

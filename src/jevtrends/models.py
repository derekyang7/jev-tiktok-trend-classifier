"""Domain models shared across modules."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TrendKind = Literal["behavior_need", "product_traction", "complaint_workaround"]


class Video(BaseModel):
    id: str
    url: str
    author_id: str
    author_handle: str
    author_bio: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    sound: str = ""
    posted_at: datetime
    views: int = 0
    likes: int = 0
    comment_count: int = 0
    shares: int = 0
    language: str | None = None
    raw: dict = Field(default_factory=dict)


class Comment(BaseModel):
    text: str
    likes: int = 0


class Enrichment(BaseModel):
    video_id: str
    transcript: str | None = None
    transcript_status: Literal["ok", "missing", "error"] | None = None
    transcript_fetched_at: datetime | None = None
    comments: list[Comment] | None = None
    comments_fetched_at: datetime | None = None


class Answer(BaseModel):
    """One Jev answer. value is a probability (noul), an option key (choice) or a level score (score)."""

    value: float | str
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


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

"""Domain models shared across pipelines."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SoundInfo(BaseModel):
    """The sound a video uses. `licensing` keeps TikTok's raw, undocumented flags (UGC spec §2.3)."""

    id: str
    title: str = ""
    author: str = ""
    is_original: bool = False
    use_count: int = 0
    licensing: dict[str, bool | int | None] = Field(default_factory=dict)
    id_rounded: bool = False  # Top search sends the id as a JSON number already rounded to a double upstream


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
    # Filled for the UGC pipeline (UGC spec §5.2); opportunities ignores them.
    duration_ms: int | None = None
    is_slideshow: bool = False
    cover_url: str | None = None
    slide_urls: list[str] = Field(default_factory=list)
    sound_info: SoundInfo | None = None
    author_followers: int | None = None
    saves: int = 0
    editing_features: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    ad_flags: dict[str, bool | int] = Field(default_factory=dict)


class Comment(BaseModel):
    text: str
    likes: int = 0


class VisionRead(BaseModel):
    """On-screen text and setup read from a video's cover frame or first slides (UGC spec §6.4)."""

    on_screen_text: str = ""
    setup: str = ""
    status: Literal["ok", "no_image", "error"] = "ok"
    model: str = ""


class Enrichment(BaseModel):
    video_id: str
    transcript: str | None = None
    transcript_status: Literal["ok", "missing", "error", "not_applicable"] | None = None
    transcript_fetched_at: datetime | None = None
    comments: list[Comment] | None = None
    comments_fetched_at: datetime | None = None
    vision: VisionRead | None = None


class Answer(BaseModel):
    """One Jev answer. value is a probability (noul), an option key (choice) or a level score (score)."""

    value: float | str
    probabilities: dict[str, float] | None = None
    confidence: float | None = None

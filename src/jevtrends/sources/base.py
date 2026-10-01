"""The data-source interface stages depend on (spec §5.2)."""

from dataclasses import dataclass
from typing import Protocol

from jevtrends.models import Comment, Video


@dataclass
class SearchPage:
    videos: list[Video]
    next_cursor: int | None
    credits: int


@dataclass
class TranscriptResult:
    text: str | None
    credits: int


@dataclass
class CommentsResult:
    comments: list[Comment]
    credits: int


class Source(Protocol):
    async def search(self, query: str, lookback_days: int, region: str, cursor: int | None = None) -> SearchPage: ...

    async def transcript(self, video: Video) -> TranscriptResult: ...

    async def comments(self, video: Video, limit: int, max_chars: int) -> CommentsResult: ...


@dataclass
class Song:
    """One entry of TikTok's popular-songs list (UGC spec §6.6)."""

    sound_id: str
    title: str
    author: str
    rank: int
    link: str
    commercial: bool | None  # TikTok's per-song "approved for business use" flag, when the list includes one
    trend: list[float]  # usage series, oldest first; empty when the list doesn't include one


@dataclass
class SongsPage:
    songs: list[Song]
    has_more: bool
    credits: int


class UgcSource(Source, Protocol):
    """V1's source plus the searches and song lists the UGC pipeline uses (UGC spec §4.2)."""

    async def search_hashtag(self, hashtag: str, region: str, cursor: int | None = None) -> SearchPage: ...

    async def search_top(self, query: str, lookback_days: int, region: str,
                         cursor: int | None = None) -> SearchPage: ...

    async def popular_songs(self, period_days: int, country: str, page: int, commercial_only: bool) -> SongsPage: ...

    async def song_videos(self, sound_id: str, cursor: int | None = None) -> SearchPage: ...

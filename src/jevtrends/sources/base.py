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

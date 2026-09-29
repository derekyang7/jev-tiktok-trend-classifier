"""ScrapeCreators TikTok adapter (spec §4.2). Field names verified by Task 1's contract fixtures."""

from datetime import UTC, datetime

import httpx

from jevtrends.config import RetriesCfg
from jevtrends.http import FatalAPIError, send_with_retry
from jevtrends.models import Comment, Video
from jevtrends.sources.base import CommentsResult, SearchPage, TranscriptResult

BASE_URL = "https://api.scrapecreators.com"
# Per-video errors (no captions, photo posts, private or deleted videos) mean "unavailable";
# 401/402 (key or credits) stay fatal.
UNAVAILABLE_STATUS = {400, 403, 404, 422}


def date_posted_for(lookback_days: int) -> str:
    """Smallest ScrapeCreators time frame that covers the lookback; exact filtering happens in collect."""
    for limit, value in ((1, "yesterday"), (7, "this-week"), (31, "this-month"),
                         (92, "last-3-months"), (183, "last-6-months")):
        if lookback_days <= limit:
            return value
    return "all-time"


def parse_video(info: dict) -> Video:
    author = info.get("author") or {}
    stats = info.get("statistics") or {}
    handle = author.get("unique_id") or ""
    video_id = str(info["aweme_id"])
    return Video(
        id=video_id,
        url=f"https://www.tiktok.com/@{handle}/video/{video_id}",
        author_id=str(author.get("uid") or handle),
        author_handle=handle,
        author_bio=author.get("signature") or "",
        caption=info.get("desc") or "",
        hashtags=[t["hashtag_name"] for t in info.get("text_extra") or [] if t.get("hashtag_name")],
        sound=(info.get("music") or {}).get("title") or "",
        posted_at=datetime.fromtimestamp(int(info["create_time"]), tz=UTC),
        views=int(stats.get("play_count") or 0),
        likes=int(stats.get("digg_count") or 0),
        comment_count=int(stats.get("comment_count") or 0),
        shares=int(stats.get("share_count") or 0),
        language=info.get("desc_language") or None,
        raw={k: v for k, v in info.items() if k != "video"},
    )


def vtt_to_text(vtt: str | None) -> str | None:
    """Joins WebVTT cue text into plain text, dropping timings and consecutive duplicate lines."""
    if not vtt or not vtt.strip():
        return None
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or "-->" in line or line.isdigit():
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return " ".join(lines) or None


class ScrapeCreatorsSource:
    def __init__(self, client: httpx.AsyncClient, api_key: str, retries: RetriesCfg, base_url: str = BASE_URL):
        self.client = client
        self.api_key = api_key
        self.retries = retries
        self.base_url = base_url

    async def _get(self, path: str, params: dict) -> dict:
        response = await send_with_retry(self.client, "scrapecreators", "GET", f"{self.base_url}{path}",
                                         retries=self.retries, params=params, headers={"x-api-key": self.api_key})
        return response.json()

    async def search(self, query: str, lookback_days: int, region: str, cursor: int | None = None) -> SearchPage:
        params: dict = {"query": query, "date_posted": date_posted_for(lookback_days), "sort_by": "relevance",
                        "region": region}
        if cursor is not None:
            params["cursor"] = cursor
        data = await self._get("/v1/tiktok/search/keyword", params)
        videos = [parse_video(item["aweme_info"]) for item in data.get("search_item_list") or []
                  if (item.get("aweme_info") or {}).get("aweme_id") and item["aweme_info"].get("create_time")]
        more = data.get("has_more") in (None, 1, True)
        next_cursor = data.get("cursor") if videos and more else None
        return SearchPage(videos=videos, next_cursor=next_cursor, credits=int(data.get("credits_charged", 1)))

    async def transcript(self, video: Video) -> TranscriptResult:
        try:
            data = await self._get("/v1/tiktok/video/transcript", {"url": video.url, "language": "en"})
        except FatalAPIError as exc:
            if exc.status in UNAVAILABLE_STATUS:
                return TranscriptResult(text=None, credits=1)
            raise
        return TranscriptResult(text=vtt_to_text(data.get("transcript")), credits=int(data.get("credits_charged", 1)))

    async def comments(self, video: Video, limit: int, max_chars: int) -> CommentsResult:
        try:
            data = await self._get("/v1/tiktok/video/comments", {"url": video.url})
        except FatalAPIError as exc:
            if exc.status in UNAVAILABLE_STATUS:
                return CommentsResult(comments=[], credits=1)
            raise
        raw = [c for c in data.get("comments") or [] if (c.get("text") or "").strip()]
        raw.sort(key=lambda c: int(c.get("digg_count") or 0), reverse=True)
        comments = [Comment(text=c["text"].strip()[:max_chars], likes=int(c.get("digg_count") or 0)) for c in raw[:limit]]
        return CommentsResult(comments=comments, credits=int(data.get("credits_charged", 1)))

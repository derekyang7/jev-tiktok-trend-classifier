"""ScrapeCreators TikTok adapter (spec §4.2). Field names verified by Task 1's contract fixtures."""

import re
from datetime import UTC, datetime

import httpx

from jevtrends.config import RetriesCfg
from jevtrends.http import FatalAPIError, send_with_retry
from jevtrends.models import Comment, SoundInfo, Video
from jevtrends.sources.base import CommentsResult, SearchPage, TranscriptResult

BASE_URL = "https://api.scrapecreators.com"
# Per-video errors (no captions, photo posts, private or deleted videos) mean "unavailable";
# 401/402 (key or credits) stay fatal.
UNAVAILABLE_STATUS = {400, 403, 404, 422}
LICENSING_KEYS = ("is_commerce_music", "is_commerce_music_strict", "has_commerce_right", "has_commerce_right_strict",
                  "commercial_right_type")
HASHTAG = re.compile(r"#(\w+)")


def first_url(node: object) -> str | None:
    """The first link in a TikTok media object ({"url_list": [...]}), or the node itself if it is a link."""
    if isinstance(node, str):
        return node or None
    urls = node.get("url_list") if isinstance(node, dict) else None
    return next((url for url in urls or [] if isinstance(url, str) and url), None)


def parse_sound(music: dict | None) -> SoundInfo | None:
    music = music or {}
    sound_id = str(music.get("id_str") or music.get("id") or "")
    if not sound_id:
        return None
    return SoundInfo(id=sound_id, title=music.get("title") or "", author=music.get("author") or "",
                     is_original=bool(music.get("is_original_sound")), use_count=int(music.get("user_count") or 0),
                     licensing={key: music[key] for key in LICENSING_KEYS if key in music})


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
    media = info.get("video") or {}
    commerce = info.get("commerce_info") or {}
    slides = [first_url(image.get("display_image")) for image in (info.get("image_post_info") or {}).get("images") or []
              if isinstance(image, dict)]
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
        duration_ms=int(media["duration"]) if media.get("duration") else None,
        is_slideshow=any(slides),
        # `cover` is a JPEG; `origin_cover` is HEIC, which Pillow can't read (contract check D6).
        cover_url=first_url(media.get("cover")) or first_url(media.get("origin_cover")),
        slide_urls=[url for url in slides if url],
        sound_info=parse_sound(info.get("music")),
        author_followers=int(author["follower_count"]) if author.get("follower_count") is not None else None,
        saves=int(stats.get("collect_count") or 0),
        editing_features=[str(f) for f in (info.get("creation_info") or {}).get("creation_used_functions") or []],
        anchors=[a["keyword"] for a in info.get("anchors") or [] if isinstance(a, dict) and a.get("keyword")],
        ad_flags={"is_ad": bool(info.get("is_ad")), "is_paid_partnership": bool(info.get("is_paid_partnership")),
                  "branded_content_type": int(commerce.get("branded_content_type") or 0)},
    )


def parse_top_item(item: dict) -> Video:
    """Top-search items use `id`, `content_type` and a flat `images` list (UGC spec §4.2); normalize, then parse."""
    info = dict(item)
    info["aweme_id"] = str(item.get("aweme_id") or item.get("id"))
    if item.get("content_type") == "multi_photo" and not item.get("image_post_info"):
        urls = [first_url(image) if not isinstance(image, dict) or "url_list" in image
                else first_url(image.get("display_image")) for image in item.get("images") or []]
        info["image_post_info"] = {"images": [{"display_image": {"url_list": [url]}} for url in urls if url]}
    if not item.get("text_extra"):
        info["text_extra"] = [{"hashtag_name": tag} for tag in HASHTAG.findall(item.get("desc") or "")]
    return parse_video(info)


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

"""Deterministic stand-ins for the UGC pipeline's source, image downloads and vision model, plus a context factory."""

import io
from datetime import UTC, datetime

from PIL import Image

from jevtrends.budget import BudgetGuard
from jevtrends.http import FatalAPIError
from jevtrends.llm.client import ImagePart, LLMOutputError, LLMResult
from jevtrends.sources.base import SearchPage, Song, SongsPage
from jevtrends.ugc.config import NicheProfile, ProductProfile, RunProfiles, UgcSettings
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.prompts import VisionOut
from jevtrends.ugc.store import UgcStore
from tests.fakes import FakeJev, FakeLLM, FakeSource

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def niche() -> NicheProfile:
    return NicheProfile(id="consumer_apps", name="Consumer apps", covers="Apps people use every day",
                        not_for="Business software", audience="Young adults", seed_queries=["apps you need"],
                        hashtags=["appsyouneed"])


def product() -> ProductProfile:
    return ProductProfile(id="streak", name="StreakBuddy", what_it_does="Habit streaks with friends",
                          audience="Students", claims_allowed=[{"id": "c1", "text": "Free to download"}],
                          claims_to_avoid=["Health outcomes"])


def tiny_png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _page(pages: list[list], cursor: int | None) -> SearchPage:
    index = cursor or 0
    videos = pages[index] if index < len(pages) else []
    return SearchPage(videos=videos, next_cursor=index + 1 if index + 1 < len(pages) else None, credits=1)


class FakeUgcSource(FakeSource):
    """V1's fake plus hashtag and Top searches, popular songs and song pages.

    `business_songs=None` means the business-use filter is ignored and returns the full list.
    """

    def __init__(self, pages=None, hashtag_pages=None, top_pages=None, transcripts=None, comments=None,
                 songs: list[Song] | None = None, business_songs: list[Song] | None = None, song_pages=None,
                 fail_top: Exception | None = None, fail_songs: Exception | None = None):
        super().__init__(pages=pages, transcripts=transcripts, comments=comments)
        self.hashtag_pages = hashtag_pages or {}
        self.top_pages = top_pages or {}
        self.songs = songs or []
        self.business_songs = business_songs
        self.song_pages = song_pages or {}
        self.fail_top = fail_top
        self.fail_songs = fail_songs

    async def search_hashtag(self, hashtag: str, region: str, cursor: int | None = None) -> SearchPage:
        self.calls.append(("hashtag", hashtag, cursor))
        return _page(self.hashtag_pages.get(hashtag, []), cursor)

    async def search_top(self, query: str, lookback_days: int, region: str, cursor: int | None = None) -> SearchPage:
        self.calls.append(("top", query, cursor))
        if self.fail_top:
            raise self.fail_top
        return _page(self.top_pages.get(query, []), cursor)

    async def popular_songs(self, period_days: int, country: str, page: int, commercial_only: bool) -> SongsPage:
        self.calls.append(("songs", page, commercial_only))
        if self.fail_songs:
            raise self.fail_songs
        songs = self.business_songs if commercial_only and self.business_songs is not None else self.songs
        return SongsPage(songs=list(songs) if page == 1 else [], has_more=False, credits=1)

    async def song_videos(self, sound_id: str, cursor: int | None = None) -> SearchPage:
        self.calls.append(("song_videos", sound_id, cursor))
        return _page(self.song_pages.get(sound_id, []), cursor)


class FakeImages:
    """Serves bytes by URL; an unknown URL behaves like an expired link."""

    def __init__(self, images: dict[str, bytes] | None = None):
        self.images = images or {}
        self.calls: list[str] = []

    async def fetch(self, url: str, max_bytes: int) -> bytes | None:
        self.calls.append(url)
        data = self.images.get(url)
        return data if data is not None and len(data) <= max_bytes else None


class FakeVision:
    """Reads images by their bytes: `reads` maps the first image's bytes to what it shows."""

    model = "fake-vision"

    def __init__(self, reads: dict[bytes, VisionOut] | None = None, fail_on: set[bytes] | None = None,
                 fatal_on: set[bytes] | None = None):
        self.reads = reads or {}
        self.fail_on = fail_on or set()
        self.fatal_on = fatal_on or set()
        self.calls: list[tuple[str, list[ImagePart]]] = []

    async def complete_json(self, system, user, schema, max_tokens, validate=None, images=None) -> LLMResult:
        images = images or []
        self.calls.append((user, images))
        first = images[0].data if images else b""
        if first in self.fatal_on:
            raise FatalAPIError("openrouter", 401, "bad key")
        if first in self.fail_on:
            raise LLMOutputError("unreadable", 800, 10, None)
        read = self.reads.get(first, VisionOut(on_screen_text="", setup="person talking to camera"))
        return LLMResult(parsed=read, input_tokens=800, output_tokens=40, cost_usd=None)


def sequential(**scan) -> UgcSettings:
    """Default settings with one request at a time, so call order is deterministic."""
    settings = UgcSettings()
    settings.scan = settings.scan.model_copy(update=scan)
    settings.concurrency = settings.concurrency.model_copy(update={"scraper": 1, "jev": 1, "llm": 1, "vision": 1})
    return settings


def make_ugc_ctx(source=None, jev=None, llm=None, vision=None, images=None, settings: UgcSettings | None = None,
                 store: UgcStore | None = None, run_id: int | None = None, with_product: bool = False) -> UgcRunContext:
    settings = settings or sequential()
    store = store or UgcStore(":memory:")
    profiles = RunProfiles(niche=niche(), product=product() if with_product else None)
    if run_id is None:
        run_id = store.create_run({"lookback_days": settings.scan.lookback_days}, settings, profiles, NOW)
    return UgcRunContext(run_id=run_id, store=store, settings=settings, niche=profiles.niche,
                         product=profiles.product, source=source or FakeUgcSource(), jev=jev or FakeJev(),
                         llm=llm or FakeLLM(lambda *args: None), vision=vision or FakeVision(),
                         images=images or FakeImages(),
                         budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=NOW)

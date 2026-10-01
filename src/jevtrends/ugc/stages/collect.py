"""Stage 1: keyword, hashtag and Top searches → deduplicated video records (UGC spec §6.1)."""

import asyncio
import math
from datetime import timedelta

from jevtrends.http import APIError
from jevtrends.sources.base import SearchPage
from jevtrends.stages.collect import is_english_or_unknown
from jevtrends.stages.context import run_items
from jevtrends.ugc.context import UgcRunContext, is_account_error


async def fetch_page(ctx: UgcRunContext, kind: str, query: str, cursor: int | None) -> SearchPage:
    scan = ctx.settings.scan
    if kind == "keyword":
        return await ctx.source.search(query, scan.lookback_days, scan.region, cursor)
    if kind == "hashtag":
        return await ctx.source.search_hashtag(query, scan.region, cursor)
    return await ctx.source.search_top(query, scan.lookback_days, scan.region, cursor)


async def run_collect(ctx: UgcRunContext) -> None:
    scan = ctx.settings.scan
    searches = ctx.niche.searches(scan.top_search)
    per_search_cap = math.ceil(scan.max_videos / len(searches))
    window_start = ctx.now - timedelta(days=scan.lookback_days)
    seen = set(ctx.store.run_video_ids(ctx.run_id))
    done = ctx.store.done_queries(ctx.run_id)
    found_before = ctx.store.query_counts(ctx.run_id)  # progress from an earlier, interrupted attempt
    lock = asyncio.Lock()

    async def run_search(key: str) -> None:
        kind, _, query = key.partition(":")
        found, cursor = found_before.get(key, 0), None
        for _ in range(scan.search_pages_per_query):
            if found >= per_search_cap or len(seen) >= scan.max_videos:
                return
            try:
                page = await fetch_page(ctx, kind, query, cursor)
            except APIError as exc:
                if kind != "top" or is_account_error(exc):
                    raise
                ctx.store.add_note(ctx.run_id, "TikTok's Top search was unavailable for some queries, so fewer "
                                               "slideshows were collected.")
                return
            ctx.record_scraper("collect", f"search_{kind}", page.credits)
            for video in page.videos:
                if found >= per_search_cap:
                    return
                if not (window_start <= video.posted_at <= ctx.now) or not is_english_or_unknown(video.language):
                    continue
                async with lock:
                    if video.id in seen:
                        ctx.store.add_run_video(ctx.run_id, video.id, key)
                        continue
                    if len(seen) >= scan.max_videos:
                        return
                    seen.add(video.id)
                    ctx.store.upsert_video(video)
                    ctx.store.add_run_video(ctx.run_id, video.id, key)
                found += 1
            if found >= per_search_cap or page.next_cursor is None:
                return
            cursor = page.next_cursor

    async def collect_search(key: str) -> None:
        await run_search(key)
        ctx.store.mark_query_done(ctx.run_id, key)

    todo = [key for key in searches if key not in done]
    await run_items(ctx, "collect", "scrapecreators", todo, collect_search, ctx.settings.concurrency.scraper,
                    total=len(searches))

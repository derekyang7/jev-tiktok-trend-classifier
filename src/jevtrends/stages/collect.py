"""Stage 1: keyword searches → deduplicated video records (spec §6.1)."""

import asyncio
import math
from datetime import timedelta

from jevtrends.budget import SEARCH_PAGES_PER_QUERY
from jevtrends.stages.context import RunContext, run_items


def is_english_or_unknown(language: str | None) -> bool:
    return not language or language in ("un", "und") or language.lower().startswith("en")


async def run_collect(ctx: RunContext) -> None:
    scan = ctx.settings.scan
    queries = ctx.niches.all_queries()
    per_query_cap = math.ceil(scan.max_videos / len(queries))
    window_start = ctx.now - timedelta(days=scan.lookback_days)
    seen = set(ctx.store.run_video_ids(ctx.run_id))
    done = ctx.store.done_queries(ctx.run_id)
    found_before = ctx.store.query_counts(ctx.run_id)  # progress from an earlier, interrupted attempt
    lock = asyncio.Lock()

    async def search_query(query: str) -> None:
        found, cursor = found_before.get(query, 0), None
        for _ in range(SEARCH_PAGES_PER_QUERY):
            if found >= per_query_cap or len(seen) >= scan.max_videos:
                return
            page = await ctx.source.search(query, scan.lookback_days, scan.region, cursor)
            ctx.record_scraper("collect", "search", page.credits)
            for video in page.videos:
                if found >= per_query_cap:
                    return
                if not (window_start <= video.posted_at <= ctx.now) or not is_english_or_unknown(video.language):
                    continue
                async with lock:
                    if video.id in seen:
                        ctx.store.add_run_video(ctx.run_id, video.id, query)
                        continue
                    if len(seen) >= scan.max_videos:
                        return
                    seen.add(video.id)
                    ctx.store.upsert_video(video)
                    ctx.store.add_run_video(ctx.run_id, video.id, query)
                found += 1
            if found >= per_query_cap or page.next_cursor is None:
                return
            cursor = page.next_cursor

    async def collect_query(query: str) -> None:
        await search_query(query)
        ctx.store.mark_query_done(ctx.run_id, query)

    todo = [query for query in queries if query not in done]
    await run_items(ctx, "collect", "scrapecreators", todo, collect_query, ctx.settings.concurrency.scraper,
                    total=len(queries))

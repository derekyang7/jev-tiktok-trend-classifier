"""Stage 3: transcripts for gate survivors, comments for the most-commented ones (spec §6.3)."""

from datetime import timedelta

from jevtrends.models import Enrichment
from jevtrends.stages.context import RunContext, run_items
from jevtrends.stages.gate import gate_survivors


async def run_enrich(ctx: RunContext) -> None:
    cfg = ctx.settings.enrich
    survivors = gate_survivors(ctx)
    videos = ctx.store.get_videos(survivors)

    def current(video_id: str) -> Enrichment:
        return ctx.store.get_enrichment(video_id) or Enrichment(video_id=video_id)

    async def fetch_transcript(video_id: str) -> None:
        result = await ctx.source.transcript(videos[video_id])
        ctx.record_scraper("enrich", "transcript", result.credits)
        ctx.store.upsert_enrichment(current(video_id).model_copy(update={
            "transcript": result.text,
            "transcript_status": "ok" if result.text else "missing",
            "transcript_fetched_at": ctx.now,
        }))

    need_transcripts = [v for v in survivors if current(v).transcript_status not in ("ok", "missing")]
    await run_items(ctx, "enrich", "scrapecreators", need_transcripts, fetch_transcript,
                    ctx.settings.concurrency.scraper, total=len(survivors))

    limit = ctx.limits.get("comments_top_videos", cfg.comments_top_videos)
    top = sorted(survivors, key=lambda v: videos[v].comment_count, reverse=True)[:limit]
    fresh_after = ctx.now - timedelta(days=cfg.comments_refresh_days)

    async def fetch_comments(video_id: str) -> None:
        result = await ctx.source.comments(videos[video_id], cfg.comments_per_video, cfg.comment_max_chars)
        ctx.record_scraper("enrich", "comments", result.credits)
        ctx.store.upsert_enrichment(current(video_id).model_copy(update={
            "comments": result.comments, "comments_fetched_at": ctx.now}))

    need_comments = [v for v in top
                     if current(v).comments_fetched_at is None or current(v).comments_fetched_at < fresh_after]
    await run_items(ctx, "enrich", "scrapecreators", need_comments, fetch_comments, ctx.settings.concurrency.scraper,
                    total=len(top))

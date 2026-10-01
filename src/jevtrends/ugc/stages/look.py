"""Stage 4: the vision model reads each survivor's cover frame or first slides (UGC spec §6.4)."""

from jevtrends.llm.client import ImagePart, LLMOutputError
from jevtrends.models import Enrichment, VisionRead
from jevtrends.stages.context import run_items
from jevtrends.stages.judge import truncate_words
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.images import prepare_image
from jevtrends.ugc.prompts import VISION_SYSTEM, VisionOut, vision_user_prompt
from jevtrends.ugc.stages.gate import gate_survivors

VISION_MAX_TOKENS = 1_000


def clean_text(text: str, max_chars: int) -> str:
    return " ".join((text or "").split())[:max_chars]


async def run_look(ctx: UgcRunContext) -> None:
    cfg = ctx.settings.vision
    if not cfg.enabled:
        ctx.store.add_note(ctx.run_id, "Vision was switched off for this run, so on-screen text was not read.")
        return
    survivors = gate_survivors(ctx)
    videos = ctx.store.get_videos(survivors)
    slides = max(1, ctx.limits.get("slides_per_post", cfg.slides_per_post))

    def needs_read(video_id: str) -> bool:
        enrichment = ctx.store.get_enrichment(video_id)
        return enrichment is None or enrichment.vision is None or enrichment.vision.status == "error"

    def save(video_id: str, read: VisionRead) -> None:
        current = ctx.store.get_enrichment(video_id) or Enrichment(video_id=video_id)
        ctx.store.upsert_enrichment(current.model_copy(update={"vision": read}))

    async def look_one(video_id: str) -> None:
        video = videos[video_id]
        urls = video.slide_urls[:slides] if video.is_slideshow else [url for url in [video.cover_url] if url]
        parts: list[ImagePart] = []
        for url in urls:
            data = await ctx.images.fetch(url, cfg.max_image_bytes)
            part = prepare_image(data, cfg.max_long_edge) if data else None
            if part:
                parts.append(part)
        if not parts:  # no link, an expired link, too large, or unreadable: not a failure
            save(video_id, VisionRead(status="no_image", model=ctx.vision.model))
            return
        try:
            result = await ctx.vision.complete_json(VISION_SYSTEM, vision_user_prompt(video.is_slideshow, len(parts)),
                                                    VisionOut, max_tokens=VISION_MAX_TOKENS, images=parts)
        except LLMOutputError as exc:
            ctx.record_vision("look", exc.input_tokens, exc.output_tokens, exc.cost_usd)
            save(video_id, VisionRead(status="error", model=ctx.vision.model))
            raise
        ctx.record_vision("look", result.input_tokens, result.output_tokens, result.cost_usd)
        save(video_id, VisionRead(on_screen_text=clean_text(result.parsed.on_screen_text, cfg.on_screen_text_max_chars),
                                  setup=truncate_words(result.parsed.setup, 25), status="ok", model=ctx.vision.model))

    todo = [video_id for video_id in survivors if needs_read(video_id)]
    await run_items(ctx, "look", "vision", todo, look_one, ctx.settings.concurrency.vision, total=len(survivors))

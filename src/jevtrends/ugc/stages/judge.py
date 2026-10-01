"""Stage 5: per-video Jev judgment, now with on-screen text: about the niche? promotional? (UGC spec §6.5)."""

from jevtrends.models import Enrichment, Video
from jevtrends.stages.context import run_items
from jevtrends.stages.judge import truncate_words
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.questions import PROMOTIONAL, relevant_question
from jevtrends.ugc.stages.gate import gate_survivors


def ugc_video_state(video: Video, enrichment: Enrichment | None, transcript_max_words: int) -> dict:
    enrichment = enrichment or Enrichment(video_id=video.id)
    vision = enrichment.vision
    return {
        "caption": video.caption or "",
        "hashtags": list(video.hashtags or []),
        "on_screen_text": vision.on_screen_text if vision else "",
        "setup": vision.setup if vision else "",
        "transcript": truncate_words(enrichment.transcript, transcript_max_words),
        "top_comments": [comment.text for comment in enrichment.comments or []],
    }


async def run_judge(ctx: UgcRunContext) -> None:
    questions = [relevant_question(ctx.niche), PROMOTIONAL]
    done = ctx.answers(questions[0])
    survivors = gate_survivors(ctx)
    todo = [video_id for video_id in survivors if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def judge_one(video_id: str) -> None:
        state = ugc_video_state(videos[video_id], ctx.store.get_enrichment(video_id),
                                ctx.settings.enrich.transcript_max_words)
        await ctx.ask_jev("judge", "video", video_id, state, questions)

    await run_items(ctx, "judge", "jev", todo, judge_one, ctx.settings.concurrency.jev, total=len(survivors))


def relevant_videos(ctx: UgcRunContext) -> list[str]:
    answers = ctx.answers(relevant_question(ctx.niche))
    threshold = ctx.settings.thresholds.relevant
    return [video_id for video_id in gate_survivors(ctx)
            if video_id in answers and float(answers[video_id].value) >= threshold]


def has_ad_flag(video: Video) -> bool:
    flags = video.ad_flags or {}
    return bool(flags.get("is_ad")) or bool(flags.get("is_paid_partnership")) or int(flags.get("branded_content_type") or 0) > 0


def promotional_videos(ctx: UgcRunContext) -> set[str]:
    """Jev says promotional, or TikTok itself flags it as an ad or paid partnership (spec §6.5)."""
    answers = ctx.answers(PROMOTIONAL)
    threshold = ctx.settings.thresholds.promotional
    survivors = gate_survivors(ctx)
    videos = ctx.store.get_videos(survivors)
    return {video_id for video_id in survivors if has_ad_flag(videos[video_id])
            or (video_id in answers and float(answers[video_id].value) >= threshold)}

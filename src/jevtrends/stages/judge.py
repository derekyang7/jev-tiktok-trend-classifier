"""Stage 4: per-video Jev judgment (spec §6.4)."""

from jevtrends.jev.questions import IS_SIGNAL, judge_questions
from jevtrends.models import Enrichment, Video
from jevtrends.stages.context import RunContext, run_items
from jevtrends.stages.gate import gate_survivors


def truncate_words(text: str | None, max_words: int) -> str:
    return " ".join((text or "").split()[:max_words])


def video_state(video: Video, enrichment: Enrichment | None, transcript_max_words: int) -> dict:
    enrichment = enrichment or Enrichment(video_id=video.id)
    return {
        "caption": video.caption or "",
        "hashtags": list(video.hashtags or []),
        "transcript": truncate_words(enrichment.transcript, transcript_max_words),
        "top_comments": [comment.text for comment in enrichment.comments or []],
        "creator_bio": video.author_bio or "",
    }


async def run_judge(ctx: RunContext) -> None:
    questions = judge_questions(ctx.niches.niches)
    done = ctx.answers(IS_SIGNAL)
    survivors = gate_survivors(ctx)
    todo = [video_id for video_id in survivors if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def judge_one(video_id: str) -> None:
        state = video_state(videos[video_id], ctx.store.get_enrichment(video_id),
                            ctx.settings.enrich.transcript_max_words)
        await ctx.ask_jev("judge", "video", video_id, state, questions)

    await run_items(ctx, "judge", "jev", todo, judge_one, ctx.settings.concurrency.jev, total=len(survivors))


def signal_videos(ctx: RunContext) -> list[str]:
    answers = ctx.answers(IS_SIGNAL)
    threshold = ctx.settings.thresholds.is_signal
    return [video_id for video_id in gate_survivors(ctx)
            if video_id in answers and answers[video_id].value >= threshold]

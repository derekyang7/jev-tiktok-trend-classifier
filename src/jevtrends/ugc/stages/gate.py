"""Stage 2: lenient Jev check that a video could be about the niche, from caption and hashtags (UGC spec §6.2)."""

from jevtrends.stages.context import run_items
from jevtrends.stages.gate import gate_state
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.questions import gate_question


async def run_gate(ctx: UgcRunContext) -> None:
    question = gate_question(ctx.niche)
    done = ctx.answers(question)
    all_ids = ctx.store.run_video_ids(ctx.run_id)
    todo = [video_id for video_id in all_ids if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def judge_one(video_id: str) -> None:
        await ctx.ask_jev("gate", "video", video_id, gate_state(videos[video_id]), [question])

    await run_items(ctx, "gate", "jev", todo, judge_one, ctx.settings.concurrency.jev, total=len(all_ids))


def gate_survivors(ctx: UgcRunContext) -> list[str]:
    answers = ctx.answers(gate_question(ctx.niche))
    keep = ctx.settings.thresholds.gate_keep
    return [video_id for video_id in ctx.store.run_video_ids(ctx.run_id)
            if video_id in answers and float(answers[video_id].value) >= keep]

"""Stage 2: lenient Jev relevance check on caption and hashtags (spec §6.2)."""

from jevtrends.core.context import gate_state, run_items
from jevtrends.opportunities.context import RunContext
from jevtrends.opportunities.questions import MAYBE_SIGNAL


async def run_gate(ctx: RunContext) -> None:
    done = ctx.answers(MAYBE_SIGNAL)
    all_ids = ctx.store.run_video_ids(ctx.run_id)
    todo = [video_id for video_id in all_ids if video_id not in done]
    videos = ctx.store.get_videos(todo)

    async def judge_one(video_id: str) -> None:
        await ctx.ask_jev("gate", "video", video_id, gate_state(videos[video_id]), [MAYBE_SIGNAL])

    await run_items(ctx, "gate", "jev", todo, judge_one, ctx.settings.concurrency.jev, total=len(all_ids))


def gate_survivors(ctx: RunContext) -> list[str]:
    answers = ctx.answers(MAYBE_SIGNAL)
    keep = ctx.settings.thresholds.gate_keep
    return [video_id for video_id in ctx.store.run_video_ids(ctx.run_id)
            if video_id in answers and answers[video_id].value >= keep]

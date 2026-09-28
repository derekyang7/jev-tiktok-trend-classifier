"""Stage 5: the LLM proposes candidate trends from one digest line per signal video (spec §6.5)."""

import math

from jevtrends.jev.questions import IS_PROMOTIONAL, IS_SIGNAL, SIGNAL_TYPE, niche_question
from jevtrends.llm.client import LLMOutputError
from jevtrends.llm.prompts import DISCOVER_SYSTEM, DiscoverOut, discover_user_prompt
from jevtrends.models import Enrichment, Trend, Video
from jevtrends.stages.context import RunContext, StageFailed
from jevtrends.stages.judge import signal_videos

DISCOVER_MAX_TOKENS = 32_000


def clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def digest_line(short_id: str, video: Video, enrichment: Enrichment | None, signal_type: str,
                niches: list[str], promotional: bool) -> str:
    transcript = " ".join(((enrichment.transcript if enrichment else None) or "").split()[:40])
    comments = (enrichment.comments if enrichment else None) or []
    top_comment = clip(comments[0].text, 100) if comments else ""
    return (f'[{short_id}] @{video.author_handle} | {signal_type} | niches: {", ".join(niches) or "none"} | '
            f'promo: {"yes" if promotional else "no"} | "{clip(video.caption, 150)}" | '
            f'transcript: "{transcript}" | top comment: "{top_comment}"')


def clean_proposals(out: DiscoverOut, short_to_video: dict[str, str], max_candidates: int) -> list[Trend]:
    trends: list[Trend] = []
    for proposal in out.trends[:max_candidates]:
        examples = [short_to_video[s.strip()] for s in proposal.example_video_ids if s.strip() in short_to_video]
        trends.append(Trend(trend_id=f"t{len(trends) + 1:02d}", name=proposal.name[:80], kind=proposal.kind,
                            definition=proposal.definition, includes=proposal.includes[:3],
                            excludes=proposal.excludes[:3], example_video_ids=list(dict.fromkeys(examples))))
    return trends


async def run_discover(ctx: RunContext) -> None:
    if ctx.store.list_trends(ctx.run_id):
        return  # already proposed in an earlier attempt of this run
    signals = signal_videos(ctx)
    if not signals:
        ctx.store.add_note(ctx.run_id, "No signal videos, so no trends were proposed.")
        return
    thresholds = ctx.settings.thresholds
    is_signal, types, promo = ctx.answers(IS_SIGNAL), ctx.answers(SIGNAL_TYPE), ctx.answers(IS_PROMOTIONAL)
    niche_answers = {niche.id: ctx.answers(niche_question(niche)) for niche in ctx.niches.niches}
    videos = ctx.store.get_videos(signals)
    ranked = sorted(signals, key=lambda v: is_signal[v].value * math.log1p(videos[v].views), reverse=True)

    lines: list[str] = []
    short_to_video: dict[str, str] = {}
    char_budget, used = ctx.settings.trends.discover_max_digest_tokens * 4, 0
    for index, video_id in enumerate(ranked, start=1):
        short_id = f"v{index:03d}"
        niches = [niche_id for niche_id, answers in niche_answers.items()
                  if video_id in answers and answers[video_id].value >= thresholds.niche_member]
        line = digest_line(short_id, videos[video_id], ctx.store.get_enrichment(video_id),
                           str(types[video_id].value) if video_id in types else "other", niches,
                           video_id in promo and promo[video_id].value >= 0.5)
        if used + len(line) > char_budget:
            break
        used += len(line)
        lines.append(line)
        short_to_video[short_id] = video_id
        ctx.store.set_short_id(ctx.run_id, video_id, short_id)

    max_candidates = ctx.settings.trends.max_candidates

    def validate(out: DiscoverOut) -> list[str]:
        if clean_proposals(out, short_to_video, max_candidates):
            return []
        return ["No valid trends. Propose 20-60 trends with the fields described."]

    try:
        result = await ctx.llm.complete_json(DISCOVER_SYSTEM, discover_user_prompt(lines), DiscoverOut,
                                             max_tokens=DISCOVER_MAX_TOKENS, validate=validate)
    except LLMOutputError as exc:
        ctx.record_llm("discover", exc.input_tokens, exc.output_tokens, exc.cost_usd)
        raise StageFailed(f"discover: invalid LLM output after one retry: {exc}") from exc
    ctx.record_llm("discover", result.input_tokens, result.output_tokens, result.cost_usd)
    for trend in clean_proposals(result.parsed, short_to_video, max_candidates):
        ctx.store.upsert_trend(ctx.run_id, trend)

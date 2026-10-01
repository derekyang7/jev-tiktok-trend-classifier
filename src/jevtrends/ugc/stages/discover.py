"""Stage 7: one LLM call proposes formats, hooks, topics and needs, plus a usage note per sound (UGC spec §6.7)."""

import math

from jevtrends.llm.client import LLMOutputError
from jevtrends.models import Enrichment, Video
from jevtrends.stages.context import StageFailed
from jevtrends.stages.discover import clip
from jevtrends.ugc import scoring
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.models import LLM_FACETS, FacetTrend, SoundCandidate
from jevtrends.ugc.prompts import DiscoverOut, discover_system, discover_user_prompt
from jevtrends.ugc.questions import relevant_question
from jevtrends.ugc.stages.judge import promotional_videos, relevant_videos

DISCOVER_MAX_TOKENS = 40_000
PREFIX = {"format": "f", "hook": "h", "topic": "t", "need": "n"}


def first_words(text: str | None, n: int) -> str:
    return " ".join((text or "").split()[:n])


def video_digest_line(short_id: str, video: Video, enrichment: Enrichment | None, promotional: bool) -> str:
    enrichment = enrichment or Enrichment(video_id=video.id)
    vision, comments, sound = enrichment.vision, enrichment.comments or [], video.sound_info
    length = (f"slideshow {len(video.slide_urls)}" if video.is_slideshow
              else f"video {round((video.duration_ms or 0) / 1000)}s")
    edits = ", ".join(dict.fromkeys([*video.editing_features, *video.anchors])) or "none"
    parts = [f"[{short_id}] @{video.author_handle}", length, f"edits: {edits}",
             f"promo: {'yes' if promotional else 'no'}",
             f'on-screen: "{clip(vision.on_screen_text if vision else "", 150)}"',
             f'setup: "{clip(vision.setup if vision else "", 120)}"']
    if not video.is_slideshow:
        parts.append(f'speech: "{first_words(enrichment.transcript, 25)}"')
    parts += [f'caption: "{clip(video.caption, 120)}"',
              f'sound: "{clip(sound.title if sound else video.sound, 60)}"' + (" (original)" if sound and sound.is_original else ""),
              f'top comment: "{clip(comments[0].text, 80) if comments else ""}"']
    return " | ".join(parts)


def sound_digest_line(trend_id: str, sound: SoundCandidate, captions: list[str], sampled: int, niche_uses: int) -> str:
    rank = f"popular #{sound.popular_rank}" if sound.popular_rank else "from the niche sample"
    uses = (f"niche uses: {niche_uses} of {sampled} sampled" if sampled
            else f"niche uses: {niche_uses} videos in the sample")
    quoted = " / ".join(f'"{clip(caption, 80)}"' for caption in captions[:8]) or "none"
    return (f'[{trend_id}] "{clip(sound.title, 80)}" by {sound.author or "unknown"} | {rank} | '
            f"business use: {sound.business_use} | {uses} | captions: {quoted}")


def clean_candidates(out: DiscoverOut, short_to_video: dict[str, str], high: int) -> list[FacetTrend]:
    trends: list[FacetTrend] = []
    for facet, items in (("format", out.formats), ("hook", out.hooks), ("topic", out.topics), ("need", out.needs)):
        kept = 0
        for item in items:
            if kept >= high:
                break
            if facet == "hook" and not item.template.strip():
                continue
            kept += 1
            examples = [short_to_video[s.strip()] for s in item.example_video_ids if s.strip() in short_to_video]
            trends.append(FacetTrend(trend_id=f"{PREFIX[facet]}{kept:02d}", facet=facet, name=item.name[:80],
                                     definition=item.definition, includes=item.includes[:3],
                                     excludes=item.excludes[:3],
                                     template=item.template.strip()[:100] if facet == "hook" else "",
                                     example_video_ids=list(dict.fromkeys(examples))))
    return trends


def sound_lines(ctx: UgcRunContext, relevant: list[str]) -> list[str]:
    sounds = {sound.sound_id: sound for sound in ctx.store.list_sounds(ctx.run_id)}
    samples = ctx.store.sound_samples(ctx.run_id)
    corpus = ctx.store.get_videos(relevant)
    threshold = ctx.settings.thresholds.relevant
    lines = []
    for trend in ctx.store.list_facet_trends(ctx.run_id, facet="sound"):
        sound = sounds[trend.sound_id]
        sampled = samples.get(sound.sound_id, {})
        corpus_uses = [v for v in relevant if corpus[v].sound_info and corpus[v].sound_info.id == sound.sound_id]
        caption_ids = list(sampled)[:8] or corpus_uses[:8]
        captions = [video.caption for video in ctx.store.get_videos(caption_ids).values()]
        niche_uses = (sum(1 for p in sampled.values() if p is not None and p >= threshold) if sampled
                      else len(corpus_uses))
        lines.append(sound_digest_line(trend.trend_id, sound, captions, len(sampled), niche_uses))
    return lines


async def run_discover(ctx: UgcRunContext) -> None:
    if any(trend.facet in LLM_FACETS for trend in ctx.store.list_facet_trends(ctx.run_id)):
        return  # proposed in an earlier attempt of this run
    relevant = relevant_videos(ctx)
    if not relevant:
        ctx.store.add_note(ctx.run_id, "No relevant videos, so no formats, hooks, topics or needs were proposed.")
        return
    cfg = ctx.settings.trends
    relevance = ctx.answers(relevant_question(ctx.niche))
    promotional = promotional_videos(ctx)
    videos = ctx.store.get_videos(relevant)
    ranked = sorted(relevant, key=lambda v: float(relevance[v].value) * math.log1p(videos[v].views), reverse=True)
    lines: list[str] = []
    short_to_video: dict[str, str] = {}
    char_budget, used = cfg.discover_max_digest_tokens * 4, 0
    for index, video_id in enumerate(ranked, start=1):
        short_id = f"v{index:03d}"
        line = video_digest_line(short_id, videos[video_id], ctx.store.get_enrichment(video_id),
                                 video_id in promotional)
        if used + len(line) > char_budget:
            break
        used += len(line)
        lines.append(line)
        short_to_video[short_id] = video_id
        ctx.store.set_short_id(ctx.run_id, video_id, short_id)
    low, high = scoring.facet_count_range(len(lines), cfg.videos_per_candidate, cfg.max_candidates_per_facet)

    def validate(out: DiscoverOut) -> list[str]:
        if clean_candidates(out, short_to_video, high):
            return []
        return [f"No valid candidates. Propose {low}-{high} formats and {low}-{high} hooks with every field "
                "described, including a template for each hook."]

    try:
        result = await ctx.llm.complete_json(discover_system(low, high),
                                             discover_user_prompt(lines, sound_lines(ctx, relevant)), DiscoverOut,
                                             max_tokens=DISCOVER_MAX_TOKENS, validate=validate)
    except LLMOutputError as exc:
        ctx.record_llm("discover", exc.input_tokens, exc.output_tokens, exc.cost_usd)
        raise StageFailed(f"discover: invalid LLM output after one retry: {exc}") from exc
    ctx.record_llm("discover", result.input_tokens, result.output_tokens, result.cost_usd)
    for trend in clean_candidates(result.parsed, short_to_video, high):
        ctx.store.upsert_facet_trend(ctx.run_id, trend)
    notes = {note.sound_id.strip(): note.usage.strip()[:120] for note in result.parsed.sound_notes}
    for trend in ctx.store.list_facet_trends(ctx.run_id, facet="sound"):
        if notes.get(trend.trend_id):
            ctx.store.upsert_facet_trend(ctx.run_id, trend.model_copy(update={"usage": notes[trend.trend_id]}))

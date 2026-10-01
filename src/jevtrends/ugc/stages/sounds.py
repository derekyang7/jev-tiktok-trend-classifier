"""Stage 6: sound candidates from TikTok's popular songs and the sample, checked against the niche (UGC spec §6.6)."""

from collections import Counter
from itertools import zip_longest

from jevtrends.http import APIError
from jevtrends.sources.base import Song
from jevtrends.stages.context import run_items
from jevtrends.stages.gate import gate_state
from jevtrends.ugc import scoring
from jevtrends.ugc.context import UgcRunContext, is_account_error
from jevtrends.ugc.models import FacetTrend, SoundCandidate
from jevtrends.ugc.questions import sound_relevant_question
from jevtrends.ugc.stages.judge import relevant_videos


async def fetch_popular(ctx: UgcRunContext, commercial_only: bool) -> list[Song]:
    cfg = ctx.settings.sounds
    songs: list[Song] = []
    page = 1
    while len(songs) < cfg.popular_count:
        result = await ctx.source.popular_songs(cfg.popular_period_days, ctx.settings.scan.region, page,
                                                commercial_only)
        ctx.record_scraper("sounds", "songs_popular", result.credits)
        songs += [song for song in result.songs if song.sound_id]
        if not result.has_more:
            break
        page += 1
    return songs[:cfg.popular_count]


def interleave(first: list[Song], second: list[Song], limit: int) -> list[Song]:
    """Alternates two ranked lists without repeats, so popular and approved-only songs are both represented."""
    merged: list[Song] = []
    seen: set[str] = set()
    for pair in zip_longest(first, second):
        for song in pair:
            if song is not None and song.sound_id not in seen and len(merged) < limit:
                merged.append(song)
                seen.add(song.sound_id)
    return merged


async def popular_candidates(ctx: UgcRunContext) -> tuple[list[Song], set[str]]:
    """Popular songs and the ids on the approved-for-business list; ([], set()) if the list is unavailable."""
    try:
        popular = await fetch_popular(ctx, commercial_only=False)
        if not popular or any(song.commercial is not None for song in popular):
            return popular, set()  # per-song flags already label every song
        approved = await fetch_popular(ctx, commercial_only=True)
    except APIError as exc:
        if is_account_error(exc):
            raise
        ctx.store.add_note(ctx.run_id, f"TikTok's popular-songs list was unavailable ({exc}), so sounds come only "
                                       "from the sample.")
        return [], set()
    approved_ids = {song.sound_id for song in approved}
    if not approved_ids or approved_ids == {song.sound_id for song in popular}:
        ctx.store.add_note(ctx.run_id, "TikTok's business-use filter had no effect, so popular sounds' licensing "
                                       "comes from other sources.")
        return popular, set()
    return interleave(popular, approved, ctx.settings.sounds.popular_count), approved_ids


def match_rounded_ids(ctx: UgcRunContext, songs: list[Song]) -> None:
    """Top search rounds sound ids to doubles: swap each for an exact id from this run that rounds the same."""
    corpus = ctx.store.get_videos(relevant_videos(ctx))
    known = [song.sound_id for song in songs] + [video.sound_info.id for video in corpus.values()
                                                 if video.sound_info and not video.sound_info.id_rounded]
    exact = {float(sound_id): sound_id for sound_id in known if sound_id.isdigit()}
    for video in corpus.values():
        info = video.sound_info
        if info and info.id_rounded and info.id.isdigit() and float(info.id) in exact:
            ctx.store.upsert_video(video.model_copy(update={"sound_info": info.model_copy(
                update={"id": exact[float(info.id)], "id_rounded": False})}))


def most_viewed_use(corpus: dict, sound_id: str) -> str:
    uses = [video for video in corpus.values() if video.sound_info and video.sound_info.id == sound_id]
    return max(uses, key=lambda video: video.views or 0).url


async def build_candidates(ctx: UgcRunContext) -> list[SoundCandidate]:
    songs, approved_ids = await popular_candidates(ctx)
    match_rounded_ids(ctx, songs)
    corpus = ctx.store.get_videos(relevant_videos(ctx))
    uses = Counter(video.sound_info.id for video in corpus.values() if video.sound_info)
    niche_ids = {sound_id for sound_id, count in uses.items() if count >= ctx.settings.sounds.niche_min_videos}
    candidates = [SoundCandidate(sound_id=song.sound_id, title=song.title, author=song.author,
                                 source=["popular", "niche"] if song.sound_id in niche_ids else ["popular"],
                                 popular_rank=song.rank or None, link=song.link, trend=song.trend,
                                 listed_commercial=song.commercial, in_business_list=song.sound_id in approved_ids)
                  for song in songs]
    listed = {candidate.sound_id for candidate in candidates}
    info = {video.sound_info.id: video.sound_info for video in corpus.values() if video.sound_info}
    for sound_id, _ in uses.most_common():
        if sound_id in niche_ids and sound_id not in listed:
            rounded = info[sound_id].id_rounded  # no sound page to link to, so link a video that uses it
            candidates.append(SoundCandidate(sound_id=sound_id, title=info[sound_id].title,
                                             author=info[sound_id].author, source=["niche"],
                                             use_count=info[sound_id].use_count,
                                             link=most_viewed_use(corpus, sound_id) if rounded else ""))
    if any(sound_id in info and info[sound_id].id_rounded for sound_id in (c.sound_id for c in candidates)):
        ctx.store.add_note(ctx.run_id, "Top search rounds sound ids, so sounds found only there link to a video "
                                       "that uses them instead of the sound's page.")
    return candidates


async def run_sounds(ctx: UgcRunContext) -> None:
    cfg = ctx.settings.sounds
    if not ctx.store.list_sounds(ctx.run_id):
        for index, candidate in enumerate(await build_candidates(ctx), start=1):
            ctx.store.upsert_sound(ctx.run_id, candidate)
            ctx.store.upsert_facet_trend(ctx.run_id, FacetTrend(
                trend_id=f"s{index:02d}", facet="sound", name=candidate.title or "Untitled sound",
                sound_id=candidate.sound_id, status="kept"))
    sounds = ctx.store.list_sounds(ctx.run_id)
    to_sample = [sound for sound in sounds if "popular" in sound.source and not sound.sampled]

    async def sample_one(sound: SoundCandidate) -> None:
        cursor, fetched = None, []
        try:
            for _ in range(cfg.sample_pages):
                page = await ctx.source.song_videos(sound.sound_id, cursor)
                ctx.record_scraper("sounds", "song_videos", page.credits)
                fetched += page.videos
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        except APIError as exc:
            if is_account_error(exc):
                raise
            ctx.store.add_note(ctx.run_id, "Some song pages were unavailable, so those sounds have no niche sample.")
        for video in fetched:
            ctx.store.upsert_video(video)
            ctx.store.upsert_sound_sample(ctx.run_id, sound.sound_id, video.id, None)
        ctx.store.upsert_sound(ctx.run_id, sound.model_copy(update={"sampled": True}))

    await run_items(ctx, "sounds", "scrapecreators", to_sample, sample_one, ctx.settings.concurrency.scraper,
                    total=len(to_sample))

    question = sound_relevant_question(ctx.niche)
    samples = ctx.store.sound_samples(ctx.run_id)
    sample_ids = list(dict.fromkeys(video_id for videos in samples.values() for video_id in videos))
    done = ctx.answers(question)
    todo = [video_id for video_id in sample_ids if video_id not in done]
    sample_videos = ctx.store.get_videos(todo)

    async def check_one(video_id: str) -> None:
        await ctx.ask_jev("sounds", "video", video_id, gate_state(sample_videos[video_id]), [question])

    await run_items(ctx, "sounds", "jev", todo, check_one, ctx.settings.concurrency.jev, total=len(sample_ids))
    finalize_sounds(ctx)


def finalize_sounds(ctx: UgcRunContext) -> None:
    """Niche creators and share, business-use labels, and corpus memberships for every sound (spec §6.6)."""
    threshold = ctx.settings.thresholds.relevant
    answers = ctx.answers(sound_relevant_question(ctx.niche))
    samples = ctx.store.sound_samples(ctx.run_id)
    corpus = ctx.store.get_videos(relevant_videos(ctx))
    sampled_videos = ctx.store.get_videos(list(dict.fromkeys(v for videos in samples.values() for v in videos)))
    trends = {trend.sound_id: trend for trend in ctx.store.list_facet_trends(ctx.run_id, facet="sound")}
    member_rows: list[tuple[str, str, float]] = []
    labels: Counter = Counter()
    for sound in ctx.store.list_sounds(ctx.run_id):
        sound_id = sound.sound_id
        corpus_uses = [v for v, video in corpus.items() if video.sound_info and video.sound_info.id == sound_id]
        judged = {v: float(answers[v].value) for v in samples.get(sound_id, {}) if v in answers}
        for video_id, p in judged.items():
            ctx.store.upsert_sound_sample(ctx.run_id, sound_id, video_id, p)
        niche_samples = [v for v, p in judged.items() if p >= threshold]
        creators = ({corpus[v].author_id for v in corpus_uses}
                    | {sampled_videos[v].author_id for v in niche_samples})
        infos = [video.sound_info for video in [*(corpus[v] for v in corpus_uses),
                                                *(sampled_videos[v] for v in samples.get(sound_id, {}))]
                 if video.sound_info and video.sound_info.id == sound_id]
        label, source = scoring.business_use(sound.listed_commercial, sound.in_business_list,
                                             infos[0].licensing if infos else {},
                                             ctx.settings.sounds.trusted_licensing_flag)
        labels[label] += 1
        ctx.store.upsert_sound(ctx.run_id, sound.model_copy(update={
            "niche_creators": len(creators), "niche_share": len(niche_samples) / len(judged) if judged else None,
            "business_use": label, "business_use_source": source,
            "use_count": max([sound.use_count, *(info.use_count for info in infos)])}))
        member_rows += [(trends[sound_id].trend_id, v, 1.0) for v in corpus_uses]
    ctx.store.replace_members(ctx.run_id, [trend.trend_id for trend in trends.values()], member_rows)
    if trends and labels["unknown"] == sum(labels.values()):
        ctx.store.add_note(ctx.run_id, "No sound's business use could be verified, so briefs suggest original audio "
                                       "or a sound from TikTok's Commercial Music Library.")

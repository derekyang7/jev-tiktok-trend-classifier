"""Stage 11: the Markdown report (UGC spec §6.11)."""

import re
from collections import Counter
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from jevtrends import scoring as base
from jevtrends.jev.questions import NONE_OF_THESE
from jevtrends.models import Video
from jevtrends.stages.judge import truncate_words
from jevtrends.ugc import scoring
from jevtrends.ugc.context import UgcRunContext, ugc_report_context
from jevtrends.ugc.models import LLM_FACETS, FacetTrend, SoundCandidate
from jevtrends.ugc.questions import relevant_question
from jevtrends.ugc.stages.assign import assign_questions, facet_groups
from jevtrends.ugc.stages.gate import gate_survivors
from jevtrends.ugc.stages.judge import promotional_videos, relevant_videos
from jevtrends.ugc.stages.score import evidence_ids
from jevtrends.ugc.store import UgcStore

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
FACET_LABELS = {"format": "Format", "hook": "Hook", "sound": "Sound", "topic": "Topic", "need": "Need"}
SECTIONS = [("Formats and hooks", ("format", "hook")), ("Sounds", ("sound",)), ("Topics and memes", ("topic",)),
            ("Needs and angles", ("need",))]
SEARCH_TYPES = ("keyword", "hashtag", "top")  # funnel order; stored rows come back in video-id order


def sound_url(sound: SoundCandidate) -> str:
    """The sound's TikTok page: the popular list's link, or TikTok's music URL built from title and id."""
    if sound.link:
        return sound.link
    slug = re.sub(r"[^a-z0-9]+", "-", sound.title.lower()).strip("-") or "sound"
    return f"https://www.tiktok.com/music/{slug}-{sound.sound_id}"


def sound_pick_text(brief: dict | None, trends: dict[str, FacetTrend], sounds: dict[str, SoundCandidate]) -> str:
    pick = (brief or {}).get("sound") or {}
    trend = trends.get(pick.get("sound_id", ""))
    sound = sounds.get(trend.sound_id) if trend and trend.sound_id else None
    label = f'"{sound.title}" by {sound.author or "unknown"}' if sound else "Original audio"
    return f"{label} ({pick['why']})" if pick.get("why") else label


def evidence_rows(ctx: UgcRunContext, trend: FacetTrend, brief: dict | None, members: dict, samples: dict,
                  videos: dict[str, Video], promotional: set[str], limit: int = 5) -> list[dict]:
    """Brief-cited videos first, then the trend's strongest evidence, up to `limit`."""
    why = {ref["video_id"]: ref.get("why", "") for ref in (brief or {}).get("evidence", [])}
    ids = [video_id for video_id in why if video_id in videos]
    for video_id in evidence_ids(trend, members, samples, videos, ctx.settings.trends.evidence_per_trend,
                                 ctx.settings.thresholds.relevant):
        if video_id not in ids:
            ids.append(video_id)
    rows = []
    for video_id in ids[:limit]:
        video, enrichment = videos[video_id], ctx.store.get_enrichment(video_id)
        vision = enrichment.vision if enrichment else None
        comments = (enrichment.comments if enrichment else None) or []
        snippet = (truncate_words(enrichment.transcript if enrichment else None, 30)
                   or (vision.setup if vision else "") or truncate_words(video.caption, 30))
        rows.append({"url": video.url, "handle": video.author_handle, "views": video.views,
                     "reach": scoring.reach(video.views, video.author_followers, ctx.settings.trends.follower_floor),
                     "saves": video.saves, "shares": video.shares, "posted": video.posted_at.date().isoformat(),
                     "promotional": video_id in promotional, "why": why.get(video_id, ""),
                     "on_screen": vision.on_screen_text if vision else "", "snippet": snippet,
                     "comment": " ".join(comments[0].text.split()) if comments else ""})
    return rows


def build_ugc_report_data(store: UgcStore, run_id: int, weights: dict[str, float] | None = None) -> dict:
    ctx = ugc_report_context(store, run_id)
    run = store.get_run(run_id)
    settings = ctx.settings
    trends = {t.trend_id: t for t in store.list_facet_trends(run_id)}
    scores = store.list_ugc_scores(run_id)
    if weights:
        scores = scoring.rank_ugc(scores, weights)
    briefs = store.list_ugc_briefs(run_id)
    members, samples = store.facet_members(run_id), store.sound_samples(run_id)
    sounds = {s.sound_id: s for s in store.list_sounds(run_id)}
    survivors, relevant, promotional = gate_survivors(ctx), relevant_videos(ctx), promotional_videos(ctx)
    videos = store.get_videos(list(dict.fromkeys([*relevant, *(v for s in samples.values() for v in s)])))
    claims = {claim.id: claim.text for claim in ctx.product.claims_allowed} if ctx.product else {}

    entries = []
    for score in scores:
        trend = trends[score.trend_id]
        row = briefs.get(score.trend_id, {})
        brief = row.get("brief")
        sound = sounds.get(trend.sound_id) if trend.sound_id else None
        entries.append({
            "score": score, "trend": trend, "facet_label": FACET_LABELS[trend.facet],
            "sound": sound, "sound_url": sound_url(sound) if sound else "",
            "brief": brief, "brief_status": row.get("status"),
            "brief_pairs": [trends[p].name for p in (brief or {}).get("pairs_with", []) if p in trends],
            "claims": [f"{c}: {claims[c]}" for c in (brief or {}).get("claims_used", []) if c in claims],
            "sound_pick": sound_pick_text(brief, trends, sounds),
            "evidence": evidence_rows(ctx, trend, brief, members, samples, videos, promotional) if brief else [],
        })
    sections = []
    for title, facets in SECTIONS:
        within = [e for e in entries if e["trend"].facet in facets]
        briefed = sorted((e for e in within if e["brief"]),
                         key=lambda e: (facets.index(e["trend"].facet), e["score"].rank_overall))
        sections.append({"title": title, "is_sounds": facets == ("sound",), "briefed": briefed,
                         "others": [e for e in within if not e["brief"]],
                         "sound_rows": within[:settings.sounds.report_count]})

    found: Counter = Counter()
    for key, count in store.query_counts(run_id).items():
        found[key.partition(":")[0]] += count
    by_type = {kind: found[kind] for kind in SEARCH_TYPES if found[kind]}
    by_type.update({kind: n for kind, n in found.items() if kind not in SEARCH_TYPES})
    enrichments = {video_id: store.get_enrichment(video_id) for video_id in survivors}
    vision = Counter(e.vision.status if e and e.vision else "not read" for e in enrichments.values())
    images_read = sum(1 for v in relevant if enrichments[v] and enrichments[v].vision
                      and enrichments[v].vision.status == "ok")  # look runs before judge, on every survivor
    transcripts = Counter(e.transcript_status if e and e.transcript_status else "not fetched"
                          for e in enrichments.values())
    facet_counts = {facet: {"proposed": sum(1 for t in trends.values() if t.facet == facet),
                            "kept": sum(1 for t in trends.values() if t.facet == facet and t.status == "kept")}
                    for facet in LLM_FACETS}
    none_rates = {}
    for question in assign_questions(facet_groups(ctx)):
        top = base.top_choices({v: a.probabilities or {} for v, a in ctx.answers(question).items()})
        none_rates[question.key] = base.none_rate(top, NONE_OF_THESE) if top else None
    low, high = settings.thresholds.borderline
    relevance = ctx.answers(relevant_question(ctx.niche))
    return {
        "run_id": run_id, "date": run["started_at"].date().isoformat(), "status": run["status"],
        "niche_name": ctx.niche.name, "product_name": ctx.product.name if ctx.product else "",
        "lookback_days": settings.scan.lookback_days,
        "funnel": {"collected": len(store.run_video_ids(run_id)), "by_type": by_type,
                   "passed": len(survivors), "relevant": len(relevant), "images_read": images_read,
                   "facets": facet_counts, "sounds": len(sounds)},
        "cost": store.spend_by_provider(run_id), "total_cost": store.total_spend(run_id), "notes": store.notes(run_id),
        "top_picks": entries[:settings.briefs.top_picks], "sections": sections,
        "diagnostics": {
            "none_rates": none_rates,
            "flagged": [t.name for t in trends.values() if t.facet in LLM_FACETS and t.status == "kept"
                        and t.self_check_agreement is not None
                        and t.self_check_agreement < settings.trends.self_check_min_agreement],
            "borderline": sum(1 for v in survivors if v in relevance and low <= float(relevance[v].value) <= high),
            "vision": dict(vision), "transcripts": dict(transcripts), "failures": store.failures_by_stage(run_id),
            "licensing": dict(Counter(s.business_use for s in sounds.values())),
            "licensing_sources": sorted({s.business_use_source for s in sounds.values() if s.business_use_source}),
            "momentum_recent_days": settings.scan.lookback_days * settings.trends.momentum_recent_fraction,
            "weights": weights or settings.ranking.weights},
        "settings_yaml": yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
    }


def render_ugc_report(store: UgcStore, run_id: int, weights: dict[str, float] | None = None) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True,
                      keep_trailing_newline=True)
    env.filters["pct"] = lambda x: f"{x:.0%}"
    env.filters["f2"] = lambda x: f"{x:.2f}"
    env.filters["x1"] = lambda x: f"{x:.1f}×"
    env.filters["cell"] = lambda x: " ".join(str(x or "").split()).replace("|", "\\|")
    return env.get_template("report.md.j2").render(**build_ugc_report_data(store, run_id, weights))


def write_ugc_report(store: UgcStore, run_id: int, reports_dir: Path, weights: dict[str, float] | None = None) -> Path:
    run = store.get_run(run_id)
    path = Path(reports_dir) / f"{run['started_at'].date().isoformat()}-{run['niche'].id}-run-{run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ugc_report(store, run_id, weights))
    return path

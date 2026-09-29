"""Stage 9: Markdown report (spec §6.9)."""

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from jevtrends import scoring
from jevtrends.jev.questions import IS_SIGNAL, NONE_OF_THESE, assign_question, niche_question
from jevtrends.stages.context import RunContext
from jevtrends.stages.gate import gate_survivors
from jevtrends.stages.judge import signal_videos, truncate_words
from jevtrends.stages.score import evidence_set
from jevtrends.store import Store

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def report_context(store: Store, run_id: int) -> RunContext:
    """Read-only context for building reports; no API clients are needed."""
    run = store.get_run(run_id)
    return RunContext(run_id=run_id, store=store, settings=run["settings"], niches=run["niches"],
                      source=None, jev=None, llm=None, budget=None, now=run["started_at"])


def evidence_rows(ctx: RunContext, brief: dict | None, members: dict[str, float], limit: int = 5) -> list[dict]:
    """Brief-cited videos first, then the strongest members, up to `limit`."""
    why = {ref["video_id"]: ref.get("why", "") for ref in (brief or {}).get("evidence", [])}
    ids = list(why)
    for video_id in evidence_set(members, ctx.settings.trends.evidence_per_trend):
        if video_id not in ids:
            ids.append(video_id)
    rows = []
    for video_id in ids[:limit]:
        video, enrichment = ctx.store.get_video(video_id), ctx.store.get_enrichment(video_id)
        comments = (enrichment.comments if enrichment else None) or []
        rows.append({
            "url": video.url, "handle": video.author_handle, "views": video.views,
            "posted": video.posted_at.date().isoformat(), "p": members.get(video_id, 0.0), "why": why.get(video_id, ""),
            "snippet": truncate_words(enrichment.transcript if enrichment else None, 30) or truncate_words(video.caption, 30),
            "comment": " ".join(comments[0].text.split()) if comments else "",
        })
    return rows


def build_report_data(store: Store, run_id: int, weights: dict[str, float] | None = None) -> dict:
    ctx = report_context(store, run_id)
    run = store.get_run(run_id)
    settings, niches = ctx.settings, ctx.niches
    names = {niche.id: niche.name for niche in niches.niches}
    trends = {t.trend_id: t for t in store.list_trends(run_id)}
    kept = [t for t in trends.values() if t.status == "kept"]
    scores = store.list_trend_scores(run_id)
    if weights:
        scores = scoring.rank_scores(scores, weights)
    briefs = store.list_briefs(run_id)
    members = store.trend_members(run_id)

    entries = []
    for score in scores:
        brief_row = briefs.get(score.trend_id, {})
        brief = brief_row.get("brief")
        entries.append({
            "score": score, "trend": trends[score.trend_id],
            "niche_names": [names[n] for n in score.niches],
            "primary_name": names.get(score.primary_niche or "", ""),
            "brief": brief, "brief_status": brief_row.get("status"),
            "evidence": evidence_rows(ctx, brief, members.get(score.trend_id, {})) if brief else [],
        })
    sections = []
    for niche in niches.niches:
        primary = [e for e in entries if e["score"].primary_niche == niche.id]
        also = [e for e in entries if niche.id in e["score"].niches and e["score"].primary_niche != niche.id]
        sections.append({"name": niche.name, "briefed": [e for e in primary if e["brief"]],
                         "others": [e for e in primary if not e["brief"]] + also})

    survivors, signals = gate_survivors(ctx), signal_videos(ctx)
    low, high = settings.thresholds.borderline
    is_signal = ctx.answers(IS_SIGNAL)
    niche_answers = [ctx.answers(niche_question(n)) for n in niches.niches]
    borderline = 0
    for video_id in survivors:
        probs = ([float(is_signal[video_id].value)] if video_id in is_signal else []) + \
                [float(a[video_id].value) for a in niche_answers if video_id in a]
        borderline += any(low <= p <= high for p in probs)
    missing = sum(1 for video_id in survivors
                  if (e := store.get_enrichment(video_id)) is None or e.transcript_status != "ok")
    none_rate = None
    if trends:
        answers = ctx.answers(assign_question(list(trends.values())))
        none_rate = scoring.none_rate(scoring.top_choices({v: a.probabilities or {} for v, a in answers.items()}),
                                      NONE_OF_THESE)
    flagged = [t.name for t in kept if t.self_check_agreement is not None
               and t.self_check_agreement < settings.trends.self_check_min_agreement]
    return {
        "run_id": run_id, "date": run["started_at"].date().isoformat(), "status": run["status"],
        "lookback_days": settings.scan.lookback_days,
        "funnel": {"collected": len(store.run_video_ids(run_id)), "passed": len(survivors), "signals": len(signals),
                   "proposed": len(trends), "kept": len(kept)},
        "cost": store.spend_by_provider(run_id), "total_cost": store.total_spend(run_id),
        "notes": store.notes(run_id), "entries": entries, "sections": sections,
        "outside": [e for e in entries if not e["score"].niches],
        "diagnostics": {"none_rate": none_rate, "flagged": flagged, "borderline": borderline,
                        "missing_transcripts": missing, "failures": store.failures_by_stage(run_id),
                        "weights": weights or settings.ranking.weights},
        "settings_yaml": yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
    }


def render_report(store: Store, run_id: int, weights: dict[str, float] | None = None) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True,
                      keep_trailing_newline=True)
    env.filters["pct"] = lambda x: f"{x:.0%}"
    env.filters["f2"] = lambda x: f"{x:.2f}"
    return env.get_template("report.md.j2").render(**build_report_data(store, run_id, weights))


def write_report(store: Store, run_id: int, reports_dir: Path, weights: dict[str, float] | None = None) -> Path:
    run = store.get_run(run_id)
    path = Path(reports_dir) / f"{run['started_at'].date().isoformat()}-scan-{run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(store, run_id, weights))
    return path

"""Command-line interface (spec §10). Run through scripts/scan.sh so API keys are loaded."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from jevtrends.budget import BudgetGuard
from jevtrends.config import NicheConfig, Settings, load_niches, load_settings, parse_weights
from jevtrends.evaluation import compute_metrics, sample_for_labeling
from jevtrends.http import APIError
from jevtrends.jev.client import JevClient
from jevtrends.llm.client import LLMClient
from jevtrends.pipeline import BudgetExceeded, estimate_scan, run_pipeline
from jevtrends.sources.scrapecreators import ScrapeCreatorsSource
from jevtrends.stages.context import RunContext, StageFailed
from jevtrends.stages.judge import truncate_words
from jevtrends.stages.report import write_report
from jevtrends.store import Store

app = typer.Typer(no_args_is_help=True, help="Find startup opportunities in TikTok trends using Jev.")
KEYS = ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")


def config_dir() -> Path:
    return Path(os.environ.get("JEVTRENDS_CONFIG_DIR", "config"))


def db_path() -> Path:
    return Path(os.environ.get("JEVTRENDS_DB", "data/jevtrends.db"))


def reports_dir() -> Path:
    return Path(os.environ.get("JEVTRENDS_REPORTS_DIR", "reports"))


def require_keys() -> dict[str, str]:
    missing = [name for name in KEYS if not os.environ.get(name)]
    if missing:
        typer.echo(f"Missing {', '.join(missing)}. Run commands through scripts/scan.sh, which loads the keys "
                   "from ~/Repos/.env.secrets.", err=True)
        raise typer.Exit(2)
    return {name: os.environ[name] for name in KEYS}


async def _execute(store: Store, run_id: int, settings: Settings, niches: NicheConfig, started_at: datetime,
                   keys: dict[str, str]) -> Path:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
        ctx = RunContext(
            run_id=run_id, store=store, settings=settings, niches=niches,
            source=ScrapeCreatorsSource(http, keys["SCRAPECREATORS_API_KEY"], settings.retries),
            jev=JevClient(http, keys["OPENROUTER_API_KEY"], settings.models.jev, settings.retries),
            llm=LLMClient(http, keys["OPENROUTER_API_KEY"], settings.models.llm, settings.retries,
                          settings.llm.use_json_schema),
            budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=started_at)
        return await run_pipeline(ctx, reports_dir())


def _finish(store: Store, run_id: int, settings: Settings, niches: NicheConfig, started_at: datetime,
            keys: dict[str, str]) -> None:
    try:
        path = asyncio.run(_execute(store, run_id, settings, niches, started_at, keys))
    except BudgetExceeded as exc:
        typer.echo(f"Run {run_id} stopped by the budget guard: {exc}\n"
                   f"Continue with: scripts/scan.sh resume {run_id} --budget <higher cap>", err=True)
        raise typer.Exit(1)
    except (StageFailed, APIError) as exc:
        typer.echo(f"Run {run_id} stopped: {exc}\nContinue with: scripts/scan.sh resume {run_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Run {run_id} completed for ${store.total_spend(run_id):.2f}. Report: {path}")


@app.command()
def scan(lookback_days: int | None = None, max_videos: int | None = None, budget: float | None = None,
         estimate: bool = typer.Option(False, "--estimate", help="Print the projected cost and exit.")) -> None:
    """Run a full scan."""
    settings = load_settings(config_dir() / "settings.yaml")
    niches = load_niches(config_dir() / "niches.yaml")
    if lookback_days:
        settings.scan.lookback_days = lookback_days
    if max_videos:
        settings.scan.max_videos = max_videos
    if budget:
        settings.budget.max_usd_per_scan = budget
    if estimate:
        p, decision = estimate_scan(settings, niches, BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing))
        typer.echo(f"Projected cost: ${p.total:.2f} (scraper ${p.scraper:.2f} · jev ${p.jev:.2f} · "
                   f"llm ${p.llm:.2f}); cap ${settings.budget.max_usd_per_scan:.2f}")
        for trim in decision.trims:
            typer.echo(f"Budget guard would trim: {trim}")
        if not decision.ok:
            typer.echo("Budget guard would stop this scan before it starts; raise --budget.")
        return
    keys = require_keys()
    store = Store(db_path())
    started_at = datetime.now(UTC)
    params = {"lookback_days": settings.scan.lookback_days, "max_videos": settings.scan.max_videos}
    run_id = store.create_run(params, settings, niches, started_at)
    typer.echo(f"Run {run_id} started.")
    _finish(store, run_id, settings, niches, started_at, keys)


@app.command()
def resume(run_id: int, budget: float | None = None) -> None:
    """Continue a failed or budget-stopped run, redoing only missing work."""
    keys = require_keys()
    store = Store(db_path())
    run = store.get_run(run_id)
    settings, niches = run["settings"], run["niches"]
    if budget:
        settings.budget.max_usd_per_scan = budget
    store.set_run_status(run_id, "running")
    _finish(store, run_id, settings, niches, run["started_at"], keys)


@app.command()
def report(run_id: int, weights: str | None = typer.Option(None, help="e.g. momentum=0.3,pain=0.2,...")) -> None:
    """Re-rank and re-render a run's report without calling any model."""
    path = write_report(Store(db_path()), run_id, reports_dir(), parse_weights(weights) if weights else None)
    typer.echo(f"Report: {path}")


@app.command()
def runs() -> None:
    """List runs with status and cost."""
    for run in Store(db_path()).list_runs():
        typer.echo(f"#{run['id']}  {run['started_at'][:16]}  {run['status']:<17}  ${run['cost_usd']:.2f}")


from jevtrends.stages.judge import truncate_words

SIGNAL_TYPES = ["behavior_need", "product_traction", "complaint_workaround", "other"]


def _prompt_choice(label: str, options: list[str]) -> str:
    while True:
        answer = typer.prompt(f"{label} ({'/'.join(options)})").strip()
        if answer in options:
            return answer
        typer.echo(f"Choose one of: {', '.join(options)}")


@app.command()
def label(run_id: int, n: int = 100) -> None:
    """Label a sample of this run's videos for evaluation (interactive)."""
    store = Store(db_path())
    niche_ids = store.get_run(run_id)["niches"].ids()
    sample = sample_for_labeling(store, run_id, n)
    typer.echo(f"{len(sample)} videos to label. Open each link if the text isn't enough. Ctrl-C stops; labels so far are saved.")
    for index, (video_id, stratum) in enumerate(sample, start=1):
        video, enrichment = store.get_video(video_id), store.get_enrichment(video_id)
        typer.echo(f"\n[{index}/{len(sample)}] {video.url}  ({stratum})")
        typer.echo(f"Caption: {video.caption}")
        typer.echo(f"Transcript: {truncate_words(enrichment.transcript if enrichment else None, 80)}")
        for comment in ((enrichment.comments if enrichment else None) or [])[:3]:
            typer.echo(f"Comment: {comment.text}")
        is_signal = typer.confirm("Signal? (evidence of what people do, want, buy or struggle with)")
        store.add_label(video_id, "is_signal", is_signal, stratum)
        if stratum == "gate_dropped":
            continue
        if is_signal:
            store.add_label(video_id, "signal_type", _prompt_choice("Type", SIGNAL_TYPES), stratum)
        raw = typer.prompt(f"Niches (comma-separated: {', '.join(niche_ids)}; blank for none)", default="",
                           show_default=False)
        store.add_label(video_id, "niches", [x.strip() for x in raw.split(",") if x.strip() in niche_ids], stratum)
        store.add_label(video_id, "is_promotional", typer.confirm("Promotional?"), stratum)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


@app.command(name="eval")
def evaluate(run_id: int) -> None:
    """Print precision, recall, calibration and a suggested threshold from your labels."""
    m = compute_metrics(Store(db_path()), run_id)
    typer.echo(f"Random-sample labels: {m['labeled_random']}")
    typer.echo(f"is_signal @ {m['is_signal']['threshold']}: precision {_fmt(m['is_signal']['precision'])}, "
               f"recall {_fmt(m['is_signal']['recall'])} (targets 0.80 / 0.70)")
    typer.echo(f"niches @ {m['niches']['threshold']}: precision {_fmt(m['niches']['precision'])}, "
               f"recall {_fmt(m['niches']['recall'])} (target precision 0.80)")
    typer.echo(f"gate miss rate: {_fmt(m['gate_miss_rate'])} · signal_type accuracy: {_fmt(m['signal_type_accuracy'])}")
    typer.echo(f"suggested is_signal threshold: {_fmt(m['suggested_is_signal_threshold'])}")
    for bucket in m["calibration"]:
        typer.echo(f"  {bucket['range']}: n={bucket['count']} predicted {_fmt(bucket['predicted'])} "
                   f"observed {_fmt(bucket['observed'])}")

"""The `jevtrends ugc` command group (UGC spec §10). Run through scripts/scan.sh so API keys are loaded."""

import asyncio
import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import typer

from jevtrends.budget import BudgetGuard
from jevtrends.http import APIError
from jevtrends.jev.client import JevClient
from jevtrends.llm.client import LLMClient
from jevtrends.pipeline import BudgetExceeded
from jevtrends.sources.scrapecreators import ScrapeCreatorsSource
from jevtrends.stages.context import StageFailed
from jevtrends.ugc.config import (RunProfiles, UgcSettings, load_niche, load_product, load_ugc_settings,
                                  parse_ugc_weights)
from jevtrends.ugc.context import UgcRunContext
from jevtrends.ugc.images import ImageFetcher
from jevtrends.ugc.niche_draft import draft_niche, render_niche_yaml
from jevtrends.ugc.pipeline import estimate_ugc, run_ugc_pipeline
from jevtrends.ugc.stages.report import write_ugc_report
from jevtrends.ugc.store import UgcStore

ugc_app = typer.Typer(no_args_is_help=True, help="Find TikTok trends for UGC and ads in one niche.")


def ugc_config_dir() -> Path:
    return Path(os.environ.get("JEVTRENDS_UGC_CONFIG_DIR", "config/ugc"))


def ugc_db_path() -> Path:
    return Path(os.environ.get("JEVTRENDS_UGC_DB", "data/ugc.db"))


def ugc_reports_dir() -> Path:
    return Path(os.environ.get("JEVTRENDS_UGC_REPORTS_DIR", "reports/ugc"))


def require_keys() -> dict[str, str]:
    from jevtrends.cli import require_keys as require  # imported here: jevtrends.cli mounts this module

    return require()


def load_profiles(niche_id: str, product_id: str | None) -> RunProfiles:
    config = ugc_config_dir()
    try:
        return RunProfiles(niche=load_niche(config, niche_id),
                           product=load_product(config, product_id) if product_id else None)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


async def _execute(store: UgcStore, run_id: int, settings: UgcSettings, profiles: RunProfiles,
                   started_at: datetime, keys: dict[str, str]) -> Path:
    openrouter = keys["OPENROUTER_API_KEY"]
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
        ctx = UgcRunContext(
            run_id=run_id, store=store, settings=settings, niche=profiles.niche, product=profiles.product,
            source=ScrapeCreatorsSource(http, keys["SCRAPECREATORS_API_KEY"], settings.retries),
            jev=JevClient(http, openrouter, settings.models.jev, settings.retries),
            llm=LLMClient(http, openrouter, settings.models.llm, settings.retries, settings.llm.use_json_schema,
                          effort=settings.models.llm_effort or None),
            vision=LLMClient(http, openrouter, settings.models.vision, settings.retries, settings.llm.use_json_schema,
                             image_tokens=settings.pricing.tokens_per_image),
            images=ImageFetcher(http, settings.retries),
            budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=started_at)
        return await run_ugc_pipeline(ctx, ugc_reports_dir())


def _finish(store: UgcStore, run_id: int, settings: UgcSettings, profiles: RunProfiles, started_at: datetime,
            keys: dict[str, str]) -> None:
    try:
        path = asyncio.run(_execute(store, run_id, settings, profiles, started_at, keys))
    except BudgetExceeded as exc:
        typer.echo(f"UGC run {run_id} stopped by the budget guard: {exc}\n"
                   f"Continue with: scripts/scan.sh ugc resume {run_id} --budget <higher cap>", err=True)
        raise typer.Exit(1)
    except (StageFailed, APIError) as exc:
        typer.echo(f"UGC run {run_id} stopped: {exc}\nContinue with: scripts/scan.sh ugc resume {run_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"UGC run {run_id} completed for ${store.total_spend(run_id):.2f}. Report: {path}")


@ugc_app.command()
def scan(niche: str = typer.Option(..., help="Niche id: config/ugc/niches/<id>.yaml"),
         product: str | None = typer.Option(None, help="Product id: config/ugc/products/<id>.yaml"),
         lookback_days: int | None = None, max_videos: int | None = None, budget: float | None = None,
         no_vision: bool = typer.Option(False, "--no-vision", help="Skip reading cover frames (text only)."),
         estimate: bool = typer.Option(False, "--estimate", help="Print the projected cost and exit.")) -> None:
    """Run a full UGC scan for one niche."""
    settings = load_ugc_settings(ugc_config_dir() / "settings.yaml")
    profiles = load_profiles(niche, product)
    if lookback_days:
        settings.scan.lookback_days = lookback_days
    if max_videos:
        settings.scan.max_videos = max_videos
    if budget:
        settings.budget.max_usd_per_scan = budget
    if no_vision:
        settings.vision.enabled = False
    if estimate:
        projection, decision = estimate_ugc(settings, profiles.niche)
        typer.echo(f"Projected cost: ${projection.total:.2f} (scraper ${projection.scraper:.2f} · jev "
                   f"${projection.jev:.2f} · vision ${projection.vision:.2f} · llm ${projection.llm:.2f}); "
                   f"cap ${settings.budget.max_usd_per_scan:.2f}")
        for trim in decision.trims:
            typer.echo(f"Budget guard would cut: {trim}")
        if not decision.ok:
            typer.echo("Budget guard would stop this run before it starts; raise --budget.")
        return
    keys = require_keys()
    store = UgcStore(ugc_db_path())
    started_at = datetime.now(UTC)
    params = {"niche": niche, "product": product, "lookback_days": settings.scan.lookback_days,
              "max_videos": settings.scan.max_videos, "vision": settings.vision.enabled}
    run_id = store.create_run(params, settings, profiles, started_at)
    typer.echo(f"UGC run {run_id} started for niche {niche}.")
    _finish(store, run_id, settings, profiles, started_at, keys)


@ugc_app.command()
def resume(run_id: int, budget: float | None = None) -> None:
    """Continue a failed or budget-stopped UGC run, redoing only missing work."""
    keys = require_keys()
    store = UgcStore(ugc_db_path())
    run = store.get_run(run_id)
    settings = run["settings"]
    if budget:
        settings.budget.max_usd_per_scan = budget
    store.set_run_status(run_id, "running")
    _finish(store, run_id, settings, RunProfiles(niche=run["niche"], product=run["product"]), run["started_at"],
            keys)


@ugc_app.command()
def report(run_id: int,
           weights: str | None = typer.Option(None, help="e.g. momentum=0.25,performance=0.25,fit=0.3,...")) -> None:
    """Re-rank and re-render a UGC run's report without calling any model."""
    path = write_ugc_report(UgcStore(ugc_db_path()), run_id, ugc_reports_dir(),
                            parse_ugc_weights(weights) if weights else None)
    typer.echo(f"Report: {path}")


@ugc_app.command()
def runs() -> None:
    """List UGC runs with niche, product, status and cost."""
    store = UgcStore(ugc_db_path())
    for run in store.list_runs():
        details = store.get_run(run["id"])
        product = details["product"].id if details["product"] else "generic"
        typer.echo(f"#{run['id']}  {run['started_at'][:16]}  {details['niche'].id:<18}  {product:<12}  "
                   f"{run['status']:<17}  ${run['cost_usd']:.2f}")


@ugc_app.command(name="niche-draft")
def niche_draft(niche_id: str, description: str) -> None:
    """Draft config/ugc/niches/<niche_id>.yaml from a one-line description; review it before use."""
    path = ugc_config_dir() / "niches" / f"{niche_id}.yaml"
    if path.exists():
        typer.echo(f"{path} already exists; not overwriting it.", err=True)
        raise typer.Exit(1)
    keys = require_keys()
    settings = load_ugc_settings(ugc_config_dir() / "settings.yaml")

    async def draft():
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
            llm = LLMClient(http, keys["OPENROUTER_API_KEY"], settings.models.llm, settings.retries,
                            settings.llm.use_json_schema, effort=settings.models.llm_effort or None)
            return await draft_niche(llm, description)

    out, cost = asyncio.run(draft())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_niche_yaml(niche_id, out, date.today()))
    typer.echo(f"Wrote {path} for ${cost:.2f}. Review and edit it before running a scan.")

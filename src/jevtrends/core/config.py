"""Shared configuration building blocks and API key check."""

import os

import typer
from pydantic import BaseModel

KEYS = ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")


def require_keys() -> dict[str, str]:
    missing = [name for name in KEYS if not os.environ.get(name)]
    if missing:
        typer.echo(f"Missing {', '.join(missing)}. Run commands through scripts/scan.sh, which loads the keys "
                   "from ~/Repos/.env.secrets.", err=True)
        raise typer.Exit(2)
    return {name: os.environ[name] for name in KEYS}


class PricingCfg(BaseModel):
    jev_input_per_mtok: float = 0.042
    llm_input_per_mtok: float = 5.00
    llm_output_per_mtok: float = 25.00
    scrapecreators_per_credit: float = 0.00188
    discover_expected_output_tokens: int = 15_000
    brief_expected_output_tokens: int = 3_000


class BudgetCfg(BaseModel):
    max_usd_per_scan: float = 5.00


class ConcurrencyCfg(BaseModel):
    jev: int = 16
    scraper: int = 5
    llm: int = 5


class RetriesCfg(BaseModel):
    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0


class FailureCfg(BaseModel):
    max_item_failure_rate: float = 0.20


class LlmCfg(BaseModel):
    use_json_schema: bool = True

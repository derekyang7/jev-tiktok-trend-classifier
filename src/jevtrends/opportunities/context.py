"""Run state for the startup opportunities pipeline (spec §5.2)."""

from dataclasses import dataclass, field
from datetime import datetime

from jevtrends.core.budget import BudgetGuard
from jevtrends.core.context import ContextHelpers, JevLike, LLMLike
from jevtrends.core.sources.base import Source
from jevtrends.opportunities.config import NicheConfig, Settings
from jevtrends.opportunities.store import OpportunitiesStore


@dataclass
class RunContext(ContextHelpers):
    run_id: int
    store: OpportunitiesStore
    settings: Settings
    niches: NicheConfig
    source: Source | None
    jev: JevLike | None
    llm: LLMLike | None
    budget: BudgetGuard | None
    now: datetime
    limits: dict[str, int] = field(default_factory=dict)


def report_context(store: OpportunitiesStore, run_id: int) -> RunContext:
    """Read-only context for building reports; no API clients are needed."""
    run = store.get_run(run_id)
    return RunContext(run_id=run_id, store=store, settings=run["settings"], niches=run["niches"],
                      source=None, jev=None, llm=None, budget=None, now=run["started_at"])

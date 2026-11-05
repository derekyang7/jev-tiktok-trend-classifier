"""Deterministic stand-ins and a RunContext factory for the startup opportunities pipeline."""

from datetime import UTC, datetime

from jevtrends.core.budget import BudgetGuard
from jevtrends.opportunities.config import NicheConfig, Settings
from jevtrends.opportunities.context import RunContext
from jevtrends.opportunities.store import OpportunitiesStore
from tests.helpers import FakeJev, FakeLLM, FakeSource

__all__ = ["FakeJev", "FakeLLM", "FakeSource", "NOW", "make_ctx", "test_niches"]

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def test_niches() -> NicheConfig:
    return NicheConfig.model_validate({
        "niches": [
            {"id": "ai", "name": "AI", "covers": "AI tools", "not_for": "tech news", "seed_queries": ["ai app"]},
            {"id": "fintech_payments", "name": "Fintech & payments", "covers": "money", "not_for": "shopping",
             "seed_queries": ["budgeting app"]},
        ],
        "global_seed_queries": ["rant"],
    })


test_niches.__test__ = False  # not a pytest test


def make_ctx(source=None, jev=None, llm=None, niches: NicheConfig | None = None,
             settings: Settings | None = None, store: OpportunitiesStore | None = None,
             run_id: int | None = None) -> RunContext:
    settings = settings or Settings()
    niches = niches or test_niches()
    store = store or OpportunitiesStore(":memory:")
    if run_id is None:
        run_id = store.create_run({"lookback_days": settings.scan.lookback_days}, settings, niches, NOW)
    return RunContext(run_id=run_id, store=store, settings=settings, niches=niches, source=source or FakeSource(),
                      jev=jev or FakeJev(), llm=llm or FakeLLM(lambda *a: None),
                      budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=NOW)

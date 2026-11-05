"""Shared budget guard and trimming helper (spec §12.1)."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from jevtrends.core.config import PricingCfg

SEARCH_PAGES_PER_QUERY = 2


@dataclass
class Trimmable:
    """Optional work the guard may cut, listed in the order it is cut (spec §12.1)."""

    name: str
    units: int
    unit_cost: float
    minimum: int
    note: Callable[[int, int], str]  # (kept, original) -> the trim note


@dataclass
class TrimResult:
    ok: bool
    units: dict[str, int]
    projected: float
    trims: list[str] = field(default_factory=list)


def trim_to_fit(available: float, fixed_cost: float, items: list[Trimmable]) -> TrimResult:
    """Cuts each item in order, as little as needed, until fixed_cost plus the remaining items fit."""
    units = {item.name: item.units for item in items}

    def total() -> float:
        return fixed_cost + sum(units[item.name] * item.unit_cost for item in items)

    trims: list[str] = []
    for item in items:
        if total() > available and units[item.name] > item.minimum and item.unit_cost > 0:
            cut = min(units[item.name] - item.minimum, math.ceil((total() - available) / item.unit_cost))
            units[item.name] -= cut
            trims.append(item.note(units[item.name], item.units))
    projected = total()
    return TrimResult(ok=projected <= available, units=units, projected=projected, trims=trims)


class BudgetGuard:
    def __init__(self, cap_usd: float, pricing: PricingCfg):
        self.cap = cap_usd
        self.pricing = pricing

    def scraper_cost(self, requests: int) -> float:
        return requests * self.pricing.scrapecreators_per_credit

    def jev_cost(self, chars: int) -> float:
        return math.ceil(chars / 4) * 1.2 * self.pricing.jev_input_per_mtok / 1e6

    def llm_cost(self, input_chars: int, output_tokens: int) -> float:
        return (math.ceil(input_chars / 4) * self.pricing.llm_input_per_mtok
                + output_tokens * self.pricing.llm_output_per_mtok) / 1e6

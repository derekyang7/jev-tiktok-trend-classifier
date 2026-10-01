"""Cost projection and trimming decisions (spec §12.1)."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from jevtrends.config import PricingCfg, Settings

STAGE_ORDER = ["collect", "gate", "enrich", "judge", "discover", "assign", "score", "brief", "report"]

# Rough request sizes in characters, used only for projections.
CHARS = {"gate": 1_200, "judge": 16_000, "assign": 30_000, "trend_score": 20_000,
         "digest_line": 600, "discover_prompt": 6_000, "brief": 20_000}
GATE_PASS_RATE = 1.0  # pilot scan 2026-09-29: 100 of 100 videos passed the lenient gate
SIGNAL_RATE = 0.65
EXPECTED_TRENDS = 40
SEARCH_PAGES_PER_QUERY = 2


@dataclass
class RemainingWork:
    search_requests: int = 0
    transcript_requests: int = 0
    comment_requests: int = 0
    jev_chars: int = 0
    discover_chars: int = 0
    brief_count: int = 0


@dataclass
class Projection:
    scraper: float
    jev: float
    llm: float

    @property
    def total(self) -> float:
        return self.scraper + self.jev + self.llm


@dataclass
class Decision:
    ok: bool
    comment_requests: int
    brief_count: int
    projected: float
    trims: list[str] = field(default_factory=list)


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

    def project(self, work: RemainingWork) -> Projection:
        scraper = self.scraper_cost(work.search_requests + work.transcript_requests + work.comment_requests)
        llm = work.brief_count * self.llm_cost(CHARS["brief"], self.pricing.brief_expected_output_tokens)
        if work.discover_chars:
            llm += self.llm_cost(work.discover_chars, self.pricing.discover_expected_output_tokens)
        return Projection(scraper=scraper, jev=self.jev_cost(work.jev_chars), llm=llm)

    def decide(self, spent: float, work: RemainingWork, min_briefs: int) -> Decision:
        # Briefs go first (lowest-ranked dropped); comments carry the complaint signal, so they are trimmed last.
        per_brief = self.llm_cost(CHARS["brief"], self.pricing.brief_expected_output_tokens)
        fixed = self.project(replace(work, comment_requests=0, brief_count=0)).total
        result = trim_to_fit(self.cap - spent, fixed, [
            Trimmable("briefs", work.brief_count, per_brief, min(min_briefs, work.brief_count),
                      lambda kept, was: f"{kept} briefs written instead of {was}"),
            Trimmable("comments", work.comment_requests, self.scraper_cost(1), 0,
                      lambda kept, was: f"comments fetched for {kept} videos instead of {was}"),
        ])
        return Decision(ok=result.ok, comment_requests=result.units["comments"],
                        brief_count=result.units["briefs"], projected=result.projected, trims=result.trims)

def remaining_work(from_stage: str, counts: dict[str, int], settings: Settings,
                   comment_videos: int, max_briefs: int) -> RemainingWork:
    """Estimates the work left from from_stage onward, using known counts where available."""
    todo = set(STAGE_ORDER[STAGE_ORDER.index(from_stage):])
    collected = counts.get("collected", settings.scan.max_videos)
    gate_passed = counts.get("gate_passed", round(collected * GATE_PASS_RATE))
    signals = counts.get("signals", round(gate_passed * SIGNAL_RATE))
    kept = counts.get("kept", EXPECTED_TRENDS)
    work = RemainingWork()
    if "collect" in todo:
        work.search_requests = counts["queries"] * SEARCH_PAGES_PER_QUERY
    if "gate" in todo:
        work.jev_chars += collected * CHARS["gate"]
    if "enrich" in todo:
        work.transcript_requests = gate_passed
        work.comment_requests = min(comment_videos, gate_passed)
    if "judge" in todo:
        work.jev_chars += gate_passed * CHARS["judge"]
    if "discover" in todo and signals:
        work.discover_chars = signals * CHARS["digest_line"] + CHARS["discover_prompt"]
    if "assign" in todo:
        work.jev_chars += signals * CHARS["assign"]
    if "score" in todo:
        work.jev_chars += kept * CHARS["trend_score"]
    if "brief" in todo:
        work.brief_count = min(max_briefs, kept)
    return work

"""Cost projection and trimming decisions (spec §12.1)."""

import math
from dataclasses import dataclass, field, replace

from jevtrends.config import PricingCfg, Settings

STAGE_ORDER = ["collect", "gate", "enrich", "judge", "discover", "assign", "score", "brief", "report"]

# Rough request sizes in characters, used only for projections.
CHARS = {"gate": 1_200, "judge": 16_000, "assign": 30_000, "trend_score": 20_000,
         "digest_line": 600, "discover_prompt": 6_000, "brief": 20_000}
GATE_PASS_RATE = 0.6
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
        available = self.cap - spent
        comments, briefs, trims = work.comment_requests, work.brief_count, []

        def total() -> float:
            return self.project(replace(work, comment_requests=comments, brief_count=briefs)).total

        if total() > available and comments:
            cut = min(comments, math.ceil((total() - available) / self.scraper_cost(1)))
            comments -= cut
            trims.append(f"comments fetched for {comments} videos instead of {work.comment_requests}")
        if total() > available and briefs > min_briefs:
            per_brief = self.llm_cost(CHARS["brief"], self.pricing.brief_expected_output_tokens)
            cut = min(briefs - min_briefs, math.ceil((total() - available) / per_brief))
            briefs -= cut
            trims.append(f"{briefs} briefs written instead of {work.brief_count}")
        projected = total()
        return Decision(ok=projected <= available, comment_requests=comments, brief_count=briefs,
                        projected=projected, trims=trims)


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

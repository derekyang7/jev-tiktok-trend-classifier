"""Cost projection and trimming decisions for startup opportunities (spec §12.1)."""

from dataclasses import dataclass, field, replace

from jevtrends.core.budget import SEARCH_PAGES_PER_QUERY, BudgetGuard, Trimmable, trim_to_fit
from jevtrends.opportunities.config import Settings

STAGE_ORDER = ["collect", "gate", "enrich", "judge", "discover", "assign", "score", "brief", "report"]

# Rough request sizes in characters, used only for projections.
CHARS = {"gate": 1_200, "judge": 16_000, "assign": 30_000, "trend_score": 20_000,
         "digest_line": 600, "discover_prompt": 6_000, "brief": 20_000}
GATE_PASS_RATE = 1.0  # pilot scan 2026-09-29: 100 of 100 videos passed the lenient gate
SIGNAL_RATE = 0.65
EXPECTED_TRENDS = 40


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


def project_opportunities(guard: BudgetGuard, work: RemainingWork) -> Projection:
    scraper = guard.scraper_cost(work.search_requests + work.transcript_requests + work.comment_requests)
    llm = work.brief_count * guard.llm_cost(CHARS["brief"], guard.pricing.brief_expected_output_tokens)
    if work.discover_chars:
        llm += guard.llm_cost(work.discover_chars, guard.pricing.discover_expected_output_tokens)
    return Projection(scraper=scraper, jev=guard.jev_cost(work.jev_chars), llm=llm)


def decide_opportunities(guard: BudgetGuard, spent: float, work: RemainingWork, min_briefs: int) -> Decision:
    # Briefs go first (lowest-ranked dropped); comments carry the complaint signal, so they are trimmed last.
    per_brief = guard.llm_cost(CHARS["brief"], guard.pricing.brief_expected_output_tokens)
    fixed = project_opportunities(guard, replace(work, comment_requests=0, brief_count=0)).total
    result = trim_to_fit(guard.cap - spent, fixed, [
        Trimmable("briefs", work.brief_count, per_brief, min(min_briefs, work.brief_count),
                  lambda kept, was: f"{kept} briefs written instead of {was}"),
        Trimmable("comments", work.comment_requests, guard.scraper_cost(1), 0,
                  lambda kept, was: f"comments fetched for {kept} videos instead of {was}"),
    ])
    return Decision(ok=result.ok, comment_requests=result.units["comments"],
                    brief_count=result.units["briefs"], projected=result.projected, trims=result.trims)

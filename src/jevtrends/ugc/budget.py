"""Cost projection and cuts for the UGC version (UGC spec §11, §12.1)."""

import math
from dataclasses import dataclass, field, replace

from jevtrends.budget import BudgetGuard, Trimmable, trim_to_fit
from jevtrends.ugc.config import UgcSettings

UGC_STAGE_ORDER = ["collect", "gate", "enrich", "look", "judge", "sounds", "discover", "assign", "score", "brief",
                   "report"]

# Rough request sizes in characters, used only for projections.
CHARS = {"gate": 1_200, "judge": 16_000, "sound_check": 1_000, "assign": 34_000, "trend_score": 30_000,
         "digest_line": 680, "sound_line": 800, "discover_prompt": 8_000, "brief": 30_000}
GATE_PASS_RATE = 0.8
RELEVANT_RATE = 0.7
SLIDESHOW_RATE = 0.1
EXPECTED_TRENDS = 40
SONG_PAGE_SIZE = 20
SAMPLE_VIDEOS_PER_SOUND = 30
VISION_PROMPT_TOKENS = 400


@dataclass
class UgcWork:
    search_requests: int = 0
    transcript_requests: int = 0
    comment_requests: int = 0
    sound_requests: int = 0
    jev_chars: int = 0
    vision_requests: int = 0
    cover_images: int = 0  # one image per video: its cover, or a slideshow's first slide
    extra_slides: int = 0  # slideshow slides after the first; the guard may cut these
    discover_chars: int = 0
    brief_count: int = 0


@dataclass
class UgcProjection:
    scraper: float
    jev: float
    vision: float
    llm: float

    @property
    def total(self) -> float:
        return self.scraper + self.jev + self.vision + self.llm


@dataclass
class UgcDecision:
    ok: bool
    brief_count: int
    comment_requests: int
    slides_per_post: int
    projected: float
    trims: list[str] = field(default_factory=list)


def ugc_remaining_work(from_stage: str, counts: dict[str, int], settings: UgcSettings, comment_videos: int,
                       slides_per_post: int, max_briefs: int) -> UgcWork:
    """Estimates the work left from from_stage onward, using known counts where available."""
    todo = set(UGC_STAGE_ORDER[UGC_STAGE_ORDER.index(from_stage):])
    sounds_cfg = settings.sounds
    collected = counts.get("collected", settings.scan.max_videos)
    gate_passed = counts.get("gate_passed", round(collected * GATE_PASS_RATE))
    slideshows = counts.get("slideshows", round(gate_passed * SLIDESHOW_RATE))
    relevant = counts.get("relevant", round(gate_passed * RELEVANT_RATE))
    sounds = counts.get("sounds", sounds_cfg.popular_count)
    kept = counts.get("kept", EXPECTED_TRENDS)
    work = UgcWork()
    if "collect" in todo:
        work.search_requests = counts["searches"] * settings.scan.search_pages_per_query
    if "gate" in todo:
        work.jev_chars += collected * CHARS["gate"]
    if "enrich" in todo:
        work.transcript_requests = gate_passed - slideshows
        work.comment_requests = min(comment_videos, gate_passed)
    if "look" in todo and settings.vision.enabled:
        work.vision_requests = gate_passed
        work.cover_images = gate_passed
        work.extra_slides = slideshows * max(0, slides_per_post - 1)
    if "judge" in todo:
        work.jev_chars += gate_passed * CHARS["judge"]
    if "sounds" in todo:
        sampled = sounds_cfg.popular_count * sounds_cfg.sample_pages
        work.sound_requests = math.ceil(sounds_cfg.popular_count / SONG_PAGE_SIZE) + sampled
        work.jev_chars += sampled * SAMPLE_VIDEOS_PER_SOUND * CHARS["sound_check"]
    if "discover" in todo and relevant:
        work.discover_chars = (relevant * CHARS["digest_line"] + sounds * CHARS["sound_line"]
                               + CHARS["discover_prompt"])
    if "assign" in todo:
        work.jev_chars += relevant * CHARS["assign"]
    if "score" in todo:
        work.jev_chars += (kept + sounds) * CHARS["trend_score"]
    if "brief" in todo:
        work.brief_count = min(max_briefs, kept + sounds)
    return work


def _guard(settings: UgcSettings) -> BudgetGuard:
    return BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing)


def project_ugc(work: UgcWork, settings: UgcSettings) -> UgcProjection:
    pricing, guard = settings.pricing, _guard(settings)
    scraper = guard.scraper_cost(work.search_requests + work.transcript_requests + work.comment_requests
                                 + work.sound_requests)
    vision_in = ((work.cover_images + work.extra_slides) * pricing.tokens_per_image
                 + work.vision_requests * VISION_PROMPT_TOKENS)
    vision = (vision_in * pricing.vision_input_per_mtok
              + work.vision_requests * pricing.vision_expected_output_tokens * pricing.vision_output_per_mtok) / 1e6
    llm = work.brief_count * guard.llm_cost(CHARS["brief"], pricing.brief_expected_output_tokens)
    if work.discover_chars:
        llm += guard.llm_cost(work.discover_chars, pricing.discover_expected_output_tokens)
    return UgcProjection(scraper=scraper, jev=guard.jev_cost(work.jev_chars), vision=vision, llm=llm)


def decide_ugc(spent: float, work: UgcWork, settings: UgcSettings, slideshows: int,
               slides_per_post: int) -> UgcDecision:
    """Cuts briefs, then comments, then extra slides until the rest of the run fits under the cap (spec §12.1)."""
    pricing, guard = settings.pricing, _guard(settings)
    fixed = project_ugc(replace(work, brief_count=0, comment_requests=0, extra_slides=0), settings).total
    result = trim_to_fit(settings.budget.max_usd_per_scan - spent, fixed, [
        Trimmable("briefs", work.brief_count, guard.llm_cost(CHARS["brief"], pricing.brief_expected_output_tokens),
                  min(settings.briefs.min_briefs, work.brief_count),
                  lambda kept, was: f"{kept} briefs written instead of {was}"),
        Trimmable("comments", work.comment_requests, guard.scraper_cost(1), 0,
                  lambda kept, was: f"comments fetched for {kept} videos instead of {was}"),
        Trimmable("slides", work.extra_slides, pricing.tokens_per_image * pricing.vision_input_per_mtok / 1e6, 0,
                  lambda kept, was: f"{kept} extra slideshow slides read instead of {was}"),
    ])
    slides = slides_per_post
    if result.units["slides"] < work.extra_slides:
        slides = 1 + result.units["slides"] // max(1, slideshows)
    return UgcDecision(ok=result.ok, brief_count=result.units["briefs"], comment_requests=result.units["comments"],
                       slides_per_post=slides, projected=result.projected, trims=result.trims)

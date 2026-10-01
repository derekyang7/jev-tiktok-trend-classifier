"""Loads and validates the UGC version's settings, niche profiles and product profiles (UGC spec §9)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from jevtrends.config import BudgetCfg, ConcurrencyCfg, FailureCfg, LlmCfg, PricingCfg, RetriesCfg
from jevtrends.ugc.models import FACETS

WEIGHT_KEYS = {"momentum", "performance", "fit", "breadth", "ease"}


class UgcScanCfg(BaseModel):
    lookback_days: int = 14
    max_videos: int = 600
    region: str = "US"
    search_pages_per_query: int = 2
    top_search: bool = True


class UgcThresholdsCfg(BaseModel):
    gate_keep: float = 0.25
    relevant: float = 0.50
    promotional: float = 0.50
    trend_member: float = 0.50
    brand_risk: float = 0.50
    borderline: tuple[float, float] = (0.35, 0.65)


class UgcEnrichCfg(BaseModel):
    transcript_max_words: int = 1500
    comments_top_videos: int = 100
    comments_per_video: int = 20
    comment_max_chars: int = 300
    comments_refresh_days: int = 7


class VisionCfg(BaseModel):
    enabled: bool = True
    slides_per_post: int = 3
    max_long_edge: int = 960
    max_image_bytes: int = 3_000_000
    on_screen_text_max_chars: int = 400


class SoundsCfg(BaseModel):
    popular_count: int = 50
    popular_period_days: int = 7
    sample_pages: int = 1
    niche_min_videos: int = 3
    report_count: int = 20
    trusted_licensing_flag: str = ""  # a boolean TikTok flag that Step 0 showed agrees with the business-use filter


class UgcTrendsCfg(BaseModel):
    discover_max_digest_tokens: int = 80_000
    videos_per_candidate: int = 8
    max_candidates_per_facet: int = 15
    min_support: float = 3.0
    min_creators: int = 3
    none_rate_warning: float = 0.30
    self_check_min_agreement: float = 0.5
    momentum_recent_fraction: float = 0.333
    momentum_pseudo_count: float = 2.0
    performance_pseudo_count: float = 2.0
    follower_floor: int = 1000
    evidence_per_trend: int = 12
    pair_min_videos: float = 2.0
    pair_min_lift: float = 1.5


def _default_weights() -> dict[str, float]:
    return {"momentum": 0.25, "performance": 0.25, "fit": 0.30, "breadth": 0.10, "ease": 0.10}


class UgcRankingCfg(BaseModel):
    weights: dict[str, float] = Field(default_factory=_default_weights)

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != WEIGHT_KEYS:
            raise ValueError(f"ranking.weights keys must be exactly {sorted(WEIGHT_KEYS)}")
        if abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError("ranking.weights must sum to 1")
        return value


def _default_quotas() -> dict[str, int]:
    return {"format": 3, "hook": 2, "sound": 2, "topic": 2, "need": 2}


class UgcBriefsCfg(BaseModel):
    quotas: dict[str, int] = Field(default_factory=_default_quotas)
    min_briefs: int = 5
    top_picks: int = 15

    @field_validator("quotas")
    @classmethod
    def _check_quotas(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != set(FACETS):
            raise ValueError(f"briefs.quotas keys must be exactly {list(FACETS)}")
        if any(count < 0 for count in value.values()):
            raise ValueError("briefs.quotas must not be negative")
        return value

    @property
    def max_briefs(self) -> int:
        return sum(self.quotas.values())


class UgcModelsCfg(BaseModel):
    jev: str = "typesafe/jev-1.13"
    llm: str = "anthropic/claude-opus-5.5"
    vision: str = "anthropic/claude-haiku-4.5"
    llm_effort: str = "medium"


class UgcPricingCfg(PricingCfg):
    llm_input_per_mtok: float = 4.00
    llm_output_per_mtok: float = 20.00
    vision_input_per_mtok: float = 1.00
    vision_output_per_mtok: float = 5.00
    tokens_per_image: int = 700
    vision_expected_output_tokens: int = 150
    discover_expected_output_tokens: int = 25_000
    brief_expected_output_tokens: int = 5_000


class UgcConcurrencyCfg(ConcurrencyCfg):
    vision: int = 8


class UgcSettings(BaseModel):
    scan: UgcScanCfg = Field(default_factory=UgcScanCfg)
    thresholds: UgcThresholdsCfg = Field(default_factory=UgcThresholdsCfg)
    enrich: UgcEnrichCfg = Field(default_factory=UgcEnrichCfg)
    vision: VisionCfg = Field(default_factory=VisionCfg)
    sounds: SoundsCfg = Field(default_factory=SoundsCfg)
    trends: UgcTrendsCfg = Field(default_factory=UgcTrendsCfg)
    ranking: UgcRankingCfg = Field(default_factory=UgcRankingCfg)
    briefs: UgcBriefsCfg = Field(default_factory=UgcBriefsCfg)
    models: UgcModelsCfg = Field(default_factory=UgcModelsCfg)
    pricing: UgcPricingCfg = Field(default_factory=UgcPricingCfg)
    budget: BudgetCfg = Field(default_factory=BudgetCfg)
    concurrency: UgcConcurrencyCfg = Field(default_factory=UgcConcurrencyCfg)
    retries: RetriesCfg = Field(default_factory=RetriesCfg)
    failure: FailureCfg = Field(default_factory=FailureCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)


class NicheProfile(BaseModel):
    id: str
    name: str
    covers: str
    not_for: str
    audience: str = ""
    seed_queries: list[str]
    hashtags: list[str] = Field(default_factory=list)

    @field_validator("seed_queries")
    @classmethod
    def _clean_queries(cls, value: list[str]) -> list[str]:
        queries = list(dict.fromkeys(q.strip() for q in value if q.strip()))
        if not queries:
            raise ValueError("a niche needs at least one seed query")
        return queries

    @field_validator("hashtags")
    @classmethod
    def _clean_hashtags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(h.strip().lstrip("#") for h in value if h.strip().lstrip("#")))

    def searches(self, top_search: bool) -> list[str]:
        """Search keys as "type:query", in the order they run (UGC spec §6.1)."""
        keys = [f"keyword:{q}" for q in self.seed_queries] + [f"hashtag:{h}" for h in self.hashtags]
        if top_search:
            keys += [f"top:{q}" for q in self.seed_queries]
        return keys


class Claim(BaseModel):
    id: str = Field(pattern=r"^c\d+$")
    text: str


class ProductProfile(BaseModel):
    id: str
    name: str
    one_liner: str = ""
    what_it_does: str
    audience: str = ""
    key_benefits: list[str] = Field(default_factory=list)
    claims_allowed: list[Claim] = Field(default_factory=list)
    claims_to_avoid: list[str] = Field(default_factory=list)
    tone: str = ""

    @model_validator(mode="after")
    def _unique_claims(self) -> "ProductProfile":
        ids = [claim.id for claim in self.claims_allowed]
        if len(ids) != len(set(ids)):
            raise ValueError("claim ids must be unique")
        return self


class RunProfiles(BaseModel):
    """The niche and optional product a run was started with; stored in the run's snapshot."""

    niche: NicheProfile
    product: ProductProfile | None = None


def load_ugc_settings(path: Path) -> UgcSettings:
    return UgcSettings.model_validate(yaml.safe_load(Path(path).read_text()) or {})


def _load_profile(path: Path, kind: str, profile_id: str, model: type[BaseModel]):
    if not path.exists():
        raise FileNotFoundError(f"No {kind} profile at {path}")
    profile = model.model_validate(yaml.safe_load(path.read_text()))
    if profile.id != profile_id:
        raise ValueError(f"{path} has id {profile.id!r}; expected {profile_id!r}")
    return profile


def load_niche(config_dir: Path, niche_id: str) -> NicheProfile:
    return _load_profile(Path(config_dir) / "niches" / f"{niche_id}.yaml", "niche", niche_id, NicheProfile)


def load_product(config_dir: Path, product_id: str) -> ProductProfile:
    return _load_profile(Path(config_dir) / "products" / f"{product_id}.yaml", "product", product_id,
                         ProductProfile)


def parse_ugc_weights(text: str) -> dict[str, float]:
    """Parses 'momentum=0.25,performance=0.25,...' into weights validated by UgcRankingCfg."""
    weights: dict[str, float] = {}
    for part in text.split(","):
        key, _, raw = part.partition("=")
        weights[key.strip()] = float(raw)
    return UgcRankingCfg(weights=weights).weights

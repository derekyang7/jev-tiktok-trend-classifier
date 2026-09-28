"""Loads and validates config/settings.yaml and config/niches.yaml (spec §9)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

WEIGHT_KEYS = {"momentum", "pain", "spend", "underserved", "breadth"}


class ScanCfg(BaseModel):
    lookback_days: int = 30
    max_videos: int = 1000
    region: str = "US"


class ThresholdsCfg(BaseModel):
    gate_keep: float = 0.25
    is_signal: float = 0.50
    niche_member: float = 0.50
    trend_member: float = 0.50
    borderline: tuple[float, float] = (0.35, 0.65)


class EnrichCfg(BaseModel):
    transcript_max_words: int = 1500
    comments_top_videos: int = 150
    comments_per_video: int = 20
    comment_max_chars: int = 300
    comments_refresh_days: int = 7


class TrendsCfg(BaseModel):
    discover_max_digest_tokens: int = 100_000
    max_candidates: int = 60
    min_support: float = 3.0
    min_creators: int = 3
    none_rate_warning: float = 0.30
    self_check_min_agreement: float = 0.5
    momentum_recent_fraction: float = 0.333
    momentum_pseudo_count: float = 2.0
    evidence_per_trend: int = 12


def _default_weights() -> dict[str, float]:
    return {"momentum": 0.30, "pain": 0.20, "spend": 0.20, "underserved": 0.20, "breadth": 0.10}


class RankingCfg(BaseModel):
    weights: dict[str, float] = Field(default_factory=_default_weights)

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != WEIGHT_KEYS:
            raise ValueError(f"ranking.weights keys must be exactly {sorted(WEIGHT_KEYS)}")
        if abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError("ranking.weights must sum to 1")
        return value


class BriefsCfg(BaseModel):
    max_briefs: int = 20
    min_briefs: int = 5


class ModelsCfg(BaseModel):
    jev: str = "typesafe/jev-1.13"
    llm: str = "anthropic/claude-opus-5"


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


class Settings(BaseModel):
    scan: ScanCfg = Field(default_factory=ScanCfg)
    thresholds: ThresholdsCfg = Field(default_factory=ThresholdsCfg)
    enrich: EnrichCfg = Field(default_factory=EnrichCfg)
    trends: TrendsCfg = Field(default_factory=TrendsCfg)
    ranking: RankingCfg = Field(default_factory=RankingCfg)
    briefs: BriefsCfg = Field(default_factory=BriefsCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    pricing: PricingCfg = Field(default_factory=PricingCfg)
    budget: BudgetCfg = Field(default_factory=BudgetCfg)
    concurrency: ConcurrencyCfg = Field(default_factory=ConcurrencyCfg)
    retries: RetriesCfg = Field(default_factory=RetriesCfg)
    failure: FailureCfg = Field(default_factory=FailureCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)


class Niche(BaseModel):
    id: str
    name: str
    covers: str
    not_for: str
    seed_queries: list[str]


class NicheConfig(BaseModel):
    niches: list[Niche]
    global_seed_queries: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "NicheConfig":
        seen: set[str] = set()
        for niche in self.niches:
            if niche.id in seen:
                raise ValueError(f"duplicate niche id: {niche.id}")
            seen.add(niche.id)
        return self

    def ids(self) -> list[str]:
        return [niche.id for niche in self.niches]

    def all_queries(self) -> list[str]:
        queries = [q for niche in self.niches for q in niche.seed_queries] + self.global_seed_queries
        return list(dict.fromkeys(queries))


def load_settings(path: Path) -> Settings:
    return Settings.model_validate(yaml.safe_load(Path(path).read_text()) or {})


def load_niches(path: Path) -> NicheConfig:
    return NicheConfig.model_validate(yaml.safe_load(Path(path).read_text()))


def parse_weights(text: str) -> dict[str, float]:
    """Parses 'momentum=0.3,pain=0.2,...' into a weights dict validated by RankingCfg."""
    weights: dict[str, float] = {}
    for part in text.split(","):
        key, _, raw = part.partition("=")
        weights[key.strip()] = float(raw)
    return RankingCfg(weights=weights).weights

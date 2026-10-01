"""Run state for the UGC pipeline: V1's recording and Jev helpers with the UGC config and clients (spec §5.2)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from jevtrends.budget import BudgetGuard
from jevtrends.http import FatalAPIError
from jevtrends.llm.client import ImagePart, LLMResult
from jevtrends.sources.base import UgcSource
from jevtrends.stages.context import ContextHelpers, JevLike, LLMLike
from jevtrends.ugc.config import NicheProfile, ProductProfile, UgcSettings
from jevtrends.ugc.store import UgcStore


class VisionLike(Protocol):
    model: str

    async def complete_json(self, system: str, user: str, schema: type, max_tokens: int,
                            validate: Callable | None = None, images: list[ImagePart] | None = None) -> LLMResult: ...


class ImagesLike(Protocol):
    async def fetch(self, url: str, max_bytes: int) -> bytes | None: ...


def is_account_error(exc: BaseException) -> bool:
    """A rejected key or exhausted credits: the only errors from optional sources that still stop a run (§12.2)."""
    return isinstance(exc, FatalAPIError) and exc.status in (401, 402)


@dataclass
class UgcRunContext(ContextHelpers):
    run_id: int
    store: UgcStore
    settings: UgcSettings
    niche: NicheProfile
    product: ProductProfile | None
    source: UgcSource
    jev: JevLike
    llm: LLMLike
    vision: VisionLike
    images: ImagesLike
    budget: BudgetGuard | None
    now: datetime
    limits: dict[str, int] = field(default_factory=dict)

    def record_vision(self, stage: str, input_tokens: int, output_tokens: int, cost_usd: float | None) -> None:
        pricing = self.settings.pricing
        if cost_usd is None:
            cost_usd = (input_tokens * pricing.vision_input_per_mtok
                        + output_tokens * pricing.vision_output_per_mtok) / 1e6
        self.store.record_api_call(self.run_id, stage, "vision", "chat",
                                   {"input_tokens": input_tokens, "output_tokens": output_tokens}, cost_usd, "ok")


def ugc_report_context(store: UgcStore, run_id: int) -> UgcRunContext:
    """Read-only context for reports, reviews and budget checks; no API clients are needed."""
    run = store.get_run(run_id)
    return UgcRunContext(run_id=run_id, store=store, settings=run["settings"], niche=run["niche"],
                         product=run["product"], source=None, jev=None, llm=None, vision=None, images=None,
                         budget=None, now=run["started_at"])

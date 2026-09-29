"""Shared run state and helpers for pipeline stages."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from jevtrends.budget import BudgetGuard
from jevtrends.config import NicheConfig, Settings
from jevtrends.http import FatalAPIError, TransientAPIError
from jevtrends.jev.client import JevResult
from jevtrends.jev.questions import Question, payload
from jevtrends.llm.client import LLMOutputError, LLMResult
from jevtrends.models import Answer
from jevtrends.sources.base import Source
from jevtrends.store import Store


class JevLike(Protocol):
    async def ask(self, state: dict, questions: dict[str, dict]) -> JevResult: ...


class LLMLike(Protocol):
    model: str

    async def complete_json(self, system: str, user: str, schema: type, max_tokens: int,
                            validate: Callable | None = None) -> LLMResult: ...


class StageFailed(Exception):
    """More than failure.max_item_failure_rate of a stage's items failed (spec §12.2)."""


@dataclass
class RunContext:
    run_id: int
    store: Store
    settings: Settings
    niches: NicheConfig
    source: Source
    jev: JevLike
    llm: LLMLike
    budget: BudgetGuard
    now: datetime
    limits: dict[str, int] = field(default_factory=dict)

    def record_jev(self, stage: str, result: JevResult) -> None:
        cost = result.input_tokens * self.settings.pricing.jev_input_per_mtok / 1e6
        self.store.record_api_call(self.run_id, stage, "jev", "systemone",
                                   {"input_tokens": result.input_tokens}, cost, "ok")

    def record_llm(self, stage: str, input_tokens: int, output_tokens: int, cost_usd: float | None) -> None:
        pricing = self.settings.pricing
        if cost_usd is None:
            cost_usd = (input_tokens * pricing.llm_input_per_mtok + output_tokens * pricing.llm_output_per_mtok) / 1e6
        self.store.record_api_call(self.run_id, stage, "llm", "chat",
                                   {"input_tokens": input_tokens, "output_tokens": output_tokens}, cost_usd, "ok")

    def record_scraper(self, stage: str, endpoint: str, credits: int) -> None:
        self.store.record_api_call(self.run_id, stage, "scrapecreators", endpoint, {"credits": credits},
                                   credits * self.settings.pricing.scrapecreators_per_credit, "ok")

    def record_failure(self, stage: str, provider: str, item: str, error: str) -> None:
        self.store.record_api_call(self.run_id, stage, provider, stage, {"item": item, "error": error[:300]},
                                   0.0, "failed")

    async def ask_jev(self, stage: str, subject_type: str, subject_id: str, state: dict,
                      questions: list[Question]) -> dict[str, Answer]:
        result = await self.jev.ask(state, payload(questions))
        self.record_jev(stage, result)
        for question in questions:
            self.store.upsert_judgment(self.run_id, subject_type, subject_id, question.id, question.version,
                                       result.answers[question.key])
        return {question.key: result.answers[question.key] for question in questions}

    def answers(self, question: Question, subject_type: str = "video") -> dict[str, Answer]:
        return self.store.get_answers(self.run_id, subject_type, question.id, question.version)


async def run_items(ctx: RunContext, stage: str, provider: str, items: Sequence,
                    fn: Callable[[object], Awaitable[None]], concurrency: int, total: int | None = None) -> int:
    """Runs fn(item) with bounded concurrency; item failures are recorded and counted.

    The failure rate is measured against the stage's whole item count (`total`), so a resumed attempt that only
    retries the leftovers is not judged by those leftovers alone.
    """
    semaphore = asyncio.Semaphore(concurrency)
    failures = 0

    async def one(item: object) -> None:
        nonlocal failures
        async with semaphore:
            try:
                await fn(item)
            except FatalAPIError:
                raise
            except (TransientAPIError, LLMOutputError, ValueError, KeyError) as exc:
                failures += 1
                ctx.record_failure(stage, provider, str(item), repr(exc))

    try:
        async with asyncio.TaskGroup() as group:
            for item in items:
                group.create_task(one(item))
    except* FatalAPIError as group_error:
        raise group_error.exceptions[0] from None
    if items and failures / max(len(items), total or 0) > ctx.settings.failure.max_item_failure_rate:
        raise StageFailed(f"{stage}: {failures} of {len(items)} items failed")
    return failures

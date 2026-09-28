"""Deterministic stand-ins for ScrapeCreators, Jev and the LLM, plus a RunContext factory."""

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from jevtrends.budget import BudgetGuard
from jevtrends.config import NicheConfig, Settings
from jevtrends.jev.client import JevResult
from jevtrends.llm.client import LLMOutputError, LLMResult
from jevtrends.models import Answer, Comment, Video
from jevtrends.sources.base import CommentsResult, SearchPage, TranscriptResult
from jevtrends.stages.context import RunContext
from jevtrends.store import Store

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


class FakeSource:
    def __init__(self, pages: dict[str, list[list[Video]]] | None = None,
                 transcripts: dict[str, str | None] | None = None,
                 comments: dict[str, list[Comment]] | None = None):
        self.pages = pages or {}
        self.transcripts = transcripts or {}
        self.comments_by_video = comments or {}
        self.calls: list[tuple] = []

    async def search(self, query: str, lookback_days: int, region: str, cursor: int | None = None) -> SearchPage:
        self.calls.append(("search", query, cursor))
        pages = self.pages.get(query, [])
        index = cursor or 0
        videos = pages[index] if index < len(pages) else []
        return SearchPage(videos=videos, next_cursor=index + 1 if index + 1 < len(pages) else None, credits=1)

    async def transcript(self, video: Video) -> TranscriptResult:
        self.calls.append(("transcript", video.id))
        return TranscriptResult(text=self.transcripts.get(video.id), credits=1)

    async def comments(self, video: Video, limit: int, max_chars: int) -> CommentsResult:
        self.calls.append(("comments", video.id))
        return CommentsResult(comments=self.comments_by_video.get(video.id, [])[:limit], credits=1)


class FakeJev:
    """Answers any question. rules maps a question key (or "niche_*") to fn(state, key) -> value.

    Defaults: noul 0.9, choice = first option, score 1.0. fail_when(state, questions) may return an exception to raise.
    """

    def __init__(self, rules: dict[str, Callable] | None = None, fail_when: Callable | None = None):
        self.rules = rules or {}
        self.fail_when = fail_when
        self.calls: list[tuple[dict, dict]] = []

    async def ask(self, state: dict, questions: dict[str, dict]) -> JevResult:
        self.calls.append((state, questions))
        if self.fail_when and (exc := self.fail_when(state, questions)):
            raise exc
        answers = {}
        for key, body in questions.items():
            rule = self.rules.get(key) or (self.rules.get("niche_*") if key.startswith("niche_") else None)
            if body["type"] == "choice":
                options = list(body["criteria"])
                value = rule(state, key) if rule else options[0]
                rest = 0.1 / max(1, len(options) - 1)
                answers[key] = Answer(value=value, probabilities={o: 0.9 if o == value else rest for o in options},
                                      confidence=0.9)
            elif body["type"] == "score":
                answers[key] = Answer(value=float(rule(state, key)) if rule else 1.0, probabilities={}, confidence=0.8)
            else:
                answers[key] = Answer(value=float(rule(state, key)) if rule else 0.9)
        return JevResult(answers=answers, input_tokens=100)


class FakeLLM:
    model = "fake-llm"

    def __init__(self, responder: Callable[[str, str, type], BaseModel]):
        self.responder = responder
        self.calls: list[tuple[str, str, type]] = []

    async def complete_json(self, system: str, user: str, schema: type, max_tokens: int,
                            validate: Callable | None = None) -> LLMResult:
        self.calls.append((system, user, schema))
        parsed = self.responder(system, user, schema)
        errors = validate(parsed) if validate else []
        if errors:
            raise LLMOutputError("; ".join(errors), 1000, 200, None)
        return LLMResult(parsed=parsed, input_tokens=1000, output_tokens=200, cost_usd=None)


def make_ctx(source=None, jev=None, llm=None, niches: NicheConfig | None = None,
             settings: Settings | None = None, store: Store | None = None, run_id: int | None = None) -> RunContext:
    settings = settings or Settings()
    niches = niches or test_niches()
    store = store or Store(":memory:")
    if run_id is None:
        run_id = store.create_run({"lookback_days": settings.scan.lookback_days}, settings, niches, NOW)
    return RunContext(run_id=run_id, store=store, settings=settings, niches=niches, source=source or FakeSource(),
                      jev=jev or FakeJev(), llm=llm or FakeLLM(lambda *a: None),
                      budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=NOW)

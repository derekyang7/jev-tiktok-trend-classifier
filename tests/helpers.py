"""Shared test helpers and deterministic stand-ins for ScrapeCreators, Jev, and the LLM."""

from collections.abc import Callable
import contextlib
from datetime import UTC, datetime
import sys

from pydantic import BaseModel

from jevtrends.core.http import TransientAPIError
from jevtrends.core.jev import JevResult
from jevtrends.core.llm import LLMOutputError, LLMResult
from jevtrends.core.models import Answer, Comment, Enrichment, SoundInfo, Video, VisionRead
from jevtrends.core.sources.base import CommentsResult, SearchPage, TranscriptResult

with contextlib.suppress(ImportError):
    import jevtrends.models as _legacy_models

    for _name, _cls in (("Answer", Answer), ("Comment", Comment), ("Enrichment", Enrichment),
                        ("SoundInfo", SoundInfo), ("Video", Video), ("VisionRead", VisionRead)):
        setattr(_legacy_models, _name, _cls)
        for _mod_name, _mod in list(sys.modules.items()):
            if _mod_name.startswith("jevtrends") and hasattr(_mod, _name):
                setattr(_mod, _name, _cls)


def make_video(**overrides) -> Video:
    vid = overrides.pop("id", "7000000000000000001")
    handle = overrides.pop("author_handle", "creator1")
    fields = {
        "id": vid,
        "url": f"https://www.tiktok.com/@{handle}/video/{vid}",
        "author_id": overrides.pop("author_id", f"uid-{handle}"),
        "author_handle": handle,
        "caption": "My bank app is useless #budgeting",
        "hashtags": ["budgeting"],
        "posted_at": datetime(2026, 9, 20, tzinfo=UTC),
        "views": 1000,
        "likes": 100,
        "comment_count": 10,
    }
    fields.update(overrides)
    if isinstance(fields.get("sound_info"), BaseModel) and not isinstance(fields["sound_info"], SoundInfo):
        fields["sound_info"] = SoundInfo.model_validate(fields["sound_info"].model_dump())
    return Video(**fields)


class FakeSource:
    def __init__(self, pages: dict[str, list[list[Video]]] | None = None,
                 transcripts: dict[str, str | None] | None = None,
                 comments: dict[str, list[Comment]] | None = None,
                 fail_pages: set[tuple[str, int]] | None = None):
        self.pages = pages or {}
        self.fail_pages = fail_pages or set()  # (query, page index) pairs whose search raises a transient error
        self.transcripts = transcripts or {}
        self.comments_by_video = comments or {}
        self.calls: list[tuple] = []

    async def search(self, query: str, lookback_days: int, region: str, cursor: int | None = None) -> SearchPage:
        self.calls.append(("search", query, cursor))
        pages = self.pages.get(query, [])
        index = cursor or 0
        if (query, index) in self.fail_pages:
            raise TransientAPIError("scrapecreators", 503, "boom")
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

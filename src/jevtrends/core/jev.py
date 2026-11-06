"""Jev (TypeSafe System One) client via TypeSafe or OpenRouter and shared question primitives (spec §4.1, §7)."""

from dataclasses import dataclass

import httpx

from jevtrends.core.config import RetriesCfg
from jevtrends.core.http import send_with_retry
from jevtrends.core.models import Answer

JEV_URL = "https://openrouter.ai/api/v1/systemone"  # change here if Task 1 found a different endpoint
TYPESAFE_JEV_URL = "https://api.typesafe.ai/v1/systemone"
NONE_OF_THESE = "none_of_these"


@dataclass(frozen=True)
class Question:
    stage: str
    key: str
    version: int
    body: dict

    @property
    def id(self) -> str:
        return f"{self.stage}.{self.key}"


def payload(questions: list[Question]) -> dict[str, dict]:
    return {q.key: q.body for q in questions}


IS_PROMOTIONAL = Question("judge", "is_promotional", 1, {
    "type": "noul",
    "instructions": "Was this video made mainly to sell something: an ad, a sponsorship, an affiliate or TikTok Shop "
                    "pitch, or a creator or founder promoting their own product?",
    "criteria": {
        "true": "Paid-partnership disclosure, discount codes, affiliate or shop links, 'link in bio' sales pitches, or "
                "the creator selling their own product.",
        "false": "Organic content; any products shown are not being sold by the creator.",
    },
})


@dataclass
class JevResult:
    answers: dict[str, Answer]
    input_tokens: int


def parse_answer(raw: dict) -> Answer:
    kind = raw.get("type")
    if kind == "noul":
        return Answer(value=float(raw["noul"]))
    if kind == "choice":
        return Answer(value=str(raw["choice"]), probabilities=raw.get("probabilities"),
                      confidence=raw.get("confidence"))
    if kind == "score":
        return Answer(value=float(raw["score"]), probabilities=raw.get("probabilities"),
                      confidence=raw.get("confidence"))
    raise ValueError(f"unknown Jev answer type: {kind!r}")


class JevClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str, retries: RetriesCfg, url: str = JEV_URL):
        self.client = client
        self.api_key = api_key
        self.url = url
        self.model = model.removeprefix("typesafe/") if url == TYPESAFE_JEV_URL else model
        self.retries = retries

    @classmethod
    def from_keys(cls, client: httpx.AsyncClient, keys: dict[str, str], model: str,
                  retries: RetriesCfg) -> "JevClient":
        if typesafe_key := keys.get("TYPESAFE_API_KEY", "").strip():
            return cls(client, typesafe_key, model, retries, url=TYPESAFE_JEV_URL)
        return cls(client, keys["OPENROUTER_API_KEY"], model, retries, url=JEV_URL)

    async def ask(self, state: dict, questions: dict[str, dict]) -> JevResult:
        response = await send_with_retry(
            self.client, "jev", "POST", self.url, retries=self.retries,
            json={"model": self.model, "state": state, "questions": questions},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        data = response.json()
        answers = {key: parse_answer(raw) for key, raw in (data.get("answers") or {}).items()}
        missing = sorted(set(questions) - set(answers))
        if missing:
            raise ValueError(f"Jev response missing answers: {missing}")
        return JevResult(answers=answers, input_tokens=int((data.get("usage") or {}).get("input_tokens", 0)))

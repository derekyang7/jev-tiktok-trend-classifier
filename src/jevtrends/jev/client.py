"""Jev (TypeSafe System One) client via OpenRouter (spec §4.1)."""

from dataclasses import dataclass

import httpx

from jevtrends.config import RetriesCfg
from jevtrends.http import send_with_retry
from jevtrends.models import Answer

JEV_URL = "https://openrouter.ai/api/v1/systemone"  # change here if Task 1 found a different endpoint


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
        self.model = model
        self.retries = retries
        self.url = url

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

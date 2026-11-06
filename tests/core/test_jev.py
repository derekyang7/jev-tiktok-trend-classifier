import json
from pathlib import Path

import httpx
import pytest

from jevtrends.core.config import RetriesCfg
from jevtrends.core.jev import (IS_PROMOTIONAL, JEV_URL, NONE_OF_THESE, TYPESAFE_JEV_URL, JevClient, Question,
                                parse_answer, payload)
from jevtrends.core.models import Answer

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "opportunities" / "jev_systemone.json"
GATE_Q = Question("gate", "maybe_signal", 1, {"type": "noul", "instructions": "Might this video show a signal?"})


def test_parse_answer_types():
    assert parse_answer({"type": "noul", "noul": 0.93}) == Answer(value=0.93)
    choice = parse_answer({"type": "choice", "choice": "a", "probabilities": {"a": 0.9, "b": 0.1}, "confidence": 0.8})
    assert (choice.value, choice.probabilities["b"], choice.confidence) == ("a", 0.1, 0.8)
    score = parse_answer({"type": "score", "score": 1.43, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
                          "legend": {"0": "x"}, "confidence": 0.4})
    assert score.value == 1.43
    with pytest.raises(ValueError):
        parse_answer({"type": "mystery"})


def test_question_primitives():
    assert GATE_Q.id == "gate.maybe_signal" and GATE_Q.version == 1
    assert payload([GATE_Q, IS_PROMOTIONAL]) == {"maybe_signal": GATE_Q.body, "is_promotional": IS_PROMOTIONAL.body}
    assert NONE_OF_THESE == "none_of_these"


async def test_ask_posts_model_state_questions_and_parses_usage():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "jev-1.13", "answers": {"maybe_signal": {"type": "noul", "noul": 0.7}},
                                         "usage": {"input_tokens": 321, "output_tokens": 5}})

    client = JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "typesafe/jev-1.13",
                       RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == JEV_URL
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "typesafe/jev-1.13"
    assert seen["body"]["state"] == {"caption": "hi"}
    assert seen["body"]["questions"]["maybe_signal"]["type"] == "noul"
    assert result.answers["maybe_signal"].value == 0.7
    assert result.input_tokens == 321


async def test_from_keys_prefers_typesafe_and_strips_model_prefix():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "jev-1.13", "answers": {"maybe_signal": {"type": "noul", "noul": 0.8}},
                                         "usage": {"input_tokens": 120, "output_tokens": 12}})

    keys = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k", "TYPESAFE_API_KEY": "ts-k"}
    client = JevClient.from_keys(httpx.AsyncClient(transport=httpx.MockTransport(handler)), keys, "typesafe/jev-1.13",
                                 RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == TYPESAFE_JEV_URL == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer ts-k"
    assert seen["body"]["model"] == "jev-1.13"
    assert result.answers["maybe_signal"].value == 0.8
    assert result.input_tokens == 120


async def test_from_keys_falls_back_to_openrouter_when_typesafe_key_absent():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "typesafe/jev-1.13",
                                         "answers": {"maybe_signal": {"type": "noul", "noul": 0.6}},
                                         "usage": {"input_tokens": 200, "output_tokens": 8}})

    keys = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k"}
    client = JevClient.from_keys(httpx.AsyncClient(transport=httpx.MockTransport(handler)), keys, "typesafe/jev-1.13",
                                 RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == JEV_URL
    assert seen["auth"] == "Bearer or-k"
    assert seen["body"]["model"] == "typesafe/jev-1.13"
    assert result.input_tokens == 200


async def test_ask_rejects_missing_answers():
    handler = lambda request: httpx.Response(200, json={"answers": {}, "usage": {"input_tokens": 1}})  # noqa: E731
    client = JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "m", RetriesCfg(max_attempts=1))
    with pytest.raises(ValueError, match="missing answers"):
        await client.ask({}, payload([GATE_Q]))


@pytest.mark.skipif(not CONTRACT.exists(), reason="Task 1 fixtures not recorded")
def test_parses_recorded_contract_fixture():
    answers = json.loads(CONTRACT.read_text())["response"]["answers"]
    parsed = {key: parse_answer(raw) for key, raw in answers.items()}
    assert set(parsed) == {"is_complaint", "topic", "pain"}

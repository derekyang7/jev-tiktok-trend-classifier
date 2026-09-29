import json
from pathlib import Path

import httpx
import pytest

from jevtrends.config import Niche, RetriesCfg
from jevtrends.jev.client import JEV_URL, JevClient, parse_answer
from jevtrends.jev.questions import (MAYBE_SIGNAL, NONE_OF_THESE, TREND_QUESTIONS, assign_question, judge_questions,
                                     payload)
from jevtrends.models import Answer, Trend

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "jev_systemone.json"
NICHES = [Niche(id="ai", name="AI", covers="AI tools", not_for="tech news", seed_queries=["ai"]),
          Niche(id="fintech_payments", name="Fintech & payments", covers="money", not_for="shopping", seed_queries=["x"])]


def test_parse_answer_types():
    assert parse_answer({"type": "noul", "noul": 0.93}) == Answer(value=0.93)
    choice = parse_answer({"type": "choice", "choice": "a", "probabilities": {"a": 0.9, "b": 0.1}, "confidence": 0.8})
    assert (choice.value, choice.probabilities["b"], choice.confidence) == ("a", 0.1, 0.8)
    score = parse_answer({"type": "score", "score": 1.43, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
                          "legend": {"0": "x"}, "confidence": 0.4})
    assert score.value == 1.43
    with pytest.raises(ValueError):
        parse_answer({"type": "mystery"})


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
    result = await client.ask({"caption": "hi"}, payload([MAYBE_SIGNAL]))
    assert seen["url"] == JEV_URL
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "typesafe/jev-1.13"
    assert seen["body"]["state"] == {"caption": "hi"}
    assert seen["body"]["questions"]["maybe_signal"]["type"] == "noul"
    assert result.answers["maybe_signal"].value == 0.7
    assert result.input_tokens == 321


async def test_ask_rejects_missing_answers():
    handler = lambda request: httpx.Response(200, json={"answers": {}, "usage": {"input_tokens": 1}})  # noqa: E731
    client = JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "m", RetriesCfg(max_attempts=1))
    with pytest.raises(ValueError, match="missing answers"):
        await client.ask({}, payload([MAYBE_SIGNAL]))


def test_question_catalog():
    assert MAYBE_SIGNAL.id == "gate.maybe_signal" and MAYBE_SIGNAL.version == 1
    assert MAYBE_SIGNAL.body["instructions"].startswith("Might this video show or discuss")
    judge = judge_questions(NICHES)
    assert [q.key for q in judge] == ["is_signal", "signal_type", "is_promotional", "niche_ai", "niche_fintech_payments"]
    niche_body = judge[3].body
    assert niche_body["type"] == "noul"
    assert niche_body["instructions"]["niche"] == {"name": "AI", "covers": "AI tools", "not_for": "tech news"}
    assert set(judge[1].body["criteria"]) == {"behavior_need", "product_traction", "complaint_workaround", "other"}
    assert [q.key for q in TREND_QUESTIONS] == ["pain", "spend", "underserved", "mentions_solutions"]
    assert all(len(q.body["criteria"]) == 4 for q in TREND_QUESTIONS if q.body["type"] == "score")


def test_assign_question_lists_trends_and_none_option():
    trends = [Trend(trend_id="t01", name="Rent splitting", kind="behavior_need", definition="Roommates split bills.",
                    includes=["utilities"], excludes=["couples"]),
              Trend(trend_id="t02", name="AI calorie apps", kind="product_traction", definition="Apps that log food.")]
    question = assign_question(trends)
    criteria = question.body["criteria"]
    assert question.id == "assign.trend"
    assert list(criteria) == ["t01", "t02", NONE_OF_THESE]
    assert criteria["t01"] == {"what": "Rent splitting. Roommates split bills. Includes: utilities.", "not_for": "couples"}
    assert criteria["t02"] == {"what": "AI calorie apps. Apps that log food."}


@pytest.mark.skipif(not CONTRACT.exists(), reason="Task 1 fixtures not recorded")
def test_parses_recorded_contract_fixture():
    answers = json.loads(CONTRACT.read_text())["response"]["answers"]
    parsed = {key: parse_answer(raw) for key, raw in answers.items()}
    assert set(parsed) == {"is_complaint", "topic", "pain"}


def test_question_wording_matches_spec_verbatim():
    from jevtrends.jev import questions as q

    root = Path(__file__).resolve().parents[2]
    spec = " ".join((root / "docs/superpowers/specs/2026-09-28-tiktok-trend-classifier-design.md").read_text().split())
    texts: list[str] = []

    def walk(node):
        if isinstance(node, str):
            texts.append(" ".join(node.split()))
        elif isinstance(node, dict):
            for key, value in node.items():
                if key != "type":
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for question in [q.MAYBE_SIGNAL, q.IS_SIGNAL, q.SIGNAL_TYPE, q.IS_PROMOTIONAL, *q.TREND_QUESTIONS]:
        walk(question.body)
    assert [t for t in texts if t not in spec and t.rstrip(".") not in spec] == []

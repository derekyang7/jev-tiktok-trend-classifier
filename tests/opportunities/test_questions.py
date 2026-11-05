from pathlib import Path

from jevtrends.core.jev import IS_PROMOTIONAL, NONE_OF_THESE
from jevtrends.opportunities import questions as q
from jevtrends.opportunities.config import Niche
from jevtrends.opportunities.models import Trend
from jevtrends.opportunities.questions import MAYBE_SIGNAL, TREND_QUESTIONS, assign_question, judge_questions

NICHES = [Niche(id="ai", name="AI", covers="AI tools", not_for="tech news", seed_queries=["ai"]),
          Niche(id="fintech_payments", name="Fintech & payments", covers="money", not_for="shopping", seed_queries=["x"])]


def test_question_catalog():
    assert MAYBE_SIGNAL.id == "gate.maybe_signal" and MAYBE_SIGNAL.version == 1
    assert MAYBE_SIGNAL.body["instructions"].startswith("Might this video show or discuss")
    judge = judge_questions(NICHES)
    assert [question.key for question in judge] == [
        "is_signal", "signal_type", "is_promotional", "niche_ai", "niche_fintech_payments"]
    niche_body = judge[3].body
    assert niche_body["type"] == "noul"
    assert niche_body["instructions"]["niche"] == {"name": "AI", "covers": "AI tools", "not_for": "tech news"}
    assert set(judge[1].body["criteria"]) == {"behavior_need", "product_traction", "complaint_workaround", "other"}
    assert [question.key for question in TREND_QUESTIONS] == ["pain", "spend", "underserved", "mentions_solutions"]
    assert all(len(question.body["criteria"]) == 4 for question in TREND_QUESTIONS if question.body["type"] == "score")


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


def test_question_wording_matches_spec_verbatim():
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

    for question in [q.MAYBE_SIGNAL, q.IS_SIGNAL, q.SIGNAL_TYPE, IS_PROMOTIONAL, *q.TREND_QUESTIONS]:
        walk(question.body)
    assert [t for t in texts if t not in spec and t.rstrip(".") not in spec] == []

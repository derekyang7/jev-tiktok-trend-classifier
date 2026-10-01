from jevtrends.jev.questions import IS_PROMOTIONAL, NONE_OF_THESE, payload
from jevtrends.ugc.config import NicheProfile
from jevtrends.ugc.models import FacetTrend
from jevtrends.ugc.questions import (BRAND_RISK, EASE, FIT, PRODUCT_FIT, PROMOTIONAL, assign_question, gate_question,
                                     relevant_question, sound_relevant_question, trend_questions)

NICHE = NicheProfile(id="apps", name="Consumer apps", covers="Everyday apps", not_for="Business software",
                     audience="Young adults", seed_queries=["q"])


def test_relevance_questions_carry_the_niche_and_have_distinct_ids():
    gate, judge, sounds = gate_question(NICHE), relevant_question(NICHE), sound_relevant_question(NICHE)
    assert (gate.id, judge.id, sounds.id) == ("ugc_gate.relevant", "ugc_judge.relevant", "ugc_sounds.relevant")
    assert gate.body["instructions"]["niche"] == {"name": "Consumer apps", "covers": "Everyday apps",
                                                  "not_for": "Business software"}
    assert judge.body["instructions"]["niche"]["audience"] == "Young adults"
    assert judge.body == sounds.body and gate.body["type"] == "noul"
    assert judge.body["instructions"]["question"] == "Is this video about the niche described in `niche`?"
    assert set(gate.body["criteria"]) == {"true", "false"}
    assert PROMOTIONAL.id == "ugc_judge.is_promotional" and PROMOTIONAL.body == IS_PROMOTIONAL.body


def test_assign_question_lists_candidates_templates_and_none():
    trends = [FacetTrend(trend_id="h01", facet="hook", name="POV discovery", definition="Opens with POV.",
                         includes=["POV:"], excludes=["reaction"], template="POV: you finally found an app that ___"),
              FacetTrend(trend_id="h02", facet="hook", name="Illegal to know", definition="Secret apps.")]
    question = assign_question("hook", trends)
    assert (question.id, question.version, question.key) == ("ugc_assign.hook", 1, "hook")
    body = question.body
    assert body["type"] == "choice" and list(body["criteria"]) == ["h01", "h02", NONE_OF_THESE]
    assert body["criteria"]["h01"] == {
        "what": "POV discovery. Opens with POV. Includes: POV:. Template: POV: you finally found an app that ___.",
        "not_for": "reaction"}
    assert body["criteria"]["h02"] == {"what": "Illegal to know. Secret apps."}
    assert body["instructions"].startswith("Which of these hooks does this video open with")


def test_trend_questions_switch_fit_for_product_fit():
    assert [q.key for q in trend_questions(with_product=False)] == ["fit", "ease", "brand_risk"]
    assert [q.key for q in trend_questions(with_product=True)] == ["product_fit", "ease", "brand_risk"]
    for question in (FIT, PRODUCT_FIT, EASE):
        assert question.body["type"] == "score" and len(question.body["criteria"]) == 4
    assert BRAND_RISK.body["type"] == "noul"
    assert set(payload(trend_questions(False))) == {"fit", "ease", "brand_risk"}

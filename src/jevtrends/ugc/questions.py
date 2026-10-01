"""Jev question catalog for the UGC version (UGC spec §7). Wording is verbatim; bump `version` whenever it changes."""

from jevtrends.jev.questions import IS_PROMOTIONAL, NONE_OF_THESE, Question
from jevtrends.ugc.config import NicheProfile
from jevtrends.ugc.models import FacetTrend


def niche_object(niche: NicheProfile, with_audience: bool) -> dict:
    obj = {"name": niche.name, "covers": niche.covers, "not_for": niche.not_for}
    if with_audience and niche.audience:
        obj["audience"] = niche.audience
    return obj


def gate_question(niche: NicheProfile) -> Question:
    return Question("ugc_gate", "relevant", 1, {
        "type": "noul",
        "instructions": {
            "question": "Could this video be about the niche described in `niche`, judging by its caption and "
                        "hashtags?",
            "niche": niche_object(niche, with_audience=False),
        },
        "criteria": {
            "true": "The caption or hashtags mention or hint at anything the niche covers, even vaguely, or give too "
                    "little information to tell.",
            "false": "The caption and hashtags clearly point to something the niche does not cover.",
        },
    })


def _relevant_body(niche: NicheProfile) -> dict:
    return {
        "type": "noul",
        "instructions": {"question": "Is this video about the niche described in `niche`?",
                         "niche": niche_object(niche, with_audience=True)},
        "criteria": {
            "true": "The video's main subject is something the niche covers: its products, how people use them, or "
                    "the needs, habits and conversations of the niche's audience.",
            "false": "The niche appears only in passing, or the video is about something else.",
        },
    }


def relevant_question(niche: NicheProfile) -> Question:
    return Question("ugc_judge", "relevant", 1, _relevant_body(niche))


def sound_relevant_question(niche: NicheProfile) -> Question:
    """J1's wording for a sampled song video's caption and hashtags; its own id keeps answers apart from J1's."""
    return Question("ugc_sounds", "relevant", 1, _relevant_body(niche))


PROMOTIONAL = Question("ugc_judge", "is_promotional", 1, IS_PROMOTIONAL.body)

ASSIGN_INSTRUCTIONS = {
    "format": "Which of these video formats does this video use?",
    "hook": "Which of these hooks does this video open with, in its first spoken line or on-screen text?",
    "topic": "Which of these topics, memes or moments is this video mainly about?",
    "need": "Which of these audience needs, pain points or wishes does this video mainly express or respond to?",
}


def assign_question(facet: str, trends: list[FacetTrend]) -> Question:
    criteria: dict[str, dict] = {}
    for trend in trends:
        what = f"{trend.name}. {trend.definition}"
        if trend.includes:
            what += f" Includes: {'; '.join(trend.includes)}."
        if trend.template:
            what += f" Template: {trend.template}."
        option = {"what": what}
        if trend.excludes:
            option["not_for"] = "; ".join(trend.excludes)
        criteria[trend.trend_id] = option
    criteria[NONE_OF_THESE] = {"what": "None of the options clearly fits this video."}
    return Question("ugc_assign", facet, 1, {"type": "choice", "instructions": ASSIGN_INSTRUCTIONS[facet],
                                             "criteria": criteria})


FIT = Question("ugc_trend", "fit", 1, {
    "type": "score",
    "instructions": "How naturally could a brand in this `niche` use this `trend` in an ad or a sponsored creator "
                    "video?",
    "criteria": [
        "It would feel forced or off-brand for almost any brand in the niche.",
        "Possible, with a stretch, for a few brands.",
        "A natural fit for many brands in the niche.",
        "Made for it: brands in the niche could use it almost as is, or already do.",
    ],
})

PRODUCT_FIT = Question("ugc_trend", "product_fit", 1, {
    "type": "score",
    "instructions": "How naturally could this `product` feature in a video that uses this `trend`?",
    "criteria": [
        "The product would feel forced or out of place.",
        "It could appear, but only with a stretch.",
        "It fits naturally as a supporting element.",
        "The trend is an ideal way to show the product's main benefit.",
    ],
})

EASE = Question("ugc_trend", "ease", 1, {
    "type": "score",
    "instructions": "How easily could one creator with a phone make a video that uses this `trend`?",
    "criteria": [
        "It needs a production team, special locations, celebrities, or skills few creators have.",
        "It needs props, several people, or careful editing.",
        "One creator can do it with some setup or editing.",
        "One creator, a phone, and under an hour.",
    ],
})

BRAND_RISK = Question("ugc_trend", "brand_risk", 1, {
    "type": "noul",
    "instructions": "Could using this `trend` in an ad embarrass or harm a brand?",
    "criteria": {
        "true": "It involves offensive, sexual or shocking content, politics, tragedy, mocking a person or group, "
                "dangerous acts, or copyrighted characters.",
        "false": "Ordinary content that is safe for brands.",
    },
})


def trend_questions(with_product: bool) -> list[Question]:
    return [PRODUCT_FIT if with_product else FIT, EASE, BRAND_RISK]

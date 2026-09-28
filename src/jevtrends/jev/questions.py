"""Jev question catalog (spec §7). Wording is verbatim; bump `version` whenever wording changes."""

from dataclasses import dataclass

from jevtrends.config import Niche
from jevtrends.models import Trend

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


MAYBE_SIGNAL = Question("gate", "maybe_signal", 1, {
    "type": "noul",
    "instructions": "Might this video show or discuss a real-life behavior, need, product, app, service or "
                    "frustration, rather than being pure entertainment?",
    "criteria": {
        "true": "The caption or hashtags hint at a product, app, service, habit, routine, money, health, work, "
                "business or a problem someone has, even vaguely, or give too little information to tell.",
        "false": "Clearly entertainment only: a dance, lip-sync, skit, prank, meme, music, fandom or gossip, with no "
                 "hint of a real-world need, product or problem.",
    },
})

IS_SIGNAL = Question("judge", "is_signal", 1, {
    "type": "noul",
    "instructions": "Does this video give real evidence of what people do, want, buy or struggle with, something that "
                    "could inform what a startup builds?",
    "criteria": {
        "true": "Shows or describes a concrete behavior, habit, need, purchase, product experience, complaint or "
                "improvised workaround, first-hand or clearly observed in others, including in the comments.",
        "false": "Entertainment, generic motivation, news or opinion with no concrete behavior, need, product or "
                 "frustration.",
    },
})

SIGNAL_TYPE = Question("judge", "signal_type", 1, {
    "type": "choice",
    "instructions": "What kind of real-world signal does this video mainly provide?",
    "criteria": {
        "behavior_need": {
            "what": "People doing, wanting or trying to achieve something in everyday life, work, money or health: "
                    "a habit, routine, hack, goal or desire.",
            "not_for": "Enthusiasm for one specific named product; frustration with existing options.",
            "examples": ["My 5am routine for tracking my glucose", "How we split rent and bills as three roommates"],
        },
        "product_traction": {
            "what": "A specific named product, app, tool or service getting enthusiasm or adoption: recommendations, "
                    "reviews, results, or people asking where to get it.",
            "not_for": "General habits not tied to a named product.",
            "examples": ["This AI calorie app got me 20 lbs down",
                         "comments full of \"what's the name of this app?\""],
        },
        "complaint_workaround": {
            "what": "Frustration with an existing product, service, company or process, or an improvised fix because "
                    "nothing good exists.",
            "not_for": "Mild preferences with no real problem.",
            "examples": ["My bank's app is useless so I track everything in five spreadsheets",
                         "Why is there no way to book a plumber without ten phone calls?"],
        },
        "other": {"what": "A real-world signal that fits none of the options above."},
    },
})

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


def niche_question(niche: Niche) -> Question:
    return Question("judge", f"niche_{niche.id}", 1, {
        "type": "noul",
        "instructions": {
            "question": "Is this video relevant to the business niche described in `niche`?",
            "niche": {"name": niche.name, "covers": niche.covers, "not_for": niche.not_for},
        },
    })


def judge_questions(niches: list[Niche]) -> list[Question]:
    return [IS_SIGNAL, SIGNAL_TYPE, IS_PROMOTIONAL, *(niche_question(n) for n in niches)]


def assign_question(trends: list[Trend]) -> Question:
    criteria: dict[str, dict] = {}
    for trend in trends:
        what = f"{trend.name}. {trend.definition}"
        if trend.includes:
            what += f" Includes: {'; '.join(trend.includes)}."
        option = {"what": what}
        if trend.excludes:
            option["not_for"] = "; ".join(trend.excludes)
        criteria[trend.trend_id] = option
    criteria[NONE_OF_THESE] = {"what": "The video does not clearly fit any of the trends listed."}
    return Question("assign", "trend", 1, {
        "type": "choice",
        "instructions": "Which of these trends does this video most clearly provide evidence for?",
        "criteria": criteria,
    })


PAIN = Question("trend", "pain", 1, {
    "type": "score",
    "instructions": "How strong is the frustration or unmet need that people express in the `evidence` about this "
                    "`trend`?",
    "criteria": [
        "No frustration or need: people are just sharing, showing off or enjoying something.",
        "A mild wish or curiosity; nice to have, with no real problem described.",
        "A clear, recurring problem that people actively try to solve.",
        "Intense pain: people describe wasted money or time, anger or desperation, and ask for a solution.",
    ],
})

SPEND = Question("trend", "spend", 1, {
    "type": "score",
    "instructions": "How much evidence is there in the `evidence` that people spend money on this `trend`?",
    "criteria": [
        "No spending mentioned; a free or do-it-yourself activity.",
        "Costs or prices are mentioned, but nobody describes buying anything.",
        "People describe buying related products or paying for services.",
        "People pay a lot, pay for several workarounds, or ask where to buy and how much it costs.",
    ],
})

UNDERSERVED = Question("trend", "underserved", 1, {
    "type": "score",
    "instructions": "According to the `evidence`, how well do existing products serve the need behind this `trend`?",
    "criteria": [
        "People are happy with a named existing product or service.",
        "Existing options are mentioned, with minor complaints.",
        "Existing options are described as inadequate, too expensive or annoying.",
        "People say nothing exists, or rely on manual workarounds or makeshift combinations of tools.",
    ],
})

MENTIONS_SOLUTIONS = Question("trend", "mentions_solutions", 1, {
    "type": "noul",
    "instructions": "Does the `evidence` mention existing products, services, apps or methods for the need behind this "
                    "`trend`, or say that none exist?",
})

TREND_QUESTIONS = [PAIN, SPEND, UNDERSERVED, MENTIONS_SOLUTIONS]

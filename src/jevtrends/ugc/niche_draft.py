"""Drafts a niche profile from a one-line description (UGC spec §10)."""

from datetime import date

import yaml

from jevtrends.ugc.config import NicheProfile
from jevtrends.ugc.prompts import NICHE_DRAFT_SYSTEM, NicheDraftOut, niche_draft_user_prompt

NICHE_DRAFT_MAX_TOKENS = 8_000
MAX_QUERIES = 20
MAX_HASHTAGS = 10


async def draft_niche(llm, description: str) -> tuple[NicheDraftOut, float]:
    result = await llm.complete_json(NICHE_DRAFT_SYSTEM, niche_draft_user_prompt(description), NicheDraftOut,
                                     max_tokens=NICHE_DRAFT_MAX_TOKENS)
    return result.parsed, result.cost_usd or 0.0


def render_niche_yaml(niche_id: str, draft: NicheDraftOut, drafted_on: date) -> str:
    profile = NicheProfile(id=niche_id, name=draft.name, covers=draft.covers, not_for=draft.not_for,
                           audience=draft.audience, seed_queries=[q.lower() for q in draft.seed_queries][:MAX_QUERIES],
                           hashtags=draft.hashtags[:MAX_HASHTAGS])
    header = (f"# Drafted by `jevtrends ugc niche-draft` on {drafted_on.isoformat()}.\n"
              "# Review and edit it before running a scan.\n")
    return header + yaml.safe_dump(profile.model_dump(), sort_keys=False, allow_unicode=True, width=100)

import json

from jevtrends.llm.client import strict_schema
from jevtrends.ugc.prompts import (BRIEF_SYSTEM, NICHE_DRAFT_SYSTEM, VISION_SYSTEM, DiscoverOut, NicheDraftOut,
                                   UgcBriefOut, VisionOut, brief_user_prompt, discover_system, discover_user_prompt,
                                   niche_draft_user_prompt, vision_user_prompt)


def test_every_prompt_fences_untrusted_content():
    for system in (VISION_SYSTEM, discover_system(3, 9), BRIEF_SYSTEM, NICHE_DRAFT_SYSTEM):
        assert "never" in system and ("instructions" in system or "follow" in system)
    user = discover_user_prompt(["[v001] @a | video 30s"], ['[s01] "Song" by X'])
    assert user.startswith("<videos>\n[v001]") and "</videos>" in user and "<sounds>\n[s01]" in user
    assert brief_user_prompt({"trend": {"name": "x"}}).startswith("<trend_data>")
    assert niche_draft_user_prompt("habit apps").startswith("<niche>\nhabit apps\n</niche>")


def test_discover_counts_read_naturally():
    assert "Propose between 3 and 9 formats and between 3 and 9 hooks, and up to 9 topics and up to 9 needs" in (
        discover_system(3, 9))
    assert "Propose up to 1 formats and up to 1 hooks" in discover_system(1, 1)


def test_vision_user_prompt_names_slides_or_a_frame():
    assert "first 3 slides" in vision_user_prompt(is_slideshow=True, image_count=3)
    assert "opening frame" in vision_user_prompt(is_slideshow=False, image_count=1)


def test_schemas_are_strict_and_complete():
    for model in (VisionOut, DiscoverOut, UgcBriefOut, NicheDraftOut):
        schema = strict_schema(model)
        assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert "default" not in json.dumps(strict_schema(UgcBriefOut))
    assert set(UgcBriefOut.model_fields) == {"title", "why_its_working", "concept", "hooks", "beats", "sound",
                                             "pairs_with", "dos", "donts", "cta", "claims_used", "evidence", "risks"}

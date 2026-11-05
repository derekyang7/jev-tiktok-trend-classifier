import json

from jevtrends.core.llm import strict_schema
from jevtrends.opportunities.prompts import (BRIEF_SYSTEM, DISCOVER_SYSTEM, BriefOut, DiscoverOut, brief_user_prompt,
                                             discover_system, discover_user_prompt, trend_count_range)


def test_prompts_fence_untrusted_content():
    assert "never instructions" in DISCOVER_SYSTEM
    assert "never instructions" in BRIEF_SYSTEM
    user = discover_user_prompt(["[v001] @a | behavior_need | ..."])
    assert user.startswith("<videos>\n[v001]") and "</videos>" in user
    brief = brief_user_prompt({"trend": {"name": "x"}})
    assert brief.startswith("<trend_data>") and '"name": "x"' in brief
    assert set(BriefOut.model_fields) == {"headline", "whats_happening", "who", "underlying_need", "evidence",
                                          "existing_solutions", "startup_angles", "risks"}


def test_trend_count_scales_with_signal_videos():
    assert trend_count_range(460, 60) == (20, 60)  # full scan: the spec's 20-60
    assert trend_count_range(46, 60) == (3, 7)  # pilot size: about one trend per 6 signal videos
    assert trend_count_range(5, 60) == (1, 1)
    assert "Propose between 3 and 7 trends." in discover_system(3, 7)
    assert "Propose up to 1 trend." in discover_system(1, 1)


def test_schemas_are_strict_and_complete():
    for model in (DiscoverOut, BriefOut):
        schema = strict_schema(model)
        assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert "default" not in json.dumps(strict_schema(DiscoverOut))

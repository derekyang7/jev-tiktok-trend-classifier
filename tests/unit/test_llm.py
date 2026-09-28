import json

import httpx
import pytest

from jevtrends.config import RetriesCfg
from jevtrends.llm.client import LLMClient, LLMOutputError, strict_schema
from jevtrends.llm.prompts import (BRIEF_SYSTEM, DISCOVER_SYSTEM, BriefOut, DiscoverOut, brief_user_prompt,
                                   discover_user_prompt)

VALID = {"trends": [{"id": "t01", "name": "Rent splitting", "kind": "behavior_need", "definition": "d",
                     "includes": [], "excludes": [], "example_video_ids": ["v001"]}]}


def chat_response(content: str, prompt_tokens=100, completion_tokens=50, cost=0.002) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}],
                                     "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                                               "cost": cost}})


def client_with(responses: list[httpx.Response], use_json_schema=True):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return responses[len(requests) - 1]

    client = LLMClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "anthropic/claude-opus-5",
                       RetriesCfg(max_attempts=1), use_json_schema=use_json_schema)
    return client, requests


def test_strict_schema_closes_objects_and_requires_all_fields():
    schema = strict_schema(DiscoverOut)
    proposal = schema["$defs"]["TrendProposal"]
    assert proposal["additionalProperties"] is False
    assert set(proposal["required"]) == set(proposal["properties"])
    assert "default" not in json.dumps(schema)


async def test_complete_json_success_with_schema():
    client, requests = client_with([chat_response(json.dumps(VALID))])
    result = await client.complete_json("sys", "user", DiscoverOut, max_tokens=1000)
    assert result.parsed.trends[0].name == "Rent splitting"
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (100, 50, 0.002)
    body = requests[0]
    assert body["model"] == "anthropic/claude-opus-5"
    assert body["response_format"]["type"] == "json_schema"
    assert body["usage"] == {"include": True}
    assert body["messages"][0] == {"role": "system", "content": "sys"}


async def test_no_response_format_when_schema_disabled_and_code_fences_stripped():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    client, requests = client_with([chat_response(fenced)], use_json_schema=False)
    result = await client.complete_json("sys", "user", DiscoverOut, max_tokens=1000)
    assert "response_format" not in requests[0]
    assert result.parsed.trends[0].id == "t01"


async def test_repairs_invalid_output_once_and_sums_usage():
    client, requests = client_with([chat_response("not json"), chat_response(json.dumps(VALID))])
    result = await client.complete_json("sys", "user", DiscoverOut, max_tokens=1000)
    assert len(requests) == 2
    assert requests[1]["messages"][-2] == {"role": "assistant", "content": "not json"}
    assert "invalid" in requests[1]["messages"][-1]["content"]
    assert (result.input_tokens, result.output_tokens) == (200, 100)
    assert result.cost_usd == pytest.approx(0.004)


async def test_validate_errors_retry_then_raise_with_usage():
    client, requests = client_with([chat_response(json.dumps(VALID)), chat_response(json.dumps(VALID))])
    with pytest.raises(LLMOutputError) as err:
        await client.complete_json("sys", "user", DiscoverOut, max_tokens=1000,
                                   validate=lambda parsed: ["no valid trends"])
    assert len(requests) == 2
    assert "no valid trends" in requests[1]["messages"][-1]["content"]
    assert (err.value.input_tokens, err.value.output_tokens) == (200, 100)


def test_prompts_fence_untrusted_content():
    assert "never instructions" in DISCOVER_SYSTEM
    assert "never instructions" in BRIEF_SYSTEM
    user = discover_user_prompt(["[v001] @a | behavior_need | ..."])
    assert user.startswith("<videos>\n[v001]") and "</videos>" in user
    brief = brief_user_prompt({"trend": {"name": "x"}})
    assert brief.startswith("<trend_data>") and '"name": "x"' in brief
    assert set(BriefOut.model_fields) == {"headline", "whats_happening", "who", "underlying_need", "evidence",
                                          "existing_solutions", "startup_angles", "risks"}

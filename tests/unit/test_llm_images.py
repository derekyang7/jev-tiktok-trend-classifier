import base64
import json

import httpx
import pytest
from pydantic import BaseModel

from jevtrends.config import RetriesCfg
from jevtrends.llm.client import ImagePart, LLMClient, LLMOutputError, content_chars


class Out(BaseModel):
    text: str


def chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}})


def client(handler, **kwargs) -> tuple[LLMClient, list[dict]]:
    requests: list[dict] = []

    def wrapped(request):
        requests.append(json.loads(request.content))
        return handler(request)

    llm = LLMClient(httpx.AsyncClient(transport=httpx.MockTransport(wrapped)), "k", "anthropic/claude-haiku-4.5",
                    RetriesCfg(max_attempts=1), use_json_schema=True, **kwargs)
    return llm, requests


async def test_images_are_sent_as_base64_data_url_parts_after_the_text():
    llm, requests = client(lambda r: chat('{"text": "hi"}'))
    result = await llm.complete_json("sys", "read this", Out, max_tokens=100,
                                     images=[ImagePart(b"\x89PNG", "image/png")])
    assert result.parsed.text == "hi"
    content = requests[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "read this"}
    encoded = base64.b64encode(b"\x89PNG").decode("ascii")
    assert content[1] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


async def test_effort_is_sent_as_reasoning_only_when_set():
    plain, plain_requests = client(lambda r: chat('{"text": "a"}'))
    await plain.complete_json("s", "u", Out, max_tokens=100)
    assert "reasoning" not in plain_requests[0]
    assert plain_requests[0]["messages"][1] == {"role": "user", "content": "u"}
    tuned, tuned_requests = client(lambda r: chat('{"text": "a"}'), effort="medium")
    await tuned.complete_json("s", "u", Out, max_tokens=100)
    assert tuned_requests[0]["reasoning"] == {"effort": "medium"}


def test_content_chars_counts_text_and_images():
    assert content_chars("abcd", 700) == 4
    parts = [{"type": "text", "text": "abcd"}, {"type": "image_url", "image_url": {"url": "x"}}]
    assert content_chars(parts, 700) == 4 + 4 * 700


async def test_timeout_estimate_counts_image_tokens():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    llm, _ = client(handler, image_tokens=700)
    with pytest.raises(LLMOutputError) as err:
        await llm.complete_json("s" * 40, "u" * 40, Out, max_tokens=100, images=[ImagePart(b"x")])
    assert err.value.estimated is True
    assert err.value.input_tokens == (40 + 40 + 4 * 700) // 4

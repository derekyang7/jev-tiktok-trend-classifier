"""OpenRouter chat client with JSON output, validation and one repair retry (spec §6.5 and §6.8)."""

import base64
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from jevtrends.config import RetriesCfg
from jevtrends.http import TransientAPIError, send_with_retry

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_TIMEOUT = httpx.Timeout(900.0, connect=30.0)  # long generations send no bytes until they finish


@dataclass
class LLMResult:
    parsed: BaseModel
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class LLMOutputError(Exception):
    """The model's output failed validation on both attempts. Carries the usage already spent."""

    def __init__(self, message: str, input_tokens: int, output_tokens: int, cost_usd: float | None,
                 estimated: bool = False):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd
        self.estimated = estimated


@dataclass
class ImagePart:
    """An image sent with a chat request (UGC spec §6.4)."""

    data: bytes
    media_type: str = "image/jpeg"

    def as_content(self) -> dict:
        encoded = base64.b64encode(self.data).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:{self.media_type};base64,{encoded}"}}


def content_chars(content: str | list, image_tokens: int) -> int:
    """Characters of a message's content for estimating tokens; each image counts as `image_tokens` tokens."""
    if isinstance(content, str):
        return len(content)
    return sum(len(part.get("text", "")) if part.get("type") == "text" else 4 * image_tokens for part in content)


def strict_schema(model: type[BaseModel]) -> dict:
    """JSON schema with closed objects and every property required.

    Drops the "default" and "title" keywords, but never from a "properties" mapping, where they are field names
    (the UGC brief has a `title` field).
    """
    schema = model.model_json_schema()

    def fix(node: object, is_properties: bool = False) -> None:
        if isinstance(node, dict):
            if not is_properties:
                node.pop("default", None)
                node.pop("title", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for key, value in node.items():
                fix(value, is_properties=key == "properties" and not is_properties)
        elif isinstance(node, list):
            for item in node:
                fix(item)

    fix(schema)
    return schema


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


class LLMClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str, retries: RetriesCfg,
                 use_json_schema: bool, url: str = CHAT_URL, effort: str | None = None, image_tokens: int = 1600):
        self.client = client
        self.api_key = api_key
        self.model = model
        self.retries = retries
        self.use_json_schema = use_json_schema
        self.url = url
        self.effort = effort
        self.image_tokens = image_tokens

    async def _call(self, messages: list[dict], schema: type[BaseModel], max_tokens: int) -> tuple[str, dict]:
        body: dict = {"model": self.model, "max_tokens": max_tokens, "messages": messages, "usage": {"include": True}}
        if self.effort:
            body["reasoning"] = {"effort": self.effort}  # OpenRouter's reasoning control (contract check D7)
        if self.use_json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": strict_schema(schema)}}
        response = await send_with_retry(self.client, "openrouter", "POST", self.url, retries=self.retries,
                                         retry_transport_errors=False, timeout=LLM_TIMEOUT,
                                         json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        data = response.json()
        if not data.get("choices"):  # OpenRouter can return 200 with only an error body
            raise TransientAPIError("openrouter", response.status_code, str(data.get("error"))[:300])
        return data["choices"][0]["message"].get("content") or "", data.get("usage") or {}

    async def complete_json(self, system: str, user: str, schema: type[BaseModel], max_tokens: int,
                            validate: Callable[[BaseModel], list[str]] | None = None,
                            images: list[ImagePart] | None = None) -> LLMResult:
        user_content: str | list = user
        if images:
            user_content = [{"type": "text", "text": user}, *(image.as_content() for image in images)]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
        input_tokens = output_tokens = 0
        cost: float | None = 0.0
        errors: list[str] = []
        for _ in range(2):
            try:
                content, usage = await self._call(messages, schema, max_tokens)
            except TransientAPIError as exc:
                billing_unknown = exc.status in (None, 200)  # timeout or error body: generation may be billed
                if billing_unknown:
                    input_tokens += sum(content_chars(m["content"], self.image_tokens) for m in messages) // 4
                    output_tokens += max_tokens
                    cost = None
                raise LLMOutputError(f"LLM call failed: {exc}", input_tokens, output_tokens, cost,
                                     estimated=billing_unknown) from exc
            input_tokens += int(usage.get("prompt_tokens", 0))
            output_tokens += int(usage.get("completion_tokens", 0))
            cost = cost + float(usage["cost"]) if cost is not None and "cost" in usage else None
            try:
                parsed = schema.model_validate_json(_extract_json(content))
                errors = validate(parsed) if validate else []
            except ValidationError as exc:
                errors = [str(exc)[:2000]]
            if not errors:
                return LLMResult(parsed=parsed, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "Your previous output was invalid:\n" + "\n".join(errors)
                                            + "\nReturn corrected JSON only."},
            ]
        raise LLMOutputError("; ".join(errors), input_tokens, output_tokens, cost)

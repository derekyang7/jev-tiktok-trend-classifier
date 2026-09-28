"""Step 0 live contract check (spec §14.1). Costs < $0.10 plus ~3 ScrapeCreators credits.

Run with: scripts/with-secrets.sh uv run python scripts/contract_check.py
Writes redacted responses to tests/fixtures/contract/. Never prints keys or headers.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract"
OPENROUTER = "https://openrouter.ai/api"
SC = "https://api.scrapecreators.com"
JEV_MODEL = "typesafe/jev-1.13"
LLM_MODEL = "anthropic/claude-opus-5"


def save(name: str, data: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  saved tests/fixtures/contract/{name}")


def redact_user(user: dict, n: int) -> dict:
    user = dict(user)
    for key in ("unique_id", "nickname", "uid", "sec_uid", "signature"):
        if key in user:
            user[key] = f"redacted_{key}_{n}"
    user.pop("avatar_thumb", None)
    user.pop("avatar_larger", None)
    user.pop("avatar_medium", None)
    return user


JEV_BODY = {
    "model": JEV_MODEL,
    "state": {"caption": "My bank's app is useless so I track everything in five spreadsheets"},
    "questions": {
        "is_complaint": {
            "type": "noul",
            "instructions": "Is the person complaining about an existing product?",
        },
        "topic": {
            "type": "choice",
            "instructions": "What is this mainly about?",
            "criteria": {"money": "Personal finance or banking", "food": None, "other": None},
        },
        "pain": {
            "type": "score",
            "instructions": "How strong is the frustration expressed?",
            "criteria": ["No frustration", "Mild annoyance", "Clear, recurring problem"],
        },
    },
}


async def check_jev(client: httpx.AsyncClient, key: str) -> bool:
    print("Jev via OpenRouter")
    headers = {"Authorization": f"Bearer {key}"}
    for path in ("/v1/systemone", "/alpha/decisions"):
        resp = await client.post(f"{OPENROUTER}{path}", json=JEV_BODY, headers=headers)
        print(f"  POST {path} -> {resp.status_code}")
        if resp.status_code == 200:
            save("jev_systemone.json", {"endpoint": path, "response": resp.json()})
            return True
        print(f"  body: {resp.text[:300]}")
    return False


async def check_llm(client: httpx.AsyncClient, key: str) -> bool:
    print("Opus 5 via OpenRouter chat")
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["answer", "items"],
        "additionalProperties": False,
    }
    body = {
        "model": LLM_MODEL,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": "Reply with JSON only."},
            {"role": "user", "content": "Name two fruits. Put a one-word summary in answer."},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": schema}},
        "usage": {"include": True},
    }
    resp = await client.post(f"{OPENROUTER}/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
    print(f"  POST /v1/chat/completions (json_schema) -> {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        save("llm_chat.json", {"json_schema": True, "response": data})
        content = data["choices"][0]["message"]["content"]
        print(f"  content parses as JSON: {_parses(content)}; usage: {data.get('usage')}")
        return True
    print(f"  body: {resp.text[:300]}")
    body.pop("response_format")
    resp = await client.post(f"{OPENROUTER}/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
    print(f"  POST /v1/chat/completions (no json_schema) -> {resp.status_code}")
    if resp.status_code == 200:
        save("llm_chat.json", {"json_schema": False, "response": resp.json()})
        return True
    print(f"  body: {resp.text[:300]}")
    return False


def _parses(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


async def check_scrapecreators(client: httpx.AsyncClient, key: str) -> bool:
    print("ScrapeCreators")
    headers = {"x-api-key": key}
    params = {"query": "budgeting app", "date_posted": "this-month", "sort_by": "relevance", "region": "US"}
    resp = await client.get(f"{SC}/v1/tiktok/search/keyword", params=params, headers=headers)
    print(f"  GET /v1/tiktok/search/keyword -> {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body: {resp.text[:300]}")
        return False
    data = resp.json()
    items = data.get("search_item_list") or []
    print(f"  items: {len(items)}; top-level keys: {sorted(data.keys())}")
    if not items:
        return False
    first = items[0]["aweme_info"]
    print(f"  aweme_info keys: {sorted(first.keys())}")
    print(f"  author keys: {sorted(first.get('author', {}).keys())}")
    redacted = dict(data)
    redacted["search_item_list"] = []
    for n, item in enumerate(items[:2]):
        info = dict(item["aweme_info"])
        info["author"] = redact_user(info.get("author", {}), n)
        redacted["search_item_list"].append({"aweme_info": info})
    save("sc_search.json", redacted)

    handle = first["author"]["unique_id"]
    url = f"https://www.tiktok.com/@{handle}/video/{first['aweme_id']}"
    resp = await client.get(f"{SC}/v1/tiktok/video/transcript", params={"url": url, "language": "en"}, headers=headers)
    print(f"  GET /v1/tiktok/video/transcript -> {resp.status_code}")
    transcript = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text[:500]}
    if isinstance(transcript.get("transcript"), str):
        transcript["transcript"] = "\n".join(transcript["transcript"].splitlines()[:20])
    transcript["url"] = "https://www.tiktok.com/@redacted/video/0"
    save("sc_transcript.json", {"status_code": resp.status_code, "body": transcript})

    resp = await client.get(f"{SC}/v1/tiktok/video/comments", params={"url": url}, headers=headers)
    print(f"  GET /v1/tiktok/video/comments -> {resp.status_code}")
    comments = resp.json()
    comments["comments"] = [
        {**c, "user": redact_user(c.get("user", {}), n)} for n, c in enumerate((comments.get("comments") or [])[:3])
    ]
    save("sc_comments.json", comments)
    return True


async def main() -> int:
    keys = {name: os.environ.get(name, "") for name in ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")}
    missing = [name for name, value in keys.items() if not value]
    if missing:
        print(f"Missing environment variables: {missing}. Run via scripts/with-secrets.sh.")
        return 2
    async with httpx.AsyncClient(timeout=120) as client:
        jev_ok = await check_jev(client, keys["OPENROUTER_API_KEY"])
        llm_ok = await check_llm(client, keys["OPENROUTER_API_KEY"])
        sc_ok = await check_scrapecreators(client, keys["SCRAPECREATORS_API_KEY"])
    print(f"\nRESULT jev={jev_ok} llm={llm_ok} scrapecreators={sc_ok}")
    return 0 if (jev_ok and llm_ok and sc_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

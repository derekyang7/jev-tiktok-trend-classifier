"""UGC Step 0 live contract check (UGC spec §14.1). Costs about $0.50: ~30 ScrapeCreators credits plus model calls.

Run with: scripts/with-secrets.sh uv run python scripts/ugc_contract_check.py
Writes redacted responses to tests/fixtures/contract/ugc/. Never prints keys or headers, and never saves images or
real videos' on-screen text.
"""

import asyncio
import base64
import io
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_check import scrub  # noqa: E402  (V1's deep redaction of creator identifiers)

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract" / "ugc"
OPENROUTER = "https://openrouter.ai/api/v1"
SC = "https://api.scrapecreators.com"
OPUS = "anthropic/claude-opus-5.5"
HAIKU = "anthropic/claude-haiku-4.5"
LICENSING_KEYS = ("is_commerce_music", "is_commerce_music_strict", "has_commerce_right", "has_commerce_right_strict")
PLACEHOLDER = "https://example.invalid/media"
VISION_PROMPT = ("You read the opening frame of a TikTok video, or the first slides of a photo slideshow. Transcribe "
                 "all text shown on screen exactly, in reading order, and describe the setup in at most 25 words. "
                 "Return JSON only.")
VISION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["on_screen_text", "setup"],
                 "properties": {"on_screen_text": {"type": "string"}, "setup": {"type": "string"}}}
LIST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "definition"],
                               "properties": {"name": {"type": "string"}, "definition": {"type": "string"}}}}}}


def save(name: str, data: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  saved tests/fixtures/contract/ugc/{name}")


def scrub_media(node: object) -> object:
    """Replaces signed CDN links (covers, slides, playback) with a placeholder."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in ("url_list", "images") and isinstance(value, list) and all(isinstance(v, str) for v in value):
                out[key] = [PLACEHOLDER for _ in value]
            else:
                out[key] = scrub_media(value)
        return out
    if isinstance(node, list):
        return [scrub_media(item) for item in node]
    return node


def redact(data: object) -> object:
    return scrub_media(scrub(data))


def truncated(data: dict, list_key: str, keep: int) -> dict:
    """The response with its list (at the top level or under "data") cut to `keep` items."""
    if isinstance(data.get("data"), dict) and list_key in data["data"]:
        return {**data, "data": {**data["data"], list_key: data["data"][list_key][:keep]}}
    return {**data, list_key: (data.get(list_key) or [])[:keep]}


def sound_list(data: dict) -> list[dict]:
    body = data["data"] if isinstance(data.get("data"), dict) else data
    return body.get("sound_list") or []


def parses(text: object) -> bool:
    try:
        json.loads(text)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


async def sc_get(client: httpx.AsyncClient, key: str, path: str, params: dict) -> tuple[int, dict]:
    resp = await client.get(f"{SC}{path}", params=params, headers={"x-api-key": key})
    print(f"  GET {path} {params} -> {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:300]}
    if resp.status_code != 200:
        print(f"  body: {json.dumps(body)[:300]}")
    return resp.status_code, body if isinstance(body, dict) else {"raw": body}


async def check_hashtag(client: httpx.AsyncClient, key: str) -> tuple[bool, list[dict]]:
    print("Hashtag search (D1)")
    status, data = await sc_get(client, key, "/v1/tiktok/search/hashtag", {"hashtag": "appsyouneed", "region": "US"})
    items = data.get("aweme_list") or []
    print(f"  top-level keys: {sorted(data)}; items: {len(items)}; cursor: {data.get('cursor')!r}; "
          f"has_more: {data.get('has_more')!r}")
    if items:
        times = sorted(int(i.get("create_time") or 0) for i in items)
        photos = [i for i in items if i.get("image_post_info")]
        recent = sum(1 for t in times if t >= time.time() - 14 * 86400)
        print(f"  slideshows (image_post_info): {len(photos)}; posting span: {(times[-1] - times[0]) / 86400:.1f} days; "
              f"posted in the last 14 days: {recent} of {len(items)}")
        print(f"  item keys: {sorted(items[0])}")
        save("sc_hashtag.json", redact({**data, "aweme_list": items[:2] + photos[:1]}))
    return status == 200 and bool(items), items


async def check_top(client: httpx.AsyncClient, key: str) -> tuple[bool, list[dict]]:
    print("Top search (D2)")
    found: list[dict] = []
    for query in ("apps you need", "apps that feel illegal to know"):
        params = {"query": query, "publish_time": "this-month", "sort_by": "relevance", "region": "US"}
        _, data = await sc_get(client, key, "/v1/tiktok/search/top", params)
        items = data.get("items") or []
        print(f"  '{query}': keys {sorted(data)}; items {len(items)}; content types "
              f"{dict(Counter(i.get('content_type') for i in items))}; cursor {data.get('cursor')!r}")
        found += items
    photos = [i for i in found if i.get("content_type") == "multi_photo"]
    if photos:
        first = photos[0]
        print(f"  multi_photo keys: {sorted(first)}; images[0] is a {type((first.get('images') or [None])[0]).__name__}")
    if found:
        save("sc_top.json", redact({"items": found[:1] + photos[:1]}))
    return bool(found), found


async def popular(client: httpx.AsyncClient, key: str, commercial: bool) -> tuple[int, dict]:
    params = {"page": 1, "timePeriod": 7, "rankType": "popular", "countryCode": "US"}
    if commercial:
        params["commercialMusic"] = "true"
    return await sc_get(client, key, "/v1/tiktok/songs/popular", params)


async def check_songs(client: httpx.AsyncClient, key: str) -> tuple[bool, list[dict], list[dict]]:
    print("Popular songs (D3)")
    status, data = await popular(client, key, commercial=False)
    songs = sound_list(data)
    body = data["data"] if isinstance(data.get("data"), dict) else data
    print(f"  top-level keys: {sorted(data)}; songs: {len(songs)}; pagination: {body.get('pagination')}")
    if songs:
        print(f"  song keys: {sorted(songs[0])}")
        print(f"  if_cml values: {dict(Counter(s.get('if_cml') for s in songs))}; "
              f"trend points in the first song: {len(songs[0].get('trend') or [])}; link: {songs[0].get('link')}")
        save("sc_songs_popular.json", redact(truncated(data, "sound_list", 3)))
    _, cml_data = await popular(client, key, commercial=True)
    commercial = sound_list(cml_data)
    same = {s.get("clip_id") for s in commercial} == {s.get("clip_id") for s in songs}
    print(f"  commercialMusic=true -> {len(commercial)} songs; identical to the unfiltered list: {same}")
    if commercial:
        save("sc_songs_popular_cml.json", redact(truncated(cml_data, "sound_list", 3)))
    return status == 200 and bool(songs), songs, commercial


async def check_song_videos(client: httpx.AsyncClient, key: str, clip: str) -> bool:
    print("Videos using a song (D4)")
    status, data = await sc_get(client, key, "/v1/tiktok/song/videos", {"clipId": clip})
    items = data.get("aweme_list") or []
    ids = {str((i.get("music") or {}).get("id_str") or (i.get("music") or {}).get("id")) for i in items}
    times = [int(i.get("create_time") or 0) for i in items]
    print(f"  items: {len(items)}; cursor: {data.get('cursor')!r}; has_more: {data.get('has_more')!r}")
    print(f"  every music id equals the clip_id: {ids == {clip}} ({len(ids)} distinct); "
          f"newest first: {times == sorted(times, reverse=True)}")
    if items:
        save("sc_song_videos.json", redact(truncated(data, "aweme_list", 2)))
    return status == 200 and bool(items)


async def check_licensing(client: httpx.AsyncClient, key: str, songs: list[dict], commercial: list[dict]) -> None:
    print("Raw licensing flags against TikTok's business-use data (D5), up to 24 songs")
    labels = {str(s.get("clip_id")): s["if_cml"] for s in songs if isinstance(s.get("if_cml"), bool)}
    source = "per-song if_cml"
    if not labels:
        labels = {str(s.get("clip_id")): True for s in commercial}
        source = "the commercialMusic=true list (approved side only)"
    agree: Counter = Counter()
    seen: Counter = Counter()
    for clip, label in list(labels.items())[:24]:
        _, data = await sc_get(client, key, "/v1/tiktok/song/videos", {"clipId": clip})
        music = next(((i.get("music") or {}) for i in data.get("aweme_list") or [] if i.get("music")), {})
        for flag in LICENSING_KEYS:
            if flag in music:
                seen[flag] += 1
                agree[flag] += bool(music[flag]) == label
    print(f"  labels from {source}")
    for flag in LICENSING_KEYS:
        share = f" ({agree[flag] / seen[flag]:.0%})" if seen[flag] else ""
        print(f"  {flag}: agrees on {agree[flag]} of {seen[flag]} songs{share}")


def image_facts(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return f"{image.format} {image.size[0]}x{image.size[1]}"
    except Exception as exc:  # noqa: BLE001 - report whatever Pillow can't read
        return f"unreadable by Pillow ({type(exc).__name__})"


def expires_in(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    raw = (query.get("x-expires") or query.get("expires") or [""])[0]
    return f"{(int(raw) - time.time()) / 3600:.1f} h" if raw.isdigit() else "no expiry parameter"


async def check_images(client: httpx.AsyncClient, items: list[dict]) -> tuple[bool, list[bytes]]:
    print("Cover images, downloaded with no API key (D6)")
    covers: list[bytes] = []
    for item in items[:5]:
        media = item.get("video") or {}
        best = None
        for field in ("origin_cover", "cover", "dynamic_cover"):
            url = ((media.get(field) or {}).get("url_list") or [None])[0]
            if not url:
                continue
            resp = await client.get(url)
            facts = image_facts(resp.content) if resp.status_code == 200 else ""
            print(f"  {field}: {resp.status_code} {resp.headers.get('content-type')} {len(resp.content)} bytes "
                  f"{facts}; link expires in {expires_in(url)}")
            readable = resp.status_code == 200 and not facts.startswith("unreadable")
            if best is None and readable and field != "dynamic_cover":
                best = resp.content
        if best:
            covers.append(best)
    return bool(covers), covers


async def chat(client: httpx.AsyncClient, key: str, body: dict) -> tuple[int, dict, float]:
    start = time.monotonic()
    resp = await client.post(f"{OPENROUTER}/chat/completions", json=body, timeout=900,
                             headers={"Authorization": f"Bearer {key}"})
    elapsed = time.monotonic() - start
    print(f"  POST /chat/completions model={body['model']} -> {resp.status_code} in {elapsed:.0f} s")
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:300]}
    if resp.status_code != 200:
        print(f"  body: {json.dumps(data)[:300]}")
    return resp.status_code, data, elapsed


def message_text(data: dict) -> str:
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


async def check_opus(client: httpx.AsyncClient, key: str) -> bool:
    print("Opus 5.5 via OpenRouter (D7)")
    body = {"model": OPUS, "max_tokens": 16000, "reasoning": {"effort": "medium"}, "usage": {"include": True},
            "messages": [{"role": "system", "content": "Reply with JSON only."},
                         {"role": "user", "content": "List 40 kinds of short video formats people use on social "
                                                     "media, each with a name and a two-sentence definition."}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "probe", "strict": True, "schema": LIST_SCHEMA}}}
    status, data, elapsed = await chat(client, key, body)
    if status == 400:
        print("  retrying without the reasoning parameter")
        body.pop("reasoning")
        status, data, elapsed = await chat(client, key, body)
    if status != 200:
        return False
    usage = data.get("usage") or {}
    out = int(usage.get("completion_tokens") or 0)
    speed = out / max(elapsed, 1)
    print(f"  model: {data.get('model')}; usage: {usage}")
    print(f"  output speed {speed:.0f} tokens/s; 40,000 output tokens would take {40000 / max(speed, 1):.0f} s "
          "(V1's read timeout is 900 s)")
    print(f"  content parses as JSON: {parses(message_text(data))}; "
          f"message keys: {sorted(data['choices'][0]['message'])}")
    message = data["choices"][0]["message"]
    for field in ("content", "reasoning"):
        if isinstance(message.get(field), str):
            message[field] = message[field][:400]
    save("llm_opus.json", {"reasoning_sent": "reasoning" in body, "elapsed_s": round(elapsed, 1), "response": data})
    return True


def synthetic_cover(text: str) -> bytes:
    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).multiline_text((60, 200), text, fill="black", font_size=64)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def downscale(data: bytes, long_edge: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((long_edge, long_edge))
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()


async def read_images(client: httpx.AsyncClient, key: str, images: list[bytes]) -> tuple[int, dict]:
    parts = [{"type": "image_url",
              "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")}}
             for image in images]
    body = {"model": HAIKU, "max_tokens": 1000, "usage": {"include": True},
            "messages": [{"role": "system", "content": VISION_PROMPT},
                         {"role": "user", "content": [{"type": "text", "text": "Read these images."}, *parts]}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "vision", "strict": True, "schema": VISION_SCHEMA}}}
    status, data, _ = await chat(client, key, body)
    return status, data


async def check_haiku(client: httpx.AsyncClient, key: str, covers: list[bytes]) -> bool:
    print("Haiku 4.5 vision via OpenRouter (D6, D7)")
    images = [synthetic_cover("APPS THAT FEEL\nILLEGAL TO KNOW"), synthetic_cover("POV: you finally\nfound the app")]
    status, data = await read_images(client, key, images)
    if status != 200:
        return False
    print(f"  synthetic slides read as: {message_text(data)}; usage: {data.get('usage')}")
    save("llm_vision.json", {"response": data})
    print("  real covers at full size vs 960 px (compare by eye; nothing is saved):")
    for cover in covers[:5]:
        _, full = await read_images(client, key, [cover])
        _, small = await read_images(client, key, [downscale(cover, 960)])
        print(f"   full: {message_text(full)[:200]}\n   960 : {message_text(small)[:200]}")
    return True


async def check_jev(client: httpx.AsyncClient, key: str) -> bool:
    print("Jev (D8)")
    niche = {"name": "Consumer apps", "covers": "Apps people use in everyday life", "not_for": "Business software"}
    gate = {"model": "typesafe/jev-1.13",
            "state": {"caption": "5 apps that feel illegal to know #apps", "hashtags": ["apps"]},
            "questions": {"relevant": {
                "type": "noul",
                "instructions": {"question": "Could this video be about the niche described in `niche`, judging "
                                             "by its caption and hashtags?", "niche": niche},
                "criteria": {"true": "The caption or hashtags hint at anything the niche covers.",
                             "false": "They clearly point to something else."}}}}
    none = {"what": "None of the options clearly fits this video."}
    choices = {"model": "typesafe/jev-1.13", "state": {"caption": "POV: you finally found an app that tracks habits",
                                                       "on_screen_text": "POV: you finally found the app"},
               "questions": {facet: {"type": "choice", "instructions": f"Which of these {facet}s fits this video?",
                                     "criteria": {f"{facet[0]}01": {"what": option}, "none_of_these": none}}
                             for facet, option in (("format", "Green-screen reaction over app screenshots"),
                                                   ("hook", "POV: you finally found an app that ___"),
                                                   ("topic", "Lock-in season"),
                                                   ("need", "I can't stay consistent with habits"))}}
    results = {}
    for name, body in (("gate", gate), ("choices", choices)):
        resp = await client.post(f"{OPENROUTER}/systemone", json=body, headers={"Authorization": f"Bearer {key}"})
        print(f"  {name}: POST /systemone -> {resp.status_code}")
        results[name] = {"status": resp.status_code, "response": resp.json() if resp.status_code == 200 else resp.text[:300]}
    save("jev_ugc.json", results)
    return all(r["status"] == 200 for r in results.values())


async def check_sound_alternatives(client: httpx.AsyncClient, key: str) -> None:
    """Other sources of trending sounds, in case the popular-songs list is down (informs D3; nothing is saved)."""
    print("Alternative sound sources (D3)")
    sounds: Counter = Counter()
    titles: dict[str, str] = {}
    for attempt in range(3):
        status, data = await sc_get(client, key, "/v1/tiktok/get-trending-feed", {"region": "US"})
        items = data.get("aweme_list") or []
        for item in items:
            music = item.get("music") or {}
            sound_id = str(music.get("id_str") or music.get("id") or "")
            if sound_id:
                sounds[sound_id] += 1
                titles[sound_id] = music.get("title") or ""
        print(f"  trending feed call {attempt + 1}: {status}; items {len(items)}; keys {sorted(data)[:8]}")
    repeated = [(titles[s], n) for s, n in sounds.most_common(5) if n > 1]
    print(f"  distinct sounds across calls: {len(sounds)}; repeated: {repeated}")
    status, data = await sc_get(client, key, "/v1/tiktok/videos/popular", {"period": 7, "countryCode": "US"})
    print(f"  popular videos: {status}; keys {sorted(data)[:10]}")


async def main() -> int:
    keys = {name: os.environ.get(name, "") for name in ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")}
    missing = [name for name, value in keys.items() if not value]
    if missing:
        print(f"Missing environment variables: {missing}. Run via scripts/with-secrets.sh.")
        return 2
    sc, orkey = keys["SCRAPECREATORS_API_KEY"], keys["OPENROUTER_API_KEY"]
    async with httpx.AsyncClient(timeout=120) as client:
        hashtag_ok, hashtag_items = await check_hashtag(client, sc)
        top_ok, _ = await check_top(client, sc)
        songs_ok, songs, commercial = await check_songs(client, sc)
        if songs:
            clip = str(songs[0].get("clip_id") or songs[0].get("song_id"))
        else:  # the popular list is down: probe the endpoint with a sound from the hashtag results
            clip = next((str((i.get("music") or {}).get("id_str")) for i in hashtag_items
                         if (i.get("music") or {}).get("id_str")), "")
        song_videos_ok = await check_song_videos(client, sc, clip) if clip else False
        if songs:
            await check_licensing(client, sc, songs, commercial)
        else:
            await check_sound_alternatives(client, sc)
        images_ok, covers = await check_images(client, [i for i in hashtag_items if not i.get("image_post_info")])
        opus_ok = await check_opus(client, orkey)
        haiku_ok = await check_haiku(client, orkey, covers)
        jev_ok = await check_jev(client, orkey)
    results = {"hashtag": hashtag_ok, "top": top_ok, "songs": songs_ok, "song_videos": song_videos_ok,
               "images": images_ok, "opus": opus_ok, "haiku": haiku_ok, "jev": jev_ok}
    print("\nRESULT " + " ".join(f"{name}={ok}" for name, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

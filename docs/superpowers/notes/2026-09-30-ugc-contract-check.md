# UGC live contract check (UGC spec §14.1): findings

Run on 2026-09-30 with `scripts/ugc_contract_check.py`, twice. The first run crashed on a HEIC cover; the probe was
fixed to keep only covers Pillow can read and to probe other sound sources. Final run:
`RESULT hashtag=True top=True songs=False song_videos=True images=True opus=True haiku=True jev=True`.
Cost: about $0.25 (ScrapeCreators ~35 credits; Opus ~$0.11; Haiku ~$0.03; Jev < $0.01).

## D1 Hashtag search: works, but returns all-time top posts

- `GET /v1/tiktok/search/hashtag?hashtag=appsyouneed&region=US` → 200. Top level: `aweme_list`, `cursor` (20),
  `has_more` (1), `credits_charged`, `credits_remaining`, `status_code`, `success`.
- 17 items, 11 of them photo posts with `image_post_info`.
- **None of the 17 was posted in the last 14 days; they span 1,955 days.** Date filtering in code leaves almost
  nothing, and each hashtag search would still take a slot in the per-search cap.
- **Decision (user):** drop hashtags from the `consumer_apps` niche; the feature stays for other niches.

## D2 Top search: works; no slideshows for these queries

- `GET /v1/tiktok/search/top` with `query`, `publish_time=this-month`, `sort_by=relevance`, `region=US` → 200.
  Top level: `items`, `cursor` (30), `credits_charged`, `credits_remaining`, `success`. No `has_more`.
- "apps you need": 30 items (`video` 27, `autocut` 1, missing 2). "apps that feel illegal to know": 12 items
  (`video` 10, missing 2). **No `multi_photo` items**, so the `images` shape is still unconfirmed; the parser stays
  tolerant of strings or objects.

## D3 Popular songs: down at the source

- `GET /v1/tiktok/songs/popular` (with and without `commercialMusic=true`) → 400 with
  `"error": "service_unavailable", "errorStatus": 503`: ScrapeCreators reports TikTok's Creative Center music page
  is down. `GET /v1/tiktok/videos/popular` → the same.
- `GET /v1/tiktok/get-trending-feed?region=US` works (12–20 items per call, `aweme_list`), but 44 videos had 38
  distinct sounds, mostly creators' own audio: a weak source of trending sounds.
- Per-song fields (`if_cml`, `trend`, `link`) and the business-use filter's effect could not be checked.
- **Decision (user):** proceed as designed. The sounds stage already notes the outage and takes sounds only from
  the niche sample; popular sounds return once the list is back. The sound-link fallback in Task 18 stays.

## D4 Videos by song: works; items carry no `music` object

- `GET /v1/tiktok/song/videos?clipId=<id>` → 200 with `aweme_list` (4 items), `cursor` (12), `has_more` (1).
- The items have **no `music` object**, so sampled videos never carry raw licensing flags; results are not newest
  first (2022–2024 posts).

## D5 Raw licensing flags

- Not testable without business-use data from the popular list. **`sounds.trusted_licensing_flag` stays `""`.**

## D6 Images

- `origin_cover` is **HEIC** (Pillow can't read it); `cover` is **JPEG** (576×1024 to 1080×1920);
  `dynamic_cover` is animated WebP (270×480). Links carry `x-expires` about 23.6 hours ahead.
- Haiku read the same on-screen text from real covers at full size and at 960 px (minor OCR differences both
  ways), so `vision.max_long_edge: 960` stays.
- **Decision (user):** use the JPEG `cover`; no `pillow-heif`. `parse_video` prefers `cover`, then `origin_cover`.
- **Pilot update (2026-10-01):** keyword-search covers are JPEG, but Top-search `cover` links are HEIC too
  (`…crop-80-heic:500:800.heic`), so all 39 no-image videos in the 100-video pilot came from Top search.
  **Decision (user):** add `pillow-heif`; `prepare_image` converts HEIC to JPEG. Six real Top-search covers converted.

## D7 Claude on OpenRouter

- `anthropic/claude-opus-5.5` and `anthropic/claude-haiku-4.5` work with `response_format: json_schema` (strict).
- `reasoning: {"effort": "medium"}` was accepted on the first try.
- Usage carries `prompt_tokens`, `completion_tokens` and `cost` (USD); message keys `content`, `reasoning`,
  `refusal`, `role`.
- Opus 5.5 wrote 2,682 tokens in 32 s (84 tokens/s): a 40,000-token `discover` call takes about 480 s, inside the
  900 s read timeout, so `discover` stays a single call.
- Haiku read two 720×1280 JPEGs for 2,634 prompt tokens (about 1,230 per full-size image), consistent with the
  projection's 700 per 960-px image.

## D8 Jev

- A Noul with object-valued instructions plus true/false criteria, and a request with four Choice questions, both
  returned 200.

## Changes for later tasks

| Finding | Change |
|---|---|
| D1: hashtags yield nothing in the window | `config/ugc/niches/consumer_apps.yaml` gets `hashtags: []` (Task 6): 30 searches, cap 20 per search |
| D6: `origin_cover` is HEIC | `parse_video` reads `cover` first, then `origin_cover` (Task 2) |
| D3, D5 | No code change; settings keep their defaults |

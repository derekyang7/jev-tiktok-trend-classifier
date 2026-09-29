# Live contract check (spec §14.1): findings

Run on 2026-09-28 with `scripts/contract_check.py`. Final run: `RESULT jev=True llm=True scrapecreators=True`.

## Jev via OpenRouter: PASS

- **Endpoint:** `POST https://openrouter.ai/api/v1/systemone` returned 200. The alpha `/api/alpha/decisions`
  fallback was not needed. `JEV_URL` in `jev/client.py` stays as planned.
- **Request body:** `{model, state, questions}`, exactly as in the TypeSafe docs. Model `typesafe/jev-1.13`.
- **Response top level:** `answers`, `id`, `model`, `provider`, `usage`.
- **Answer shapes** (match `parse_answer` in Task 7):
  - noul: `{"type": "noul", "noul": 0.97}`
  - choice: `{"type": "choice", "choice": "money", "probabilities": {"other": 0, "food": 0, "money": 1}, "confidence": 1}`
  - score: `{"type": "score", "score": 1.94, "legend": {"0": ..., "1": ..., "2": ...}, "probabilities": {"0": 0, "1": 0.06, "2": 0.94}, "confidence": 0.9}`
- **Usage:** `{"input_tokens": 391, "output_tokens": 71, "cost": 1.6422e-05}`. The reported cost equals
  `input_tokens × $0.042 / 1M`, so computing cost from `input_tokens` (as the plan does) matches OpenRouter's bill.

## Claude Opus 5 via OpenRouter chat: PASS

- **Slug:** `anthropic/claude-opus-5` works on `POST https://openrouter.ai/api/v1/chat/completions`.
- **Structured output:** `response_format: {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}`
  returned 200 and the content parsed as JSON. **`llm.use_json_schema: true`.**
- **Message keys:** `content`, `reasoning`, `refusal`, `role`. The JSON is in `content`.
- **Usage:** `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost` (USD, e.g. `0.0019`), plus
  `cost_details` and token details. `usage.cost` is present, so `LLMClient` records OpenRouter's reported cost.

## ScrapeCreators: PASS

- **Search** (`GET /v1/tiktok/search/keyword?query&date_posted=this-month&sort_by=relevance&region=US`): 200.
  - Top level: `success`, `credits_charged` (1), `credits_remaining`, `cursor` (30), `has_more` (1), `search_item_list`.
  - **30 videos per page** (the budget assumed up to 2 pages per query; with a per-query cap of 16, one page usually suffices).
  - `aweme_info.aweme_id` is a string; `create_time` is epoch seconds (int); `desc_language` is present (`"en"`).
  - `statistics`: `play_count`, `digg_count`, `comment_count`, `share_count` (plus `collect_count`, `download_count`, ...).
  - `text_extra[]` mixes user mentions (no `hashtag_name`) with hashtags (`hashtag_name`); the parser keeps only hashtags.
  - `music.title` present (e.g. `"original sound - <handle>"`).
  - `author` has `uid`, `unique_id`, `nickname`, `sec_uid`, `follower_count`, ... but **no `signature`**.
- **Transcript** (`GET /v1/tiktok/video/transcript?url&language=en`): 200, body `{success, credits_charged, credits_remaining,
  id, url, transcript}` with `transcript` = `"WEBVTT\n\n\n00:00:00.620 --> 00:00:03.500\nI had someone ask me ..."`.
- **Comments** (`GET /v1/tiktok/video/comments?url`): 200, body has `comments[]` (page of up to 20), `cursor`, `has_more`,
  `total`. Each comment has `text`, `digg_count`, `create_time`, `comment_language`, `user`, `is_high_purchase_intent`, ...
- **Credits:** the account had 100 free credits; 97 remain after this check. A full scan needs about 850.

## Deviations from the plan

- **Creator bio is not available from search results** (`author.signature` is absent). `parse_video` already falls back to
  `""`, so `creator_bio` in Jev state will be empty. Fetching bios would cost one profile request per creator; not done in v1.
- Not used in v1 but worth knowing: `aweme_info.is_ad`, `aweme_info.is_paid_partnership` (could complement Jev's
  `is_promotional`) and comments' `is_high_purchase_intent` (could complement the `spend` score).

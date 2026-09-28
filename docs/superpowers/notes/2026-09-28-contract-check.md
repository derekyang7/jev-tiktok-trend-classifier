# Live contract check (spec §14.1): findings

Run on 2026-09-28 with `scripts/contract_check.py` (the Jev and LLM checks were run on their own because the
ScrapeCreators key was not yet in the secrets file).

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

## ScrapeCreators: PENDING

`SCRAPECREATORS_API_KEY` was not yet set in `~/Repos/.env.secrets`. Tasks 2–15 run offline, so they go ahead
using the documented field names (see below). Before Task 16, run the full script
(`scripts/with-secrets.sh uv run python scripts/contract_check.py`), record the search, transcript and comments
shapes here, and let Task 6's fixture test (`test_parses_recorded_contract_fixtures`) confirm the parser.

Documented shapes the plan relies on until then (docs.scrapecreators.com, fetched 2026-09-28):
- search: `GET /v1/tiktok/search/keyword?query&date_posted&sort_by&region&cursor&trim`;
  `search_item_list[].aweme_info.{aweme_id, desc, create_time, statistics.{play_count, digg_count, comment_count,
  share_count}, author.{uid, unique_id, nickname}, text_extra[].hashtag_name, music.title, desc_language}`, `cursor`.
- transcript: `GET /v1/tiktok/video/transcript?url&language` → `{"transcript": "WEBVTT..."}`.
- comments: `GET /v1/tiktok/video/comments?url&cursor` → `comments[].{text, digg_count}`, `cursor`, `has_more`.

## Deviations from the plan

None so far for Jev and the LLM.

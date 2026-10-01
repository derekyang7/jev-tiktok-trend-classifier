# TikTok Trends for UGC and Ads (`jevtrends ugc`): Design

| | |
|---|---|
| **Date** | 2026-09-30 |
| **Status** | Draft, awaiting user review |
| **Repo** | `jev-tiktok-trend-classifier` |
| **Package / CLI** | `jevtrends.ugc` / `jevtrends ugc` |
| **Builds on** | [V1 design](2026-09-28-tiktok-trend-classifier-design.md) (startup opportunities) |

## 1. Purpose

For one niche at a time, scan the last 14 days of TikTok and find the trends a brand can use in UGC and ads: video formats, hooks, sounds, topics and memes, and the audience needs that make good ad angles. The tool ranks trends by how fast they are growing, how well their videos perform and how usable they are for a brand, then writes creator briefs for the top ones. Every trend is traceable to real videos.

The user sells a consumer app and will use each report to brief UGC creators and plan ads. The niche is an input, so the tool works for any niche. An optional product profile tailors the ideas to one product.

V1 keeps working unchanged. This version reuses V1's plumbing and adds its own pipeline, database file and command group.

## 2. Decisions and assumptions

### 2.1 Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Purpose | Feed the user's own brand's UGC creator briefs and ad concepts. |
| Niche | An input per run, described in a niche file. The first niche is consumer apps. |
| Trend kinds | Formats and hooks, sounds, topics and memes, needs and angles. They are handled as five **facets**: `format`, `hook`, `sound`, `topic`, `need`. Every relevant video is tagged on every facet, instead of being assigned to a single trend as in V1. |
| Product | An optional product profile per run. With one, fit is judged for the product and briefs feature it. Without one, both are generic to the niche. |
| Output | Creator briefs for the top trends and short summaries for the rest. |
| Lookback | 14 days by default, overridable per run. |
| Seeing videos | Text (captions, transcripts, comments, TikTok metadata) plus a vision model that reads each video's cover frame and the first slides of slideshows ("approach B"). `--no-vision` turns the vision step off. |
| Where it lives | This repo, as the `jevtrends.ugc` subpackage and the `jevtrends ugc` command group, with its own database file. V1's behavior and database don't change. |
| Claude access | Through OpenRouter, reusing V1's client extended for images. This was the user's choice over Anthropic's SDK; no new API key is needed. |
| Models | Jev `typesafe/jev-1.13` for every judgment. Claude Opus 5.5 for discovery, niche drafts and briefs. Claude Haiku 4.5 for reading images. |
| Existing ads | Count as evidence. Each trend's ad share is shown but not used for ranking. |
| Sounds | Taken from TikTok's popular-songs list plus sounds that recur in the sample, and labeled `approved`, `organic_only` or `unknown` for business use. Briefs suggest approved sounds only. |
| Ranking | 0.25 momentum + 0.25 performance + 0.30 fit + 0.10 breadth + 0.10 ease, re-rankable without model calls. |
| Briefs | 11 per run by default: 3 formats, 2 hooks, 2 sounds, 2 topics, 2 needs. |
| Budget | Under $5 per run at 600 videos, enforced by the budget guard. As in V1, the guard cuts briefs before comments. |

### 2.2 Assumptions (confirmed)

- A local Python CLI on macOS for one user. Runs are on demand, and each writes a Markdown report and SQLite records.
- US region, English-language content.
- TikTok limits business accounts, and posts marked as branded content, to sounds from its Commercial Music Library. So licensing matters for any sound a brief suggests.

### 2.3 Findings from V1's data that shaped this design

Measured on V1's full scan (run 2: 1,000 videos from keyword search):

- **On-screen text never comes through.** `video_text` was empty for all 1,000 videos, and `content_desc` only repeats the caption. Text overlays can only be read from images.
- **Keyword search returns almost no slideshows.** 98% of results had `aweme_type` 0 (ordinary videos).
- **Sounds barely repeat in a keyword sample.** There were 970 distinct sounds. 25 were used by 2 or more videos and 3 by 3 or more, and 82% were original sounds (the creator's own audio). Sound trends can't be found by counting sounds in the sample.
- **TikTok's own ad flags are rare.** 6% of videos had `is_ad`, 1% `is_paid_partnership`, and 3% a non-zero `commerce_info.branded_content_type`.
- **Editing metadata gives partial format cues.** 44% of videos used TikTok's text tool, about 6% had a green-screen or template anchor, and 35% of V1's filtered videos had no transcript.
- **Follower counts and saves are present for every video,** so performance relative to reach can be computed in code.
- **The licensing fields disagree with one another.** Among the undocumented flags, `is_commerce_music` was true for 95% of sounds, `is_commerce_music_strict` for 72%, `has_commerce_right` for 90% and `has_commerce_right_strict` for 67%. None can be trusted without a check (§14.1).

### 2.4 Success criteria

1. A default run (600 videos) costs under $5 and finishes in 30 minutes or less.
2. Each report surfaces 5–15 trends, across the four kinds, that the user would brief a creator on, each traceable to real videos.
3. In the user's review (§14.4), tagging precision is at least 0.80 for each facet.

These are starting targets and may be adjusted.

## 3. Non-goals

- Tracking the same trend across runs (new, rising or fading).
- Full-video understanding: downloading videos, sampling frames across a video, or analyzing audio.
- Non-US or non-English content.
- TikTok's popular-hashtags list, TikTok Shop data, and Meta's or Google's ad libraries.
- Contacting creators, posting, or anything else that acts on TikTok.
- A dashboard, or exports beyond Markdown and SQLite.
- Re-briefing an existing run for a different product.
- Any change to V1's behavior or to its database.

## 4. External facts and constraints

### 4.1 Reused from V1

- **Jev**, as described in V1 §4.1: Noul, Choice and Score questions; a 32,000-token context; $0.042 per million input tokens; called at `POST https://openrouter.ai/api/v1/systemone`. Jev can't generate text, count or compare dates, so all counting, dates and arithmetic stay in code.
- **ScrapeCreators**, as described in V1 §4.2: about $0.00188 per credit, and 1 credit per request. The keyword-search, transcript and comments contracts were verified in V1's Step 0.

### 4.2 New ScrapeCreators endpoints

Taken from ScrapeCreators' documentation index. **All of them are verified in Step 0 (§14.1) before use.**

| Endpoint | Use |
|---|---|
| `GET /v1/tiktok/search/hashtag` | Videos for a niche hashtag. |
| `GET /v1/tiktok/search/top` | TikTok's "Top" results, which include photo slideshows. |
| `GET /v1/tiktok/songs/popular` | Popular songs. Reportedly filterable by period and country. |
| `GET /v1/tiktok/song/videos` | Videos that use a given song. |

Still unknown until Step 0:
- parameters, page sizes, sort orders and date filtering;
- which fields hold slideshow images and the largest usable cover image;
- how long image links stay valid;
- whether the popular-songs list offers TikTok's "approved for business use" filter or a per-song flag, and whether it returns trend data such as rank changes or a usage series.

### 4.3 Claude via OpenRouter

| Model | Used for | List price per million tokens (in / out) |
|---|---|---|
| Claude Opus 5.5 | `discover`, briefs, niche drafts | $4 / $20 |
| Claude Haiku 4.5 | reading cover frames and slides | $1 / $5 |

- As in V1, actual spend comes from OpenRouter's reported cost.
- Step 0 verifies:
  - the OpenRouter model slugs (expected `anthropic/claude-opus-5.5` and `anthropic/claude-haiku-4.5`);
  - JSON-schema output on both models;
  - image input as base64 data URLs;
  - how to set Opus 5.5's effort level through OpenRouter;
  - the usage and cost fields.
- Opus 5.5 always thinks and defaults to medium effort. Thinking tokens bill as output, so Opus output length varies from run to run.
- An image costs about (width × height) ÷ 750 tokens. Covers are scaled down to at most 960 px on the long edge, which makes a 540×960 cover about 700 tokens.

### 4.4 Sound licensing

A sound is labeled as follows:
- **`approved`** if a verified source marks it approved for business use. The source is the popular-songs business filter or per-song flag, or a raw TikTok flag that Step 0 shows agrees with that filter.
- **`organic_only`** if a verified source marks it as not approved.
- **`unknown`** otherwise.

The report names the source used for each label. If no verified source exists, every sound is `unknown`. Briefs then suggest original audio or a Commercial Music Library sound, and the report says "check before use".

## 5. Architecture

### 5.1 Pipeline

`jevtrends ugc scan` runs these stages in order. As in V1, stages communicate only through the store, so each can be tested, re-run or resumed on its own.

| # | Stage | What it does | External calls |
|---|---|---|---|
| 1 | `collect` | Keyword, hashtag and Top searches from the niche file; dedupes and stores video records with the new fields. | ScrapeCreators |
| 2 | `gate` | A lenient check on caption and hashtags: could this video be about the niche? | Jev |
| 3 | `enrich` | Transcripts for the videos that pass (not for slideshows); comments for the most-commented. | ScrapeCreators |
| 4 | `look` | Reads each surviving video's cover frame, and the first slides of slideshows: on-screen text and a one-line description of the setup. | Haiku 4.5, image downloads |
| 5 | `judge` | Per video: is it about the niche; is it promotional? | Jev |
| 6 | `sounds` | Builds sound candidates from the popular-songs list and the sample, and checks each against the niche. | ScrapeCreators, Jev |
| 7 | `discover` | Proposes candidate formats, hooks, topics and needs from one line per relevant video, and a usage note per sound. | Opus 5.5 |
| 8 | `assign` | Tags each relevant video on each facet, then prunes weak candidates. | Jev |
| 9 | `score` | Computes momentum, performance, breadth, ad share and pairs in code, and fit, ease and brand risk with Jev; then ranks. | Jev |
| 10 | `brief` | Writes creator briefs for the selected trends. | Opus 5.5 |
| 11 | `report` | Renders the Markdown report. | none |

### 5.2 Changes to shared code

All of these changes keep V1's behavior the same. **V1's test suite must pass unchanged.**

| Module | Change |
|---|---|
| `models.Video` | New optional fields: `duration_ms`, `is_slideshow`, `cover_url`, `slide_urls`, `sound_info` (id, title, author, original flag, TikTok use count, raw licensing flags), `author_followers`, `saves`, `editing_features`, `anchors`, `ad_flags` (`is_ad`, `is_paid_partnership`, `branded_content_type`). The existing `sound` title field stays. |
| `sources/scrapecreators.py` | `parse_video` fills the new fields. The cover link and duration come from the `video` object, which V1 leaves out of `raw`. New methods: `search_hashtag`, `search_top`, `popular_songs`, `song_videos`, `fetch_image`. V1's `Source` protocol is unchanged; a `UgcSource` protocol extends it. |
| `llm/client.py` | `complete_json` accepts optional images, sent as base64 data URLs, and an optional effort setting. Each model gets its own client instance. |
| `pipeline.py` | The stage loop, run-status handling and budget checks become a function that takes a stage list and a budget-check callback. V1 passes its current ones. |
| `budget.py` | `BudgetGuard` takes an ordered list of trimmable items, each with units, a cost per unit and a minimum. V1 passes briefs then comments, its current order. |
| `stages/context.py` | The helpers for recording API calls, `ask_jev` and reading answers move to a base context class. V1 and UGC each subclass it with their own config. `run_items` is reused as is. |
| `store.py` | Config snapshots are stored and returned as JSON, and each pipeline parses its own. UGC tables are created only in the UGC database. |

### 5.3 New modules (`src/jevtrends/ugc/`)

| Module | Responsibility |
|---|---|
| `config.py` | UGC settings, niche profile and product profile models, and their loaders (Pydantic). |
| `models.py` | `FacetTrend`, `SoundCandidate`, `VisionRead`, `UgcTrendScore`. |
| `store.py` | `UgcStore`, extending `Store` with the UGC tables (§8). |
| `questions.py` | The Jev question catalog (§7), with a version on every question. |
| `prompts.py` | The discover, brief, vision and niche-draft prompts and their output schemas. |
| `scoring.py` | Pure functions: performance, pairs, sound metrics, composite score, ranking and brief selection. V1's momentum and breadth functions are reused. |
| `budget.py` | The UGC cost projection and trims. |
| `pipeline.py` | The stage list, budget checks and `--estimate`. |
| `stages/` | `collect.py gate.py enrich.py look.py judge.py sounds.py discover.py assign.py score.py brief.py report.py` |
| `review.py` | Review sampling and metrics (§14.4). |
| `cli.py` | The `ugc` Typer sub-app, mounted on the main `jevtrends` app. |
| `templates/report.md.j2` | The report template. |

### 5.4 Layout

```
config/ugc/settings.yaml
config/ugc/niches/consumer_apps.yaml
config/ugc/products/example.yaml   # committed; other files in this folder are git-ignored
scripts/ugc_contract_check.py      # Step 0
src/jevtrends/ugc/                 # §5.3
data/ugc.db                        # git-ignored
reports/ugc/                       # git-ignored
```

### 5.5 Stack and secrets

- The stack is the same as V1's, plus Pillow for scaling images down.
- The only secrets are `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY`, loaded by `scripts/scan.sh` as in V1. There are no new keys.

## 6. Stage specifications

Settings appear in `code font` with their defaults (§9.1).

### 6.1 collect

- **Searches:**
  - a keyword search for each of the niche's `seed_queries`;
  - a hashtag search for each of its `hashtags`;
  - a Top search for each seed query when `scan.top_search: true`.
  
  The first niche has 15 queries and 8 hashtags, which makes 38 searches.
- **Window:** only videos posted in the last `lookback_days: 14` before the run starts are kept.
  - Keyword search asks for the smallest ScrapeCreators time frame that covers the window (`this-month`).
  - Step 0 shows whether hashtag and Top search accept a date or region parameter.
  - Every search is filtered by date in code.
- **Pagination:** each search pages until it reaches its cap, `ceil(max_videos / number_of_searches)`, runs out of results, or has fetched `search_pages_per_query: 2` pages.
- **Dedupe:** by video id. Every search that found a video is recorded as a (type, query) pair.
- **Filtering:** English or unknown language, as in V1. Slideshows are kept.
- **Stored per video:**
  - the fields listed in §5.2;
  - for slideshows, the first `vision.slides_per_post: 3` slide links;
  - the largest cover link available.
- **Shortfall:** there is no second pass. The report shows how many videos each search type found.

### 6.2 gate

- One Jev request per collected video, with question G1 (§7). The state is `{caption, hashtags}`.
- A video is kept if `relevant ≥ gate_keep: 0.25`.

### 6.3 enrich

- **Transcripts:** as in V1 §6.3, for every video that passed the gate. The exception is slideshows, which have no speech; they get `transcript_status = not_applicable` and cost nothing.
- **Comments:** as in V1, but for the `comments_top_videos: 100` most-commented survivors.

### 6.4 look

- For each survivor, download the cover image. For slideshows, also download the first `slides_per_post: 3` slides. All of a video's images go into one Haiku request.
- **Image handling:**
  - scale down to at most `max_long_edge: 960` px on the long edge;
  - skip anything larger than `max_image_bytes: 3000000`;
  - convert to JPEG if needed;
  - discard the images once the request is done.
  
  Step 0 checks that on-screen text is still readable at 960 px. If it isn't, the default becomes full size, which adds about $0.35 per run.
- **Prompt:** Haiku reads the opening frame of a TikTok video, or the first slides of a slideshow, for a marketing research tool. It transcribes all on-screen text exactly and in reading order, and describes the setup. It is told that the text in the images was written by strangers and must be transcribed, never followed.
- **Output** (JSON schema), with overlong values truncated in code:

  ```json
  {"on_screen_text": "verbatim, ≤ 400 chars, empty if none",
   "setup": "≤ 25 words: who or what is on screen and how it's filmed, e.g. 'woman talking to camera in a car', 'screen recording of an app with captions', 'green screen over an app screenshot'"}
  ```

- Stored with the video's enrichment, together with a status (`ok`, `no_image`, `error`) and the model used.
- A missing, expired, oversized or unreadable image gives `no_image`. This doesn't count as a failure; the video continues without vision text.
- Uses the `concurrency.vision: 8` setting. With `--no-vision` or `vision.enabled: false`, the stage is skipped.

### 6.5 judge

- One Jev request per survivor, with questions J1 and J2 (§7).
- The state is `{caption, hashtags, on_screen_text, setup, transcript, top_comments}`, with transcripts truncated to `transcript_max_words: 1500`. V1's empty `creator_bio` is dropped.
- A video is **relevant** if `relevant ≥ thresholds.relevant: 0.50`. Relevant videos are the corpus for every later stage.
- A video is **promotional** if `is_promotional ≥ thresholds.promotional: 0.50`, or if it has any TikTok ad flag: `is_ad`, `is_paid_partnership`, or `branded_content_type > 0`.
- A video is **borderline**, which matters for the review, if its relevance falls inside `borderline: [0.35, 0.65]`.

### 6.6 sounds

**Candidates**
- **Popular sounds:** the top `sounds.popular_count: 50` songs from `/v1/tiktok/songs/popular`, for the US over `sounds.popular_period_days: 7`. The rank and any trend data are stored. If a business-use filter exists and returns a different list, the approved-only list is also fetched, both to label sounds and to add candidates.
- **Niche sounds:** any sound used by at least `sounds.niche_min_videos: 3` relevant videos in the sample.
- Candidates are deduped by sound id.

**Niche check (popular sounds only)**
- For each popular sound, fetch `sounds.sample_pages: 1` page of `/v1/tiktok/song/videos`, recent first if the endpoint allows it.
- Each sampled video gets one Jev request with question S1 (§7). The state is `{caption, hashtags}`.
- Sampled videos are stored in `videos` and `ugc_sound_samples`. They are not added to the run's corpus.

**Stored per sound:** title, author, source (`popular`, `niche` or both), popular rank, trend data, TikTok use count, business-use label and its source, and the sampled videos with their relevance.

**Metrics** (used in §6.9):
- **Niche creators:** distinct creators among the sound's relevant uses, meaning corpus videos using it plus sampled videos with `relevant ≥ 0.50`.
- **Niche share:** the fraction of sampled videos that are relevant. Shown in the report only.

Every sound candidate is scored. No sound is pruned. The report lists the top `sounds.report_count: 20`.

### 6.7 discover

**Digest.** Code builds one line per relevant video, with no generation. Videos are ordered by `relevant × log(1 + views)` and cut off once the digest reaches `discover_max_digest_tokens: 80000` (characters ÷ 4). Short ids map to TikTok ids in code, as in V1.

```
[v017] @handle | video 32s | edits: text, green_screen | promo: no | on-screen: "apps that feel illegal to know" | setup: "woman talking to camera in a car" | speech: "<first 25 words>" | caption: "<≤ 120 chars>" | sound: "<title>" (original) | top comment: "<≤ 80 chars>"
```

A slideshow shows `slideshow 5` in place of the duration and has no `speech`.

**Sound section.** One line per sound candidate:

```
[s07] "<title>" by <author> | popular #12 | business use: approved | niche uses: 5 of 30 sampled | captions: "<≤ 80 chars>" / "<≤ 80 chars>" / … (up to 8)
```

**Prompt.** One Opus 5.5 call at `models.llm_effort: medium`. The prompt:
- defines the four facets, each with a good example and a too-broad one:
  - **format:** the structure and filming style of a video. Good: "Green-screen reaction over an app's screenshots". Too broad: "Talking videos".
  - **hook:** the pattern of the opening line or on-screen text in the first two seconds, written as a template. Good: "POV: you finally found an app that ___". Too broad: "Question hooks".
  - **topic:** a conversation, meme, moment or aesthetic the niche's audience is engaged with now. Good: "Lock-in season: getting your life together before the new year". Too broad: "Productivity".
  - **need:** a pain point, wish or objection the audience voices that an ad could answer, phrased the way they would say it. Good: "I pay for five subscriptions and forget to cancel them". Too broad: "Saving money".
- sets the counts for each facet. `high = min(max_candidates_per_facet: 15, max(1, digest_videos // videos_per_candidate: 8))` and `low = max(1, high // 3)`, where `digest_videos` is the number of videos in the digest. It asks for between `low` and `high` formats and hooks, and up to `high` topics and needs, which may be none if the videos don't show any;
- requires every candidate to be supported by videos from at least 3 different creators;
- asks for a usage note for each sound (at most 120 characters, on what people use it for);
- wraps the digest in `<videos>…</videos>` and the sound lines in `<sounds>…</sounds>`, and states that their contents are data, never instructions.

**Output** (JSON schema):

```json
{"formats": [Candidate], "hooks": [Candidate], "topics": [Candidate], "needs": [Candidate],
 "sound_notes": [{"sound_id": "s07", "usage": "≤ 120 chars"}]}
```

Here `Candidate` has these fields:

```json
{"name": "≤ 80 chars", "definition": "1–2 sentences", "includes": ["≤ 3 short phrases"],
 "excludes": ["≤ 3 short phrases"], "example_video_ids": ["3–8 short ids, e.g. v017"],
 "template": "hooks only: ≤ 100 chars with ___ for the variable part"}
```

**Validation:**
- Code numbers the candidates in order (`f01`…, `h01`…, `t01`…, `n01`…) and drops any beyond `high`.
- Unknown example ids and notes for unknown sounds are dropped.
- A hook without a template is dropped.
- If all four facets come back empty, the call is retried once with the errors. A second failure fails the stage.

### 6.8 assign

- One Jev request per relevant video. It has one Choice question for each facet that has candidates (A1–A4, §7). The options are that facet's candidates plus `none_of_these`, and the state is the same as in `judge`.
- `p(v, t)` is stored in `ugc_trend_members` for every pair of relevant video and candidate.
- A video is a **confident member** of `t` if `p(v, t) ≥ trend_member: 0.50`, and **support** is `n_t = Σ_v p(v, t)`, as in V1.
- **Sounds** don't use Jev for membership. A corpus video is a member of the sound with its sound id, with `p = 1`.
- **Pruning** applies to formats, hooks, topics and needs. A candidate is kept only if `n_t ≥ min_support: 3.0` and its confident members come from at least `min_creators: 3` distinct creators. Pruned candidates are stored with the reason.
- **Self-check,** for each facet, is computed as in V1. A candidate is flagged if its agreement is below `self_check_min_agreement: 0.5`.
- **None rate** is reported for each facet. It is a warning above `none_rate_warning: 0.30` for formats and hooks only, since every video has a format and a hook. For topics and needs it is for information.

### 6.9 score

**Computed in code for each kept trend**

- **Momentum:** V1 §6.7's formula, applied to relevant videos, with `momentum_recent_fraction: 0.333` and `momentum_pseudo_count: 2`. With 14 days, the recent window is the last 4.7 days.
  - **Sounds, first choice:** if the popular-songs data includes a usage series for the sound, the ratio is the mean of its most recent third divided by the mean of the whole series, normalized with the same `log2` mapping.
  - **Sounds, otherwise:** a sound with at least 3 corpus uses gets the corpus formula, with those uses as members. Any other sound gets 0.5, and the report notes it.
- **Performance:**
  - `reach(v) = views / max(followers, follower_floor: 1000)` and `eng(v) = (saves + shares) / max(views, 1)`.
  - `R_t` and `E_t` are the medians over the trend's confident members. `R` and `E` are the medians over all relevant videos.
  - `x_t = log2(R_t / R) · n / (n + k)`, where `n` is the number of confident members and `k = performance_pseudo_count: 2`. This pulls small trends toward a ratio of 1×. The same is done for engagement.
  - `reach_norm = clip((x_t + 2) / 4, 0, 1)`, the same mapping as momentum, and likewise for `eng_norm`. `performance_norm = (reach_norm + eng_norm) / 2`.
  - If `R` or `E` is 0, performance is 0.5.
  - Sampled song videos aren't a random sample, so a sound's performance uses corpus uses only. It is 0.5 if the sound has fewer than 3 of them.
- **Breadth:** V1's formula, `min(1, ln(1 + creators) / ln(21))`. For formats, hooks, topics and needs, `creators` counts the distinct creators among confident members. For sounds it is the niche creators from §6.6.
- **Pairs:** for trends `a` and `b` from different facets, `co(a, b) = Σ_v p(v, a) · p(v, b)` over relevant videos, and `lift = co · N / (n_a · n_b)`. Each trend keeps up to 3 partners with `co ≥ pair_min_videos: 2.0` and `lift ≥ pair_min_lift: 1.5`, ranked by `co`.
- **Shown in the report only:**
  - ad share, `Σ_v p(v, t) · [promotional(v)] / n_t`;
  - median views;
  - the reach and engagement ratios.

**Scored by Jev.** One request per kept trend and per sound candidate, with questions T1 (or T1p when a product profile is given), T2 and T3 (§7). The state is:

```json
{"niche": {"name": "…", "covers": "…", "audience": "…"},
 "product": {"name": "…", "what_it_does": "…", "audience": "…"},
 "trend": {"facet": "format", "name": "…", "definition": "…", "template": "hooks only", "usage": "sounds only"},
 "evidence": [{"caption": "…", "on_screen_text": "…", "setup": "…", "transcript_excerpt": "≤ 150 words", "top_comments": ["up to 3"]}]}
```

- `product` is included only when a profile is given.
- The **evidence set** is the `evidence_per_trend: 12` members with the highest `p(v, t)`. As in V1, members with `p < 0.2` are excluded.
- For sounds, the evidence set is corpus uses first, then relevant sampled uses ordered by views. Sampled uses have captions only.
- `fit_norm = fit / 3` and `ease_norm = ease / 3`. A trend is **risky** if `brand_risk ≥ thresholds.brand_risk: 0.50`.

**Score:**

```
score = 0.25·momentum_norm + 0.25·performance_norm + 0.30·fit_norm + 0.10·breadth_norm + 0.10·ease_norm
```

- The weights come from `ranking.weights` and must sum to 1.
- Every component is stored, so `jevtrends ugc report <run> --weights …` can re-rank without any model calls. Re-ranking changes the order only; it never writes new briefs.
- Trends are ranked within each facet and also overall.

### 6.10 brief

**Selection**
1. For each facet, in the order `format`, `hook`, `sound`, `topic`, `need`, take its top `briefs.quotas` eligible trends by score. The quotas are 3, 2, 2, 2 and 2. **Eligible** means kept and not risky; sounds must also be `approved`.
2. If fewer than the sum of the quotas (11) are selected, fill the remaining places with the highest-scoring eligible trends from any facet.
3. Budget cuts remove the lowest-scoring briefs first, down to `min_briefs: 5`. A facet's last brief is never removed while another facet still has more than one.

**Input.** One Opus 5.5 call per selected trend, with concurrency 5. Everything below is wrapped in `<trend_data>…</trend_data>` and marked as data:
- the niche;
- the product profile, if any, with its allowed claims numbered `c1`, `c2` and so on, and its claims to avoid;
- the trend: facet, name, definition, and its template or usage note;
- stats: support, creators, momentum ratio, reach and engagement ratios, ad share, median views;
- Jev's fit and ease scores, with confidence;
- the evidence set from §6.9. Each video is labeled `e01`, `e02` and so on and includes handle, caption, on-screen text, setup, a transcript excerpt of up to 200 words, the top 3 comments, views, followers, saves, shares, post date, promotional flag, and duration or slide count;
- the trend's pairs from other facets (up to 3): id, facet, name, definition or template;
- the top 5 approved sounds by score, with their usage notes.

**Output** (JSON schema):

| Field | Content |
|---|---|
| `title` | ≤ 80 chars |
| `why_its_working` | 2–3 sentences, based on the evidence |
| `concept` | 1–2 sentences on the video to make. It features the product when there is a profile; otherwise it's written for "a brand in `<niche>`" |
| `hooks` | 3–5 opening lines, spoken or on-screen, each ≤ 100 chars and following the trend's pattern |
| `beats` | 3–6 items, each `{time, action, on_screen_text}` |
| `sound` | `{sound_id or "original_audio", why}` |
| `pairs_with` | Ids from the pairs given (may be empty) |
| `dos` | 2–4 items |
| `donts` | 2–4 items |
| `cta` | ≤ 100 chars |
| `claims_used` | Ids of the allowed claims used (empty without a profile) |
| `evidence` | 3–5 items, each `{video_id, why}` |
| `risks` | 1–3 items, e.g. saturation, claims, brand fit |

**Rules in the prompt:**
- Ground every statement in the evidence, and don't invent numbers, companies or quotes.
- Product claims may come only from the allowed claims, cited by id, and never from the claims to avoid.
- The sound must be one of the approved sounds listed, or original audio. When no sound is approved, the brief uses `original_audio`, and its `why` may suggest picking a sound from TikTok's Commercial Music Library.
- The hooks must follow the trend's pattern.

**Validation:**
- Cited evidence ids must belong to the evidence set; other ids are dropped. If none remain, the call is retried.
- `pairs_with` ids outside the given pairs are dropped.
- An unknown claim id, or a sound that is neither approved nor `original_audio`, causes a retry.
- If no item in `dos` mentions disclosure, code adds "Disclose the paid partnership with TikTok's branded-content setting or #ad."
- There is one retry, as in V1. After a second failure the trend has no brief, and the report notes it.

**Unbriefed trends** get a summary made from their `discover` definition and stats, at no extra cost.

### 6.11 report

Written to `reports/ugc/<YYYY-MM-DD>-<niche_id>-run-<run_id>.md` from `ugc/templates/report.md.j2`. It has seven parts:

1. **Header:**
   - niche and product (or "generic");
   - the window and run status;
   - funnel counts: collected by search type → passed gate → relevant → images read → candidates proposed and kept per facet → sound candidates;
   - actual cost by provider;
   - budget cuts and notes.
2. **Top picks:** the top `briefs.top_picks: 15` trends across all facets, with columns rank, facet, trend, momentum ratio, reach ratio, creators, fit, ease, ad share, score, and whether it has a brief.
3. **Formats and hooks:**
   - Each briefed trend (formats first, then hooks) shows its stats line, its definition (plus the template for hooks), the brief, and 3–5 evidence videos, with the brief's cited videos first.
   - A table then lists the other kept trends with a one-line definition, score and risk flag.
4. **Sounds:**
   - the briefed sounds;
   - a table of the top 20 candidates: title and author with a link to the sound's page (URL format confirmed in Step 0), business-use label, usage note, niche creators, niche share, TikTok use count, momentum, fit and score.
5. **Topics and memes:** the same layout as part 3.
6. **Needs and angles:** the same layout as part 3.
7. **Diagnostics:**
   - none rates and self-check flags for each facet;
   - the number of borderline videos;
   - vision coverage (`ok`, `no_image`, `error`) and transcript coverage;
   - failed items by stage;
   - the licensing source and caveat;
   - momentum caveats;
   - a snapshot of the settings used.

Each evidence video shows its link, handle, views, reach ratio (views ÷ followers), saves, shares, post date, promotional flag, on-screen text, a transcript snippet (or the setup, for slideshows), a top comment, and the brief's reason for citing it.

## 7. Jev question catalog (all version 1)

In code, question ids are prefixed by stage. `niche` and `product` objects are built from the run's profiles.

**G1 `ugc_gate.relevant`** (Noul)
- *Instructions:*

  ```json
  {"question": "Could this video be about the niche described in `niche`, judging by its caption and hashtags?",
   "niche": {"name": "…", "covers": "…", "not_for": "…"}}
  ```

- *True:* "The caption or hashtags mention or hint at anything the niche covers, even vaguely, or give too little information to tell."
- *False:* "The caption and hashtags clearly point to something the niche does not cover."

**J1 `ugc_judge.relevant`** (Noul)
- *Instructions:*

  ```json
  {"question": "Is this video about the niche described in `niche`?", "niche": {"name": "…", "covers": "…", "not_for": "…", "audience": "…"}}
  ```

- *True:* "The video's main subject is something the niche covers: its products, how people use them, or the needs, habits and conversations of the niche's audience."
- *False:* "The niche appears only in passing, or the video is about something else."

**J2 `ugc_judge.is_promotional`** (Noul): the wording of V1's Q4, verbatim.

**S1 `ugc_sounds.relevant`** (Noul): J1's wording, applied to a sampled song video's caption and hashtags only. It has its own id so its answers never collide with J1's for the same video.

**A1–A4 `ugc_assign.format`, `.hook`, `.topic`, `.need`** (Choice)

| Question | Instructions |
|---|---|
| A1 format | "Which of these video formats does this video use?" |
| A2 hook | "Which of these hooks does this video open with, in its first spoken line or on-screen text?" |
| A3 topic | "Which of these topics, memes or moments is this video mainly about?" |
| A4 need | "Which of these audience needs, pain points or wishes does this video mainly express or respond to?" |

- There is one option per candidate, keyed by trend id:
  - `what` = "<name>. <definition> Includes: <includes>." Hooks add " Template: <template>."
  - `not_for` = "<excludes>".
- `none_of_these`: "None of the options clearly fits this video."

**T1 `ugc_trend.fit`** (Score, used without a product profile)
- *Instructions:* "How naturally could a brand in this `niche` use this `trend` in an ad or a sponsored creator video?"
- *Levels*, from 0 to 3:
  0. It would feel forced or off-brand for almost any brand in the niche.
  1. Possible, with a stretch, for a few brands.
  2. A natural fit for many brands in the niche.
  3. Made for it: brands in the niche could use it almost as is, or already do.

**T1p `ugc_trend.product_fit`** (Score, used with a product profile, in place of T1)
- *Instructions:* "How naturally could this `product` feature in a video that uses this `trend`?"
- *Levels*, from 0 to 3:
  0. The product would feel forced or out of place.
  1. It could appear, but only with a stretch.
  2. It fits naturally as a supporting element.
  3. The trend is an ideal way to show the product's main benefit.

**T2 `ugc_trend.ease`** (Score)
- *Instructions:* "How easily could one creator with a phone make a video that uses this `trend`?"
- *Levels*, from 0 to 3:
  0. It needs a production team, special locations, celebrities, or skills few creators have.
  1. It needs props, several people, or careful editing.
  2. One creator can do it with some setup or editing.
  3. One creator, a phone, and under an hour.

**T3 `ugc_trend.brand_risk`** (Noul)
- *Instructions:* "Could using this `trend` in an ad embarrass or harm a brand?"
- *True:* "It involves offensive, sexual or shocking content, politics, tragedy, mocking a person or group, dangerous acts, or copyrighted characters."
- *False:* "Ordinary content that is safe for brands."

## 8. Data model (`data/ugc.db`)

JSON-valued columns are stored as TEXT.

**Shared tables** have the same schema as V1: `runs`, `videos`, `run_videos`, `enrichments`, `judgments`, `api_calls`.
- `runs.settings_snapshot` holds the UGC settings, and `runs.niches_snapshot` holds `{niche, product}`.
- `run_videos.seed_queries` holds the (type, query) pairs that found each video.
- The vision result is stored in the enrichment's data as `vision: {on_screen_text, setup, status, model}`.
- `api_calls.provider` gains one value, `vision`, next to V1's `scrapecreators`, `jev` and `llm`.

**New tables:**

| Table | Key columns |
|---|---|
| `ugc_trends` | `run_id`, `trend_id`, `facet` (`format`, `hook`, `topic`, `need`, `sound`), `data` (name, definition, includes, excludes, template, usage, example video ids, sound id), `status` (`proposed`, `kept`, `pruned`), `prune_reason`, `self_check_agreement` |
| `ugc_trend_members` | `run_id`, `trend_id`, `video_id`, `probability` |
| `ugc_sounds` | `run_id`, `sound_id`, `data` (title, author, source, popular rank, trend data, TikTok use count, business use and its source), `niche_creators`, `niche_share` |
| `ugc_sound_samples` | `run_id`, `sound_id`, `video_id`, `relevant` |
| `ugc_trend_scores` | `run_id`, `trend_id`, `facet`, `data` (every component and display metric), `score`, `rank_overall`, `rank_in_facet` |
| `ugc_pairs` | `run_id`, `trend_id`, `partner_id`, `co`, `lift` |
| `ugc_briefs` | `run_id`, `trend_id`, `model`, `brief`, `status` (`ok`, `failed`), `created_at` |
| `ugc_reviews` | `run_id`, `trend_id`, `video_id` (null for trend-level answers), `field`, `value`, `reviewed_at` |

Every sound candidate also gets a row in `ugc_trends` with facet `sound` and id `s01` and so on. That way scoring, ranking, briefs and the report treat all facets alike.

## 9. Configuration

### 9.1 `config/ugc/settings.yaml` defaults

```yaml
scan:
  lookback_days: 14
  max_videos: 600
  region: US
  search_pages_per_query: 2
  top_search: true
thresholds:
  gate_keep: 0.25
  relevant: 0.50
  promotional: 0.50
  trend_member: 0.50
  brand_risk: 0.50
  borderline: [0.35, 0.65]
enrich:
  transcript_max_words: 1500
  comments_top_videos: 100
  comments_per_video: 20
  comment_max_chars: 300
  comments_refresh_days: 7
vision:
  enabled: true
  slides_per_post: 3
  max_long_edge: 960
  max_image_bytes: 3000000
  on_screen_text_max_chars: 400
sounds:
  popular_count: 50
  popular_period_days: 7
  sample_pages: 1
  niche_min_videos: 3
  report_count: 20
trends:
  discover_max_digest_tokens: 80000
  videos_per_candidate: 8
  max_candidates_per_facet: 15
  min_support: 3.0
  min_creators: 3
  none_rate_warning: 0.30          # formats and hooks only
  self_check_min_agreement: 0.5
  momentum_recent_fraction: 0.333
  momentum_pseudo_count: 2
  performance_pseudo_count: 2
  follower_floor: 1000
  evidence_per_trend: 12
  pair_min_videos: 2.0
  pair_min_lift: 1.5
ranking:
  weights: {momentum: 0.25, performance: 0.25, fit: 0.30, breadth: 0.10, ease: 0.10}
briefs:
  quotas: {format: 3, hook: 2, sound: 2, topic: 2, need: 2}
  min_briefs: 5
  top_picks: 15
models:
  jev: typesafe/jev-1.13
  llm: anthropic/claude-opus-5.5         # slug confirmed in Step 0
  vision: anthropic/claude-haiku-4.5     # slug confirmed in Step 0
  llm_effort: medium
pricing:                                 # for projections; actual spend comes from API usage
  jev_input_per_mtok: 0.042
  llm_input_per_mtok: 4.00
  llm_output_per_mtok: 20.00
  vision_input_per_mtok: 1.00
  vision_output_per_mtok: 5.00
  tokens_per_image: 700
  vision_expected_output_tokens: 150
  scrapecreators_per_credit: 0.00188
  discover_expected_output_tokens: 25000
  brief_expected_output_tokens: 5000
budget:
  max_usd_per_scan: 5.00
concurrency: {jev: 16, scraper: 5, llm: 5, vision: 8}
retries: {max_attempts: 4, base_delay_s: 1, max_delay_s: 30}
failure:
  max_item_failure_rate: 0.20
llm:
  use_json_schema: true
```

### 9.2 Niche profiles: `config/ugc/niches/<id>.yaml`

`name`, `covers`, `not_for` and `seed_queries` are required. `audience` and `hashtags` are optional. This is the first niche; it's a draft for the user to edit to match their app's category:

```yaml
id: consumer_apps
name: Consumer apps
covers: "Mobile and web apps people use in everyday life (productivity, habits, money, health and fitness, dating, social, learning, lifestyle and utilities): how people discover, use, recommend, compare and complain about them, and the everyday goals and frustrations these apps serve."
not_for: "Software used mainly by businesses; physical products; mobile games; tech news with no everyday use."
audience: "US adults, mostly 18 to 40, who use apps to organize, improve or enjoy daily life."
seed_queries: [apps you need, this app changed my life, app recommendation, apps that feel illegal to know,
               apps i can't live without, underrated apps, best apps, is there an app for, what's on my phone,
               iphone apps, productivity apps, habit tracker app, budgeting app, ai app, app review]
hashtags: [apps, appsyouneed, iphoneapps, productivityapps, apprecommendations, musthaveapps, techtok, appreview]
```

`jevtrends ugc niche-draft` (§10) writes new files in this format.

### 9.3 Product profiles: `config/ugc/products/<id>.yaml` (optional)

The only product file committed to git is `example.yaml`, which describes a fictional app:

```yaml
id: example
name: StreakBuddy
one_liner: "A habit tracker that turns goals into daily streaks with friends."
what_it_does: "Users pick habits, check them off each day, and keep streaks going with friends who can see their progress."
audience: "Students and young professionals who struggle to stay consistent."
key_benefits: ["Streaks with friends keep you accountable", "Takes ten seconds a day"]
claims_allowed:
  - {id: c1, text: "Free to download"}
  - {id: c2, text: "Works on iPhone and Android"}
claims_to_avoid: ["Health or medical outcomes", "Guaranteed results"]
tone: "Friendly, practical, a little playful"
```

Claim ids must be unique and look like `c1`, `c2` and so on.

## 10. CLI

| Command | What it does |
|---|---|
| `jevtrends ugc scan --niche ID [--product ID] [--lookback-days N] [--max-videos N] [--budget USD] [--no-vision] [--estimate]` | Runs a full scan. With `--estimate`, it prints the projected cost per provider and the guard's planned cuts, then exits without spending anything. |
| `jevtrends ugc resume RUN [--budget USD]` | Continues a failed or budget-stopped run, redoing only missing work. The run's niche, product and settings come from its snapshot. |
| `jevtrends ugc report RUN [--weights momentum=0.25,…]` | Re-ranks and re-renders the report without any model calls. |
| `jevtrends ugc runs` | Lists UGC runs with date, niche, product, status and cost. |
| `jevtrends ugc niche-draft ID "DESCRIPTION"` | One Opus 5.5 call drafts `config/ugc/niches/ID.yaml`: covers, not_for, audience, 12–20 seed queries (a mix of topic queries and format-style queries such as "apps you need") and 5–10 hashtags. It refuses to overwrite an existing file, and the file opens with a comment asking the user to review it. Costs about $0.05. |
| `jevtrends ugc review RUN [--trends 20]` | An interactive quality review (§14.4). |
| `jevtrends ugc eval RUN` | Prints quality metrics from the review. |

`scripts/scan.sh` wraps all of these, as in V1: for example, `scripts/scan.sh ugc scan --niche consumer_apps`.

## 11. Cost model (per run, at defaults)

The estimate assumes 80% of videos pass the gate, 70% of those are relevant, and 10% of survivors are slideshows.

| Item | Units | Estimated cost |
|---|---|---|
| Searches | ~57 requests (38 searches, 1–2 pages each) | $0.11 |
| Transcripts | ~430 requests (videos only) | $0.81 |
| Comments | 100 requests | $0.19 |
| Popular songs and song pages | ~53 requests | $0.10 |
| Jev (gate 600, judge 480, sound checks ~1,500, assign ~340, trend questions ~90) | ~5.8M input tokens, with a 1.2× margin | $0.29 |
| Vision, Haiku 4.5 | ~480 requests, ~580 images at ≤ 960 px | $0.95 |
| LLM `discover`, Opus 5.5 | ~70k tokens in, ~25k out including thinking | $0.78 |
| LLM briefs, Opus 5.5 | 11 × (~7.5k in, ~5k out) | $1.43 |
| **Total** | | **≈ $4.70** |

The expected duration is about 20 minutes. The long single `discover` call and the briefs take the most time.

## 12. Error handling and budget guard

### 12.1 Budget guard

- **Projection:** as in V1 §12.1. Before each stage, the guard projects that stage plus every later stage, using actual counts where they're known.
  - Before counts are known, it assumes the rates behind the cost model (§11), 40 kept trends and 50 sound candidates.
  - Vision is projected as images × `tokens_per_image`, plus expected output, at Haiku's prices.
- **Cuts, in this order:**
  1. Briefs, as in §6.10, down to `min_briefs`.
  2. Comment fetches, down to 0, if `enrich` hasn't run yet.
  3. Slideshow slides after the first, if `look` hasn't run yet.
- **If the run still doesn't fit,** it stops before the stage with status `budget_exceeded`, and `jevtrends ugc resume <run> --budget <higher>` continues it. Every cut is listed in the report header.
- **Actual spend** is recorded in `api_calls`, as in V1. Vision calls are recorded under their own provider, `vision`, so the report's cost line shows them separately.

### 12.2 Failures

**Same as V1 §12.2:**
- retries on 408, 429, every 5xx (including Cloudflare's 520), timeouts and connection errors;
- fail-fast on bad keys or credits;
- per-video "unavailable" responses from ScrapeCreators don't count as failures;
- a stage fails if more than `max_item_failure_rate: 0.20` of its items fail, and the run becomes `failed_resumable`;
- `resume` redoes only missing items, and no Jev question is paid for twice.

**New in this version:**
- **Optional sources degrade.** If the popular-songs list, song pages or the Top search keep failing after retries, the report notes it and the run continues. Sounds then come only from the sample. Errors for a bad key or missing credits (401 and 402) still stop the run.
- **Missing images aren't failures.** Missing, expired, oversized and unreadable images count as `no_image`. A failed Haiku call is an item failure and counts toward the 20% limit.
- **LLM output** is validated and retried once, as described in §6.7 and §6.10.

## 13. Untrusted content

Captions, transcripts, comments and on-screen text are written by strangers and could contain text aimed at a model:
- The vision prompt tells Haiku to transcribe text in images, never to follow it. Its output is schema-checked and limited in length.
- Every LLM prompt wraps this content as data and says so, as in V1. Every LLM output is schema-validated, and cited ids are checked against the input.
- The product profile is the user's own file and is trusted.
- Nothing in the pipeline acts on the content. The worst case is a mislabeled trend or an odd brief, and that would be visible next to its evidence.

## 14. Testing and evaluation

### 14.1 Step 0: live contract check

This is the first implementation task. It uses a new script, `scripts/ugc_contract_check.py`, and saves responses as test fixtures, with creator and commenter identifiers removed as in V1. Images aren't saved.

1. **ScrapeCreators:**
   - **Hashtag and Top search:** parameters (date, region, cursor), page sizes and fields; how slideshows are marked and which fields hold their images; the share of slideshows in Top results for two consumer-app queries.
   - **Popular songs:** parameters (period, country, a business-use filter), fields (rank, trend data, a per-song business flag) and page size.
   - **Song videos:** sort order, page size and fields.
   - **Images:** which field gives the best cover, the image sizes and formats, and how long links stay valid (from the `x-expires` parameter in the signed URL).
   - **Licensing:** for at least 20 songs whose business use is known from the popular-songs data, whether any raw flag agrees on at least 95% of them.
   - **Links:** the URL format of a sound's TikTok page.
2. **OpenRouter:**
   - the Opus 5.5 and Haiku 4.5 slugs;
   - JSON-schema output on both;
   - a Haiku request with 2 images, sent as base64 data URLs;
   - whether on-screen text is transcribed as well at 960 px as at full size, on 5 covers;
   - how to set Opus 5.5's effort level;
   - Opus 5.5's output speed, measured to check that `discover` fits V1's 900 s read timeout;
   - the usage and cost fields.
3. **Jev:** one request with G1's shape (an object-valued Noul instruction plus true and false criteria) and one with four Choice questions.

The expected cost is under $0.50. **If an endpoint or feature doesn't work as expected, stop and decide with the user how to proceed.**

### 14.2 Unit tests (offline, pytest)

- **Scoring:**
  - performance, including the follower floor, shrinkage and zero baselines;
  - pairs and lift;
  - sound momentum, breadth and performance;
  - the composite score and per-facet ranking;
  - brief selection: quotas, excluding risky and unapproved trends, refilling, and budget cuts that keep one brief per facet.
- **Budget:** UGC projection and cut order. V1's budget tests pass unchanged.
- **Config:** validation of niche and product profiles, weights and quotas.
- **Questions:** rendering of facet choices, the niche and product objects, and versions.
- **Digest:** lines for videos and slideshows, the sound section, and short-id mapping.
- **Vision:** image checks and scaling, output parsing and length limits.
- **LLM output:** discover validation; brief validation (evidence, pairs, claims, sound, the added disclosure line).
- **Sources:** parsing of the new endpoints from fixtures. V1's parsing tests still pass with the new fields.
- **Report:** rendering, as a snapshot test.

### 14.3 Offline end-to-end tests

- Fake scraper, Jev, LLM and vision clients, driven by fixtures, run the full UGC pipeline on about 30 videos (including 3 slideshows) and 3 sounds, and produce a report.
- A second test interrupts a run during `look`, and again during `assign`, then resumes it. It checks that no call is repeated and that the results are identical.
- V1's unit and end-to-end tests pass unchanged.

### 14.4 Quality review

`jevtrends ugc review <run>` goes through the top `--trends 20` kept trends by score, across all facets. For each trend, it shows the facet, name, definition (or template or usage note) and 3 evidence videos with their links, captions and on-screen text. The user answers:

1. Is this a real, distinct trend?
2. Would you brief a creator on it?
3. For formats, hooks, topics and needs only: does each of 4 random confident members, and up to 2 random members with `p` between 0.35 and 0.50, fit the trend? Sound membership is exact, so sounds skip this question.

Answers are stored in `ugc_reviews`. `jevtrends ugc eval <run>` then reports:
- the number of real trends and would-brief trends, per facet and overall (success criterion 2);
- tagging precision per facet, on confident members (success criterion 3);
- a suggested `trend_member` threshold: the lowest of 0.35, 0.50 and 0.65 at which reviewed members at or above it have a precision of at least 0.80;
- a caveat that samples this small give rough estimates.

Niche-relevance precision isn't measured separately. Videos that are off-niche show up as bad tags.

## 15. Risks

| Risk | Mitigation |
|---|---|
| The popular-songs endpoint has no business-use data, and the raw flags are unreliable | Sounds are labeled `unknown`, briefs suggest original audio or a Commercial Music Library sound, and the report says "check before use". |
| A cover frame often isn't the hook frame (custom covers) | The setup description still helps. The diagnostics show vision coverage, and full-video frames are future work. |
| The Top search finds few recent slideshows | The report shows counts per search type, and seed queries and hashtags can be added. |
| 600 videos give thin evidence per trend | Pruning keeps trends honest. `--max-videos` and `--budget` can be raised for a run. |
| Jev's accuracy across four choice questions | Each facet has its own none rate and self-check, and the review measures tagging precision. |
| The LLM proposes overlapping candidates across facets, e.g. a hook that is really a format | Facet definitions with good and too-broad examples, plus excludes. The review asks whether each trend is distinct. |
| Opus 5.5's output, including thinking, varies in length | The guard projects with generous output estimates and cuts briefs first. |
| The long `discover` call hits V1's 900 s read timeout | Step 0 measures the output speed. If needed, `discover` is split into two calls (formats and hooks; topics and needs). |
| Image links expire before `look` runs on a resumed run | Missing images aren't failures, and the report counts them. |
| A brief makes claims about the product that the user can't support | Claims are limited to the allowed list and checked by id, and disclosure is always included. The user reviews every brief before use. |
| Vendor changes, or TikTok terms-of-service risk | The vendor is isolated behind the source adapter, as in V1. |

## 16. Future work

- Tracking trends across runs (new, rising, fading), starting with sounds, whose ids are stable.
- Re-briefing an existing run for another product without re-scanning.
- Full-video frames, for formats that unfold over time.
- TikTok's popular hashtags by industry, and comparisons with Meta's ad library.
- Scheduled runs.

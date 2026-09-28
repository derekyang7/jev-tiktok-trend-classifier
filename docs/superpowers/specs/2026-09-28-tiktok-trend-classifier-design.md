# TikTok Trend → Startup Opportunity Classifier: Design

| | |
|---|---|
| **Date** | 2026-09-28 |
| **Status** | Draft, awaiting user review |
| **Repo** | `jev-tiktok-trend-classifier` |
| **Package / CLI** | `jevtrends` |

## 1. Purpose

Scan recent TikTok content on demand to find **startup opportunities**: evidence of what people do, want, buy and struggle with. The tool groups that evidence into specific trends, maps each trend to business niches, ranks trends as opportunity signals, and writes a Markdown report in which every signal is traceable to real videos and comments.

Accuracy and explainability matter more than speed. The repo owner is the only reader, and the tool runs locally.

## 2. Decisions and assumptions

### 2.1 Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Purpose | Find startup opportunities. |
| What counts as a trend | Behaviors and needs; products and apps going viral; complaints and workarounds. TikTok-native formats (dances, sounds, memes) are out. |
| Data source | ScrapeCreators (third-party scraper API), behind a swappable interface. |
| Cadence | On-demand scans over a lookback window (default 30 days). Results are persisted. |
| Models | Jev for every per-video and per-trend judgment. Claude Opus 5, via OpenRouter, for the two generative steps: proposing trends and writing briefs. |
| Trend discovery | "LLM proposes, Jev assigns" (approach A). |
| Promotional videos | Count normally everywhere. They are labeled, and each trend's promotional share is shown in the report, but it does not affect ranking. |
| Niches | 11 niches, each with its own report section, plus an "Outside your niches" section. |
| Output | A Markdown report per scan, plus a SQLite database. |
| Budget | Under $5 per scan, all-in, enforced by a budget guard. |

### 2.2 Assumptions (confirmed)

- About 1,000 videos are collected per scan. Transcripts are fetched only for videos that pass Jev's filter, and comments only for the 150 most-commented of those.
- Niches live in an editable config file. A video or trend can belong to several niches or none.
- Content is English-language and from the US region.
- It is a Python CLI run locally on macOS by one user, with no hosting.
- "Emerging" means momentum inside the lookback window, computed in code.

### 2.3 Success criteria for v1

1. A real scan finishes in 30 minutes or less and costs under $5.
2. Against the user's hand labels (random sample):
   - signal detection reaches precision ≥ 0.80 and recall ≥ 0.70;
   - niche assignment reaches precision ≥ 0.80, micro-averaged across niches.

   These are starting targets and may be adjusted.
3. Each report surfaces 5–15 opportunity signals that the user judges worth a closer look, each traceable to real videos and comments.

## 3. Non-goals for v1

- TikTok-native formats as trends.
- Scheduled scans, matching the same trend across scans, or trend lifecycle tracking.
- A web dashboard, spreadsheet export or Notion export.
- Visual understanding (OCR, vision models) or self-hosted transcription. Only TikTok's own transcripts, fetched through the scraper, are used.
- Non-English or non-US content.
- Trend-level accuracy metrics. Trend quality is judged by reading the report.

## 4. External facts and constraints

### 4.1 Jev (TypeSafe)

Jev is a "System One" decision model: text goes in, and typed decisions with calibrated probabilities come out.

**Question types used here:**

| Type | Returns |
|---|---|
| **Choice** | One of up to 255 options, with the full probability distribution and a confidence value. |
| **Noul** | The probability that a yes/no statement is true. |
| **Score** | A probability-weighted position on 2–10 ordered levels, plus a confidence value. |

**Limits:**
- 32,000-token context.
- About $0.042 per million input tokens; output tokens are free.
- 70–500 ms per request.

**Known weaknesses.** Jev cannot reliably generate text, count, or compare dates. Irrelevant context distracts it, it reads instructions literally, and it works best in English. This design therefore keeps all counting, date handling and arithmetic in code.

**Access through OpenRouter.**
- The model is `typesafe/jev-1.13` (alias `~typesafe/jev-latest`).
- It is not served on `/chat/completions`. Calls go to `POST https://openrouter.ai/api/v1/systemone` with a body of `{model, state, questions}`.
- **This endpoint comes from a third-party guide. It is verified in Step 0 (§14.1) before anything else is built.**
- The model is pinned to `typesafe/jev-1.13` so that thresholds tuned on labels stay valid. Upgrading the model means re-running the evaluation.

### 4.2 ScrapeCreators

- A REST API. Most endpoints cost 1 credit per request, including keyword search (with date window, sort and region), comments, and transcripts.
- About $0.00188 per credit with the $47 / 25,000-credit pack. Credits do not expire, and new accounts get 100 free credits.
- Exact endpoint paths, page sizes and field names are verified in Step 0.

### 4.3 Claude Opus 5 via OpenRouter

- $5 per million input tokens and $25 per million output tokens. Thinking tokens bill as output.
- The slug `anthropic/claude-opus-5` and support for JSON-schema structured output are verified in Step 0.

## 5. Architecture

### 5.1 Pipeline

`jevtrends scan` runs these stages in order. Stages communicate only through the SQLite store, so each can be tested, re-run or replaced on its own.

| # | Stage | What it does | External calls |
|---|---|---|---|
| 1 | `collect` | Runs keyword searches from each niche's seed queries plus cross-niche phrases, dedupes, and stores video records. | ScrapeCreators |
| 2 | `gate` | Runs a lenient relevance check on caption and hashtags, and drops obvious entertainment. | Jev |
| 3 | `enrich` | Fetches transcripts for surviving videos, and comments for the most-commented of them. | ScrapeCreators |
| 4 | `judge` | Decides, per video: is it a signal, what type, is it promotional, and which niches. | Jev |
| 5 | `discover` | Reads one line per signal video and proposes candidate trends. | LLM |
| 6 | `assign` | Decides, per signal video, which trend it is evidence for (or none), then prunes weak trends. | Jev |
| 7 | `score` | Computes momentum, breadth and niches in code; gets pain / spend / underserved scores per trend from Jev; computes the opportunity score and ranking. | Jev |
| 8 | `brief` | Writes opportunity briefs for the selected trends. | LLM |
| 9 | `report` | Renders the Markdown report, re-ranking first if the weights were overridden. | none |

### 5.2 Modules

| Module | Responsibility |
|---|---|
| `config` | Loads and validates `config/settings.yaml` and `config/niches.yaml` with Pydantic. |
| `models` | Domain models: `Video`, `Enrichment`, `Judgment`, `Trend`, `TrendScore`, `Brief`. |
| `store` | SQLite schema and queries. Writes are upserts, so every stage is idempotent. |
| `sources` | The `Source` protocol (`search`, `transcript`, `comments`) and `ScrapeCreatorsSource`. |
| `jev` | `client.py` is an async client for the Jev endpoint: concurrency limit, retries, usage accounting. `questions.py` holds every Jev question, each with a version number. |
| `llm` | `client.py` is an async OpenRouter chat client with JSON-schema output. `prompts.py` holds the discover and brief prompts. |
| `scoring` | Pure functions: support, pruning, self-check, momentum, breadth, niche affinity, composite score, brief selection. |
| `budget` | Cost projection, the spend ledger, and trimming decisions. |
| `stages` | One module per pipeline stage. |
| `evaluation` | The labeling session and metrics. |
| `cli` | Typer commands (§10). |

### 5.3 Project layout

```
jev-tiktok-trend-classifier/
├── pyproject.toml
├── config/
│   ├── settings.yaml
│   └── niches.yaml
├── scripts/scan.sh
├── src/jevtrends/
│   ├── cli.py  config.py  models.py  store.py  budget.py  scoring.py  evaluation.py
│   ├── sources/   base.py  scrapecreators.py
│   ├── jev/       client.py  questions.py
│   ├── llm/       client.py  prompts.py
│   ├── stages/    collect.py  gate.py  enrich.py  judge.py  discover.py  assign.py  score.py  brief.py  report.py
│   └── templates/ report.md.j2
├── tests/         unit/  e2e/  fixtures/
├── data/          SQLite database (git-ignored)
└── reports/       generated reports (git-ignored)
```

### 5.4 Stack

- Python 3.12, uv, asyncio with httpx, Pydantic v2, PyYAML, Typer, Jinja2 (report template), stdlib `sqlite3`, pytest.
- `typesafe-sdk` is used for Jev only if Step 0 shows it works against OpenRouter's base URL. Otherwise Jev is called with httpx directly.

### 5.5 Secrets

- Code reads `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY` from the environment only. Keys are never logged, and HTTP logging redacts authorization headers.
- `scripts/scan.sh` sources `~/Repos/.env.secrets` and then runs `uv run jevtrends "$@"`. No code reads or prints the secrets file.
- **User action:** create a ScrapeCreators account and add `SCRAPECREATORS_API_KEY` to `~/Repos/.env.secrets`.
- Step 0 checks that both variables are set, by presence only. If the OpenRouter key is stored under a different variable name, the wrapper maps it.

## 6. Stage specifications

Settings are written in `code font` with their defaults (§9.1).

### 6.1 collect

- **Queries:** every niche's `seed_queries` plus `global_seed_queries` from `niches.yaml`, which is 65 queries at the defaults.
- **Search:** each query is a keyword search with region US and a date window equal to the lookback (`lookback_days: 30`), in the default sort order.
- **Pagination:** each query paginates until it reaches its cap, `ceil(max_videos / number_of_queries)`, or runs out of results.
- **Dedupe:** by video id. Every seed query that found a video is recorded.
- **Filtering:** videos posted outside the window are dropped, and so are videos the scraper marks as non-English (when it provides a language field).
- **Shortfall:** if fewer than `max_videos: 1000` are found, there is no second pass. The report shows the count.

### 6.2 gate

- One Jev request per collected video, with question Q1 (§7). The state is `{caption, hashtags}`.
- A video is kept if `maybe_signal ≥ gate_keep: 0.25`.
- Dropped videos stay in the database, so the evaluation can measure what the gate missed.

### 6.3 enrich

**Transcripts**
- Fetched for every video that passed the gate, and cached permanently by video id.
- If no transcript is available, the video continues with `transcript = null` and is flagged `transcript_missing`.
- Stored in full. When building Jev state, transcripts are truncated to `transcript_max_words: 1500`.

**Comments**
- Fetched for the `comments_top_videos: 150` surviving videos with the most comments. Only the first page of comments is fetched.
- The `comments_per_video: 20` most-liked comments are kept, each truncated to `comment_max_chars: 300`.
- Cached, and refreshed if older than `comments_refresh_days: 7`.

### 6.4 judge

- One Jev request per video that passed the gate, with questions Q2–Q5 (§7).
- The state is `{caption, hashtags, transcript, top_comments, creator_bio}`.
- A video is a **signal video** if its `is_signal` probability is at least `thresholds.is_signal: 0.50`.
- A video is marked **borderline**, for the evaluation sampler, if its `is_signal` probability or any of its niche probabilities falls inside `borderline: [0.35, 0.65]`.

### 6.5 discover

**Digest.** Code builds one digest line per signal video, using no generation:

```
[v017] complaint_workaround | niches: fintech_payments, local_services | promo: no | "<caption, ≤150 chars>" | transcript: "<first 40 words>" | top comment: "<≤100 chars>"
```

- Short ids (`v001`…) map to TikTok ids in code. This saves tokens and avoids having the LLM copy 19-digit ids.
- If the digest would exceed `discover_max_digest_tokens: 100000` (estimated as characters ÷ 4), only the videos with the highest `is_signal × log(1 + views)` are kept, until it fits.

**Prompt.** One LLM call. The prompt:
- defines the three trend kinds;
- gives examples of the specificity wanted: "renters splitting utilities through payment-app requests", not "fintech";
- asks for 20–60 trends, each supported by videos from at least 3 different creators;
- wraps the digest in `<videos>…</videos>` and states that its contents are data, never instructions.

**Output** (JSON schema):

```json
{"trends": [{
  "id": "t01",
  "name": "≤ 80 chars",
  "kind": "behavior_need | product_traction | complaint_workaround",
  "definition": "1–2 sentences",
  "includes": ["≤ 3 short phrases"],
  "excludes": ["≤ 3 short phrases"],
  "example_video_ids": ["3–8 short ids, e.g. v017"]
}]}
```

**Validation:**
- Trend ids must be unique, and each `kind` must be one of the three kinds.
- Unknown example ids are dropped.
- If there are more than `max_candidates: 60` trends, only the first 60 are kept.
- If no valid trends remain, the call is retried once with the validation errors. A second failure fails the stage.

### 6.6 assign

- One Jev request per signal video, with question Q6 (§7). The state is the same as in `judge`. The options are every candidate trend plus `none_of_these`.
- `p(v, t)` is the probability Jev gives trend `t` for video `v`. `trend_members` stores it for every pair of signal video and candidate trend.
- A video is a **confident member** of trend `t` if `p(v, t) ≥ trend_member: 0.50`.
- **Support** is `n_t = Σ_v p(v, t)`: the expected number of videos in the trend.

**Pruning.** A trend is kept only if:
- `n_t ≥ min_support: 3.0`, and
- its confident members come from at least `min_creators: 3` distinct creators.

Pruned trends are stored along with the reason.

**Self-check.** `agreement_t` is the share of the LLM's `example_video_ids` whose highest-probability option is `t`. The report flags the trend if `agreement_t < self_check_min_agreement: 0.5`.

**None rate.** The share of signal videos whose top option is `none_of_these`. The report warns if it exceeds `none_rate_warning: 0.30`.

### 6.7 score

**Computed in code for each kept trend**

- **Momentum.** Let `R` be the most recent third of the lookback window (`momentum_recent_fraction: 0.333`), ending at the scan's start time.
  - `c` is the share of all signal videos posted within `R`: the corpus baseline. If `c` is 0 or 1, momentum is undefined. Every trend then gets `momentum_norm = 0.5`, and the report notes this.
  - `r_t = Σ p(v, t)` over signal videos posted within `R`.
  - The shrunk ratio is `m_t = (r_t + k·c) / ((n_t + k)·c)`, with `k = momentum_pseudo_count: 2`. This adds `k` pseudo-videos at the baseline rate, so small trends are pulled toward a ratio of 1.0.
  - `momentum_norm = clip((log2(m_t) + 2) / 4, 0, 1)`. So a ratio of 0.25× maps to 0, 1× to 0.5, and 4× to 1.
  - Measuring against the corpus baseline cancels out the search API's bias toward recent videos.
- **Breadth.** `creators_t` is the number of distinct creators among confident members. `breadth_norm = min(1, ln(1 + creators_t) / ln(21))`, so 20 or more creators maps to 1.0.
- **Niche affinity.** `a_t(niche) = Σ_v p(v, t) · P_niche(v) / n_t`.
  - The trend belongs to every niche with `a_t ≥ niche_member: 0.50`, and its primary niche is the highest.
  - If no niche reaches 0.50, the trend goes in "Outside your niches".
- **Display only, not used for ranking:**
  - the median views of confident members;
  - the promotional share, `Σ_v p(v, t)·[is_promotional(v) ≥ 0.5] / n_t`.

**Scored by Jev.** One request per kept trend, with questions Q7–Q10 (§7). The state is:

```json
{"trend": {"name": "…", "kind": "…", "definition": "…"},
 "evidence": [{"caption": "…", "transcript_excerpt": "≤150 words", "top_comments": ["up to 3"]}]}
```

- `evidence` holds the trend's **evidence set**: the `evidence_per_trend: 12` signal videos with the highest `p(v, t)`.
- `pain_norm = pain / 3` and `spend_norm = spend / 3`.
- `underserved_norm = underserved / 3`, unless `mentions_solutions < 0.5`. In that case it is `0.5`, meaning unknown: the evidence says nothing about existing solutions.

**Opportunity score.**

```
opportunity = 0.30·momentum_norm + 0.20·pain_norm + 0.20·spend_norm + 0.20·underserved_norm + 0.10·breadth_norm
```

- The weights come from `ranking.weights` and must sum to 1.
- Every component is stored, so `jevtrends report <run> --weights …` can re-rank with no model calls. Re-ranking changes the order only; it never writes new briefs.

### 6.8 brief

**Selection.** Starting from kept trends ranked by opportunity:
1. For each niche, in config order, take that niche's highest-ranked trend that isn't already selected.
2. Fill with the highest-ranked remaining trends until there are `max_briefs: 20`.
3. If the budget guard needs to cut, it removes the lowest-opportunity selected trends first, down to a minimum of `min_briefs: 5`.

**Input.** One LLM call per selected trend (concurrency 5). Everything below is wrapped and marked as data:
- the trend's definition;
- its stats: support, creators, momentum ratio, median views, promotional share, niches;
- Jev's scores, with confidence;
- its evidence set (the same 12 videos Jev scored in §6.7): id, handle, caption, a transcript excerpt of up to 200 words, the top 3 comments, views, post date and promotional flag.

**Output** (JSON schema):

| Field | Content |
|---|---|
| `headline` | ≤ 100 chars |
| `whats_happening` | 2–4 sentences |
| `who` | 1–2 sentences |
| `underlying_need` | 1–2 sentences |
| `evidence` | 3–5 items, each `{video_id, why}` |
| `existing_solutions` | A list; may be empty |
| `startup_angles` | 2–3 items, each `{idea, why_now}` |
| `risks` | 1–3 items |

**Validation.** Cited video ids must belong to the trend's evidence set; any others are dropped. If no valid evidence remains, the call is retried once. A second failure leaves that trend without a brief, and the report notes it.

### 6.9 report

The report is written to `reports/<YYYY-MM-DD>-scan-<run_id>.md`, rendered from `templates/report.md.j2`. It has five sections:

1. **Header:**
   - date and lookback window;
   - funnel counts: collected → passed filter → signals → trends proposed → trends kept;
   - actual cost by provider;
   - any budget trims.
2. **Top opportunities:** one table across all niches, with columns rank, trend, niches, kind, momentum ratio, pain / spend / underserved, creators, promotional share, and opportunity.
3. **One section per niche**, in config order:
   - Each briefed trend shows its scores, its brief, and 3–5 evidence videos. Evidence cited by the brief comes first.
   - Each evidence video shows its link (`https://www.tiktok.com/@<handle>/video/<id>`), views, post date, `p(v, t)`, a transcript snippet and a top comment.
   - Unbriefed trends in the niche appear in a short table.
4. **Outside your niches**, in the same format.
5. **Diagnostics:**
   - the none rate and self-check flags;
   - the number of borderline videos;
   - momentum caveats;
   - missing transcripts and failed items;
   - a snapshot of the settings used.

## 7. Jev question catalog (all version 1)

In code, question ids are prefixed by stage (for example `judge.is_signal`). Changing any wording bumps that question's version, and the version is stored with every answer.

**Q1 `gate.maybe_signal`** (Noul)
- *Instructions:* "Might this video show or discuss a real-life behavior, need, product, app, service or frustration, rather than being pure entertainment?"
- *True:* "The caption or hashtags hint at a product, app, service, habit, routine, money, health, work, business or a problem someone has, even vaguely, or give too little information to tell."
- *False:* "Clearly entertainment only: a dance, lip-sync, skit, prank, meme, music, fandom or gossip, with no hint of a real-world need, product or problem."

**Q2 `judge.is_signal`** (Noul)
- *Instructions:* "Does this video give real evidence of what people do, want, buy or struggle with, something that could inform what a startup builds?"
- *True:* "Shows or describes a concrete behavior, habit, need, purchase, product experience, complaint or improvised workaround, first-hand or clearly observed in others, including in the comments."
- *False:* "Entertainment, generic motivation, news or opinion with no concrete behavior, need, product or frustration."

**Q3 `judge.signal_type`** (Choice)
- *Instructions:* "What kind of real-world signal does this video mainly provide?"

| Option | `what` | `not_for` | `examples` |
|---|---|---|---|
| `behavior_need` | People doing, wanting or trying to achieve something in everyday life, work, money or health: a habit, routine, hack, goal or desire. | Enthusiasm for one specific named product; frustration with existing options. | "My 5am routine for tracking my glucose"; "How we split rent and bills as three roommates" |
| `product_traction` | A specific named product, app, tool or service getting enthusiasm or adoption: recommendations, reviews, results, or people asking where to get it. | General habits not tied to a named product. | "This AI calorie app got me 20 lbs down"; comments full of "what's the name of this app?" |
| `complaint_workaround` | Frustration with an existing product, service, company or process, or an improvised fix because nothing good exists. | Mild preferences with no real problem. | "My bank's app is useless so I track everything in five spreadsheets"; "Why is there no way to book a plumber without ten phone calls?" |
| `other` | A real-world signal that fits none of the options above. | none | none |

**Q4 `judge.is_promotional`** (Noul)
- *Instructions:* "Was this video made mainly to sell something: an ad, a sponsorship, an affiliate or TikTok Shop pitch, or a creator or founder promoting their own product?"
- *True:* "Paid-partnership disclosure, discount codes, affiliate or shop links, 'link in bio' sales pitches, or the creator selling their own product."
- *False:* "Organic content; any products shown are not being sold by the creator."

**Q5 `judge.niche_<id>`** (Noul, one per niche)
- *Instructions* (an object):

```json
{"question": "Is this video relevant to the business niche described in `niche`?",
 "niche": {"name": "<name>", "covers": "<covers>", "not_for": "<not_for>"}}
```

**Q6 `assign.trend`** (Choice)
- *Instructions:* "Which of these trends does this video most clearly provide evidence for?"
- One option per candidate trend, keyed by trend id:
  - `what` = "<name>. <definition> Includes: <includes>."
  - `not_for` = "<excludes>"
- `none_of_these`: "The video does not clearly fit any of the trends listed."

**Q7 `trend.pain`** (Score)
- *Instructions:* "How strong is the frustration or unmet need that people express in the `evidence` about this `trend`?"
- *Levels*, from 0 to 3:
  0. No frustration or need: people are just sharing, showing off or enjoying something.
  1. A mild wish or curiosity; nice to have, with no real problem described.
  2. A clear, recurring problem that people actively try to solve.
  3. Intense pain: people describe wasted money or time, anger or desperation, and ask for a solution.

**Q8 `trend.spend`** (Score)
- *Instructions:* "How much evidence is there in the `evidence` that people spend money on this `trend`?"
- *Levels*, from 0 to 3:
  0. No spending mentioned; a free or do-it-yourself activity.
  1. Costs or prices are mentioned, but nobody describes buying anything.
  2. People describe buying related products or paying for services.
  3. People pay a lot, pay for several workarounds, or ask where to buy and how much it costs.

**Q9 `trend.underserved`** (Score)
- *Instructions:* "According to the `evidence`, how well do existing products serve the need behind this `trend`?"
- *Levels*, from 0 to 3:
  0. People are happy with a named existing product or service.
  1. Existing options are mentioned, with minor complaints.
  2. Existing options are described as inadequate, too expensive or annoying.
  3. People say nothing exists, or rely on manual workarounds or makeshift combinations of tools.

**Q10 `trend.mentions_solutions`** (Noul)
- *Instructions:* "Does the `evidence` mention existing products, services, apps or methods for the need behind this `trend`, or say that none exist?"

## 8. Data model (SQLite)

JSON-valued columns are stored as TEXT.

| Table | Key columns |
|---|---|
| `runs` | `id`, `started_at`, `finished_at`, `status` (`running`, `completed`, `failed_resumable`, `budget_exceeded`), `params`, `settings_snapshot`, `niches_snapshot`, `stage_status`, `cost_by_provider` |
| `videos` | `id` (TikTok id), `url`, `author_id`, `author_handle`, `author_bio`, `caption`, `hashtags`, `sound`, `posted_at`, `views`, `likes`, `comment_count`, `shares`, `language`, `raw` |
| `run_videos` | `run_id`, `video_id`, `seed_queries`, `short_id` (set by `discover`) |
| `enrichments` | `video_id`, `transcript`, `transcript_status` (`ok`, `missing`, `error`), `transcript_fetched_at`, `comments`, `comments_fetched_at` |
| `judgments` | `run_id`, `subject_type` (`video`, `trend`), `subject_id`, `question_id`, `question_version`, `value`, `probabilities`, `confidence`, `created_at`. Unique on (`run_id`, `subject_type`, `subject_id`, `question_id`, `question_version`). |
| `trends` | `run_id`, `trend_id`, `name`, `kind`, `definition`, `includes`, `excludes`, `example_video_ids`, `status` (`kept`, `pruned`), `prune_reason`, `self_check_agreement` |
| `trend_members` | `run_id`, `trend_id`, `video_id`, `probability` |
| `trend_scores` | `run_id`, `trend_id`, `support`, `creators`, `momentum_ratio`, `momentum_norm`, `breadth_norm`, `median_views`, `promo_share`, `niche_affinity`, `primary_niche`, `pain_norm`, `spend_norm`, `underserved_norm`, `opportunity`, `rank` |
| `briefs` | `run_id`, `trend_id`, `model`, `brief`, `status` (`ok`, `failed`), `created_at` |
| `api_calls` | `id`, `run_id`, `stage`, `provider` (`scrapecreators`, `jev`, `llm`), `endpoint`, `units`, `cost_usd`, `status`, `created_at` |
| `labels` | `video_id`, `field`, `value`, `stratum` (`random`, `borderline`, `gate_dropped`), `labeled_at` |

## 9. Configuration

### 9.1 `config/settings.yaml` defaults

```yaml
scan:
  lookback_days: 30
  max_videos: 1000
  region: US
thresholds:
  gate_keep: 0.25
  is_signal: 0.50
  niche_member: 0.50
  trend_member: 0.50
  borderline: [0.35, 0.65]
enrich:
  transcript_max_words: 1500
  comments_top_videos: 150
  comments_per_video: 20
  comment_max_chars: 300
  comments_refresh_days: 7
trends:
  discover_max_digest_tokens: 100000
  max_candidates: 60
  min_support: 3.0
  min_creators: 3
  none_rate_warning: 0.30
  self_check_min_agreement: 0.5
  momentum_recent_fraction: 0.333
  momentum_pseudo_count: 2
  evidence_per_trend: 12
ranking:
  weights: {momentum: 0.30, pain: 0.20, spend: 0.20, underserved: 0.20, breadth: 0.10}
briefs:
  max_briefs: 20
  min_briefs: 5
models:
  jev: typesafe/jev-1.13
  llm: anthropic/claude-opus-5
pricing:                         # for projections; actual spend comes from API usage
  jev_input_per_mtok: 0.042
  llm_input_per_mtok: 5.00
  llm_output_per_mtok: 25.00
  scrapecreators_per_credit: 0.00188
  discover_expected_output_tokens: 15000
  brief_expected_output_tokens: 3000
budget:
  max_usd_per_scan: 5.00
concurrency: {jev: 16, scraper: 5, llm: 5}
retries: {max_attempts: 4, base_delay_s: 1, max_delay_s: 30}
failure:
  max_item_failure_rate: 0.20
```

### 9.2 `config/niches.yaml`: initial niches

| id | Name | Covers | Not for | Seed queries |
|---|---|---|---|---|
| `creator_economy` | Creator economy | How people build audiences and earn from content: brand deals, UGC, affiliate and TikTok Shop selling, subscriptions, courses, fan monetization, and the tools creators use. | Ordinary social media use that isn't about creating or monetizing content. | ugc creator · brand deals · tiktok shop affiliate · creator tools · how i make money on tiktok |
| `consumer_apps` | Consumer apps | Mobile and web apps people use in everyday life: social, dating, productivity, habit tracking, lifestyle, entertainment and utilities. | Physical products; software used mainly by businesses. | app recommendation · apps you need · this app changed my life · best apps · is there an app for |
| `longevity_health` | Longevity & health | Physical and mental health, fitness, nutrition for health, sleep, biohacking, supplements, diagnostics and lab tests, healthcare access and costs, and aging. | Beauty or fashion with no health angle. | longevity routine · biohacking · blood test results · sleep tracking · health insurance |
| `ai` | AI | How people use AI tools, assistants, agents and AI-powered apps in life or work; new behaviors AI enables; frustrations with AI. | General tech news with no usage or behavior. | chatgpt hack · ai tool · ai agent · using ai to · ai app |
| `b2b_saas` | B2B SaaS | Software and workflows used by businesses, teams, freelancers and professionals: operations, CRM, invoicing, scheduling, hiring, internal tools and workplace productivity. | Apps for personal life. | small business tools · freelancer tools · crm · automate my business · software for my business |
| `local_services` | Offline & local services | In-person and local businesses and services: home services and trades, beauty and wellness appointments, restaurants and local shops, booking, and gig or service workers. | Businesses that operate purely online. | local business · small business owner day in the life · home services · cleaning business · booking appointments |
| `fintech_payments` | Fintech & payments | How people earn, save, spend, send, borrow, invest and insure money: budgeting, banking, payments, credit, buy now pay later, investing, side income and taxes. | Shopping content with no money-management angle. | budgeting app · credit card hack · side hustle income · buy now pay later · savings challenge |
| `education_careers` | Education & careers | Learning and upskilling, school and college, test prep, job search, career changes, workplace life and credentials. | Trivia or "fun facts" with no learning or career angle. | career change · job search · study hack · learn a new skill · corporate job |
| `ecommerce_resale` | E-commerce & resale | How people shop for, discover and resell products: marketplaces, dupes, thrifting and flipping, deals, returns and other shopping behaviors. | Budgeting or payments with no shopping angle. | thrift flip · reselling · amazon finds · dupe · tiktok made me buy it |
| `home_family_pets` | Home, family & pets | Household life: parenting and childcare, family logistics, pets, renting and housing, cleaning, home improvement and eldercare. | Running a home-services business. | mom hack · parenting tips · pet owner · renter hack · cleaning routine |
| `food_beverage` | Food & beverage | What and how people eat and drink: cooking, meal prep, diets, groceries, restaurants and delivery, drinks and food products. | Content where food only appears in the background. | meal prep · grocery haul · food delivery · healthy snacks · recipe hack |

**`global_seed_queries`** are cross-niche phrases chosen to surface complaints and workarounds:

> i wish there was an app · why is there no · does anyone else · stop paying for · life hack · game changer · i built an app · nobody talks about · how i track · rant

## 10. CLI

| Command | What it does |
|---|---|
| `jevtrends scan [--lookback-days N] [--max-videos N] [--budget USD] [--estimate]` | Runs a full scan. With `--estimate`, it prints the projected cost per stage and exits without spending. |
| `jevtrends resume <run_id> [--budget USD]` | Continues a failed or budget-stopped run, redoing only missing work. |
| `jevtrends report <run_id> [--weights momentum=0.3,pain=0.2,…]` | Re-ranks and re-renders a report with no model calls. |
| `jevtrends runs` | Lists runs with their status, counts and cost. |
| `jevtrends label <run_id> [--n 100]` | Starts an interactive labeling session for the evaluation set. |
| `jevtrends eval [<run_id>]` | Computes quality metrics from labels (§14.4). |

`scripts/scan.sh` wraps all of these and loads the secrets file first.

## 11. Cost model (per scan, at defaults)

| Item | Units | Estimated cost |
|---|---|---|
| Searches | 65–130 requests (1–2 pages per query) | $0.12–0.24 |
| Transcripts | ~600 requests | ~$1.13 |
| Comments | 150 requests | ~$0.28 |
| Jev (gate, judge, assign, trend scores) | ~2,050 requests, ~6M input tokens | ~$0.25 |
| LLM discover | ~65k tokens in, ~12k out | ~$0.63 |
| LLM briefs | 20 × (~5k in, ~2.3k out) | ~$1.65 |
| **Total** | | **≈ $4.1** |

The expected duration is about 10–15 minutes, with scraping the slowest part.

## 12. Error handling and budget guard

### 12.1 Budget guard

**Projection.** Before each stage, the guard projects the cost of that stage **plus every later stage**. It uses actual counts where they are known. Otherwise it assumes that 65% of judged videos become signals and that 40 trends are kept. The projection is computed per provider:

| Provider | Projected cost |
|---|---|
| Scraper | requests × `scrapecreators_per_credit` |
| Jev | (characters ÷ 4 × 1.2 safety margin) × `jev_input_per_mtok` |
| LLM | (input characters ÷ 4) × input price + expected output tokens × output price |

**Trimming.** If `spent + projection > max_usd_per_scan`, the guard trims in this order:
1. fewer comment fetches, if `enrich` has not run yet, down to 0;
2. fewer briefs, down to `min_briefs`.

If the scan would still exceed the budget, it stops before the stage with status `budget_exceeded`. Running `jevtrends resume <run> --budget <higher>` continues it. Every trim is listed in the report header.

**Actual spend** is recorded in `api_calls`:
- Jev and LLM: `usage` token counts × configured prices, or OpenRouter's reported cost when present.
- ScrapeCreators: 1 credit per request unless the response reports otherwise.

### 12.2 Failures

**Retry** on 408, 429, 500–504 and 529, and on timeouts and connection errors.
- Up to 4 attempts, with exponential backoff from 1 s to 30 s plus jitter.
- `Retry-After` is honored when present.

**Fail fast** on 400, 401, 403, 404 and 422. The scan stops with a clear message naming the provider, for example "OpenRouter rejected the API key (401)".

**Per item:**
- A missing transcript does not stop a video; it continues, flagged.
- A Jev or scraper item that still fails after retries is skipped and counted in the diagnostics.

**Per stage:** if more than `max_item_failure_rate: 0.20` of a stage's items fail, the stage fails and the run's status becomes `failed_resumable`.

**Resume:**
- Progress is stored per item, so `resume` redoes only missing items.
- Judgments are unique on (run, subject, question, version), so no call is paid for twice.

**LLM output** is validated against its schema and retried once, as described in §6.5 and §6.8.

## 13. Untrusted content

Transcripts and comments are written by strangers and could contain text aimed at a model:
- Both LLM prompts fence this text as data and say so explicitly.
- Every LLM output is schema-validated, and cited ids are checked against the input.
- Nothing in the pipeline acts on the content. The worst case is a mislabeled video or trend, and that would be visible in the report's evidence.

## 14. Testing and evaluation

### 14.1 Step 0: live contract check

This is the first implementation task. Its responses are saved as test fixtures, with secrets stripped.

1. **Jev on OpenRouter:** send one request containing a Noul, a Choice and a Score.
   - Confirm the endpoint, the request and response shapes, the `usage` fields and the error format.
   - Then try `typesafe-sdk` with the OpenRouter base URL. Use it if it works; otherwise use httpx.
2. **Opus 5 on OpenRouter:** send one small request with a JSON schema.
   - Confirm the slug, structured-output support, and the usage and cost fields.
   - If JSON-schema output is not supported, fall back to asking for JSON in the prompt, validating it with Pydantic, and retrying once.
3. **ScrapeCreators:** send one search, one transcript and one comments request.
   - Confirm the paths and the date-window, region and sort parameters.
   - Confirm page sizes and fields: author bio, language, stats and post time.
   - Confirm the transcript format and how often transcripts are available.
4. **Secrets:** check that both environment variables are present, without printing them.

The expected cost is under $0.10 plus about 10 free credits.

If Jev cannot be reached through OpenRouter in this form, stop and decide with the user how to proceed, for example by getting a TypeSafe API key.

### 14.2 Unit tests (offline, pytest)

- **Scoring functions:** support, pruning, self-check, breadth, niche affinity, composite score, brief selection.
- **Momentum**, including the edge cases where `c` is 0 or 1, and very small trends.
- **Budget:** projection and trimming.
- **Digest:** digest building and short-id mapping.
- **LLM output validation.**
- **Question catalog rendering:** versions and niche instructions.
- **Report rendering,** as a snapshot test.

### 14.3 Offline end-to-end test

- Fake `Source`, Jev and LLM clients, driven by fixtures, run the full pipeline on about 20 videos and produce a report.
- A second test interrupts a scan partway through `judge`, resumes it, and asserts that no call is repeated and that the results are identical.

### 14.4 Quality evaluation

**Labeling.** `jevtrends label <run>` samples 100 videos:
- 50 random judged videos;
- 30 borderline videos;
- 20 videos the gate dropped.

For each, it shows the caption, a transcript excerpt, the top comments and the TikTok link. The user labels `is_signal`, `signal_type`, `niches` (multi-select) and `is_promotional`. Gate-dropped videos get `is_signal` only.

**Metrics.** `jevtrends eval` reports:
- precision and recall for `is_signal` and for each niche at the current thresholds, computed on the random stratum so the estimates are unbiased;
- the gate's miss rate, on the gate-dropped stratum;
- `signal_type` accuracy;
- calibration: for each probability bucket (0–0.2, …, 0.8–1.0), the mean predicted probability versus the observed rate;
- suggested thresholds: for each question, the threshold with the highest recall that still meets the precision target, on the random stratum.

**Caveats:**
- 50 random labels give only a rough estimate (about ±13 percentage points). Labeling more videos tightens it.
- Trend-assignment accuracy is not measured in v1. The self-check and the none rate serve as proxies. If they look poor, the fallback is to split Q6 into one Choice per trend kind.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Jev's OpenRouter endpoint differs from the third-party description | Step 0 verifies it before anything else is built. |
| OpenRouter doesn't support Opus 5 structured output | Fall back to JSON requested in the prompt, validation, and one retry. |
| Low transcript coverage | The pipeline tolerates missing transcripts, and the diagnostics report coverage. |
| Search-result bias skews momentum | Momentum is measured against the corpus baseline, with shrinkage, and the report states the caveat. |
| Q6 accuracy drops with many options | The none rate and self-check flag it; if needed, split the question by trend kind. |
| The LLM misses trends | The none-rate warning surfaces it; a second discovery round is future work. |
| Costs vary (thinking tokens) | The budget guard reserves money for later stages, and actual spend is logged. |
| Thin coverage per niche at 1,000 videos | Raise `max_videos`; scraping costs about $1.60 per 1,000 videos. |
| Vendor changes, or TikTok terms-of-service risk | The vendor is isolated behind `Source`. |

## 16. Future work

- Scheduled scans, and tracking the same trend across scans.
- A second discovery round over the "none of these" videos.
- Clustering in front of `discover` for scans of 10,000+ videos.
- Trend-membership labels and trend-level metrics.
- A dashboard or Notion export.
- Vision or OCR for on-screen text.

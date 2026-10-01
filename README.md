# TikTok trend classifier (`jevtrends`)

`jevtrends` scans recent TikTok videos and turns them into ranked trends. Every trend links back to the videos it came from. There are two versions:

| | V1: startup opportunities | V2: UGC and ad trends |
|---|---|---|
| Command | `jevtrends scan` | `jevtrends ugc scan` |
| Finds | What people do, want, buy and struggle with | The formats, hooks, sounds, topics and needs that are working in one niche |
| Scope | 11 business niches at once, last 30 days, up to 1,000 videos | One niche per scan, last 14 days, up to 600 videos |
| Writes | Up to 20 opportunity briefs: who it affects, the need, startup angles, risks | Up to 11 creator briefs: concept, hooks, shot-by-shot beats, sound, dos and don'ts. Can be tailored to your product |
| Full scan in testing | $4.19, about 13 minutes | $3.15, about 11 minutes |

Each scan writes a Markdown report and keeps all its data in a local SQLite database. Every scan has a $5 budget cap.

## How it works

1. **Collect:** search TikTok through ScrapeCreators with each niche's queries, inside the lookback window. Fetch transcripts, and comments for the most-commented videos.
2. **Judge:** Jev is TypeSafe's decision model (`typesafe/jev-1.13` on OpenRouter). It answers yes/no, multiple-choice and score questions about every video with calibrated probabilities: whether it's on topic, and whether it's promotional.
3. **Propose, then assign:** Claude reads a digest of the relevant videos and proposes trends. Jev then tags every video against those trends.
4. **Score:** code works out momentum (growth inside the window) and breadth (how many creators). Jev scores each trend:
   - V1: how painful the need is, whether people spend money on it, and how underserved it is;
   - V2: how well it fits your product, how easy it is to film, and brand risk.
5. **Brief:** Claude writes briefs for the top trends, citing the videos they rely on.

The UGC version adds one step. Claude Haiku reads the on-screen text in each video's cover frame (or a slideshow's first slides), because hooks and formats often live in that text.

Models only make judgments and write text. Counting, dates and arithmetic stay in code.

## What you need

- **macOS or Linux** with [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 or later if you don't have it. The tool has been run on macOS.
- **An OpenRouter API key** ([openrouter.ai](https://openrouter.ai)) with credits. Every model call goes through it:
  - `typesafe/jev-1.13` (Jev) for both versions;
  - `anthropic/claude-opus-5` for V1;
  - `anthropic/claude-opus-5.5` and `anthropic/claude-haiku-4.5` for the UGC version.
- **A ScrapeCreators API key** ([scrapecreators.com](https://scrapecreators.com)) with credits.
  - A default V1 scan uses up to about 1,300 credits, and a UGC scan up to about 650.
  - New accounts get 100 free credits. At the time of writing, 25,000 credits cost $47.

## Setup

```bash
git clone https://github.com/derekyang7/jev-tiktok-trend-classifier.git
cd jev-tiktok-trend-classifier
uv sync
uv run pytest -q
```

The tests run offline against recorded API responses, so they need no keys and cost nothing.

### API keys

The CLI reads two environment variables, `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY`. You can provide them in either of two ways:

- **Export them yourself,** then run commands as `uv run jevtrends …`.
- **Keep them in a file outside the repo,** and run commands as `scripts/scan.sh …`. For example, create `~/.jevtrends.env`:

  ```
  OPENROUTER_API_KEY=your-openrouter-key
  SCRAPECREATORS_API_KEY=your-scrapecreators-key
  ```

  Then point the helper at it:

  ```bash
  export JEVTRENDS_SECRETS_FILE=~/.jevtrends.env
  ```

`scripts/scan.sh <command>` loads the keys from that file, then runs `uv run jevtrends <command>`. It never prints the keys. If `JEVTRENDS_SECRETS_FILE` isn't set, it looks for `~/Repos/.env.secrets`.

The examples below use `scripts/scan.sh`. If you exported the keys instead, type `uv run jevtrends` in its place. `uv run jevtrends --help` and `uv run jevtrends ugc --help` list every command and option.

## Check the cost first

`--estimate` prints a scan's projected cost and exits. It needs no keys and calls no APIs.

```bash
uv run jevtrends scan --estimate
uv run jevtrends ugc scan --niche consumer_apps --estimate
```

```text
Projected cost: $5.75 (scraper $2.41 · jev $0.47 · llm $2.87); cap $5.00
Budget guard would trim: 12 briefs written instead of 20
Projected cost: $4.68 (scraper $1.21 · jev $0.30 · vision $0.96 · llm $2.21); cap $5.00
```

When a projection is over the cap, the budget guard cuts lower-priority work, in this order:
1. fewer briefs;
2. fewer comments;
3. in the UGC version, fewer slides read per slideshow.

If the scan still can't fit, it stops and tells you how to resume. Dollar amounts include ScrapeCreators credits, priced from the `pricing:` section of each settings file.

## V1: startup opportunities

V1 scans 11 niches at once:
- creator economy;
- consumer apps;
- longevity and health;
- AI;
- B2B SaaS;
- offline and local services;
- fintech and payments;
- education and careers;
- e-commerce and resale;
- home, family and pets;
- food and beverage.

Each niche in `config/niches.yaml` says what it covers, what it doesn't, and which TikTok searches to run. Edit them to match what you care about.

Run a small pilot first, then the full scan:

```bash
scripts/scan.sh scan --max-videos 100 --budget 2
scripts/scan.sh scan
```

In testing:
- **Pilot:** $0.67, about 5 minutes.
- **Full scan** (1,000 videos from the last 30 days): $4.19, about 13 minutes.

Each run prints the path of its report, `reports/<date>-scan-<run>.md`. The report has:
- **a header:** the funnel (collected → passed the filter → signals → trends), the cost and any notes;
- **the top opportunities,** ranked;
- **a section for each niche,** plus "Outside your niches". Each briefed trend there has:
  - a headline;
  - what's happening and who it affects;
  - the underlying need and existing solutions;
  - startup angles and risks;
  - evidence videos with a snippet and a top comment;
- **diagnostics.**

| Command | What it does |
|---|---|
| `scripts/scan.sh scan [--lookback-days N] [--max-videos N] [--budget USD]` | Run a scan. Defaults come from `config/settings.yaml` |
| `scripts/scan.sh runs` | List runs with their status and cost |
| `scripts/scan.sh resume <run> [--budget USD]` | Continue a failed or budget-stopped run, redoing only missing work |
| `scripts/scan.sh report <run> [--weights momentum=0.3,pain=0.2,spend=0.2,underserved=0.2,breadth=0.1]` | Re-rank and re-render a report without calling any model. The five weights must sum to 1 |
| `scripts/scan.sh label <run>` | Label a sample of 100 videos in your terminal (interactive) |
| `scripts/scan.sh eval <run>` | Precision, recall, calibration and a suggested threshold, from your labels |

## V2: UGC and ad trends

The UGC version looks at one niche per scan and finds five kinds of trend:

- **Formats:** how videos are made, such as a talking-head ranking countdown.
- **Hooks:** opening lines and on-screen text templates, such as "Ranking the ___ hotels I've stayed at".
- **Sounds:** the music and audio that creators in the niche use.
- **Topics and memes:** what the niche is talking about.
- **Needs and angles:** the wants and frustrations a product can speak to.

### 1. Pick a niche

`config/ugc/niches/` comes with two niches, `consumer_apps` and `hotels_travel`. To add your own, have Claude draft one, then edit it:

```bash
scripts/scan.sh ugc niche-draft pet_products "Products and services for dog and cat owners"
```

This writes `config/ugc/niches/pet_products.yaml` with:
- what the niche covers and what it doesn't;
- the audience;
- 12 to 20 search queries.

It makes one Claude call and prints what it cost.

### 2. Describe your product (optional)

With a product profile, the scan scores how well each trend fits your product, and briefs only make the claims you allow. Start from the example:

```bash
cp config/ugc/products/example.yaml config/ugc/products/myapp.yaml
```

Set `id: myapp`; it must match the file name. Then fill in:
- the name, what the product does and its audience;
- key benefits;
- claims creators may make (`claims_allowed`);
- claims to avoid;
- the tone.

Every profile except `example.yaml` is git-ignored, so your product details stay on your machine. Without a profile, briefs are written for a generic brand in the niche.

### 3. Run a pilot, then a full scan

```bash
scripts/scan.sh ugc scan --niche consumer_apps --product myapp --max-videos 100 --budget 2
scripts/scan.sh ugc scan --niche consumer_apps --product myapp
```

In testing:
- **Pilot:** $1.05, about 4 minutes.
- **Full scan** (529 videos from the last 14 days): $3.15, about 11 minutes.

The report goes to `reports/ugc/<date>-<niche>-run-<run>.md`. It has:
- **a header:** the funnel, the cost and any notes;
- **the top 15 picks** across all five kinds;
- **a section for each kind of trend:**
  - Each briefed trend shows its stats (momentum, reach, engagement, creators, fit, ease and ad share), its definition and the brief.
  - It also shows 3 to 5 evidence videos, each with views, saves, shares, on-screen text, a transcript snippet and a top comment.
- **a sounds table** with each sound's business-use label;
- **diagnostics.**

A brief contains:
- a concept;
- hooks;
- timed beats with on-screen text;
- a sound suggestion;
- dos and don'ts;
- a call to action;
- the product claims it uses;
- risks;
- a reminder to disclose paid partnerships.

| Command | What it does |
|---|---|
| `scripts/scan.sh ugc scan --niche ID [--product ID] [--lookback-days N] [--max-videos N] [--budget USD] [--no-vision]` | Run a scan. `--no-vision` skips reading cover frames |
| `scripts/scan.sh ugc runs` | List runs with their niche, product, status and cost |
| `scripts/scan.sh ugc resume <run> [--budget USD]` | Continue a failed or budget-stopped run, redoing only missing work |
| `scripts/scan.sh ugc report <run> [--weights momentum=0.25,performance=0.25,fit=0.3,breadth=0.1,ease=0.1]` | Re-rank and re-render a report without calling any model. The five weights must sum to 1 |
| `scripts/scan.sh ugc niche-draft ID "description"` | Draft a niche file for you to edit |
| `scripts/scan.sh ugc review <run> [--trends 20]` | Review the top trends and a sample of their tagged videos (interactive) |
| `scripts/scan.sh ugc eval <run>` | From your review: how many trends you'd brief, tagging precision for each kind of trend, and a suggested threshold |

### Things to know

- **Sound licensing:** TikTok's popular-songs list carries the business-use flags. When this version was built (September 2026), the list was unavailable through ScrapeCreators. While it's down:
  - sounds come only from the scanned videos;
  - their business use shows as "unknown";
  - briefs suggest original audio or a track from TikTok's Commercial Music Library.

  Check a sound's licence before you use it in an ad.
- **Hashtags:** hashtag search returns all-time top posts, so almost none fall inside a 14-day window. The bundled niches leave `hashtags` empty.
- **Briefs are starting points:** check every claim, and keep the disclosure line.

## Configuration and data

| Path | What it holds |
|---|---|
| `config/settings.yaml` | V1 settings: window, video count, thresholds, ranking weights, briefs, models, pricing and budget |
| `config/niches.yaml` | V1 niches |
| `config/ugc/settings.yaml` | UGC settings: the same kinds of options, plus vision, sounds and brief quotas |
| `config/ugc/niches/*.yaml` | UGC niches, one per file |
| `config/ugc/products/*.yaml` | UGC product profiles, git-ignored except `example.yaml` |
| `data/jevtrends.db`, `data/ugc.db` | SQLite databases: every video, judgment, trend and API call (git-ignored) |
| `reports/`, `reports/ugc/` | Markdown reports (git-ignored) |

Each run stores the settings it used, so editing a setting only affects later runs. To keep files somewhere else, set these environment variables:
- V1: `JEVTRENDS_CONFIG_DIR`, `JEVTRENDS_DB` and `JEVTRENDS_REPORTS_DIR`;
- UGC: `JEVTRENDS_UGC_CONFIG_DIR`, `JEVTRENDS_UGC_DB` and `JEVTRENDS_UGC_REPORTS_DIR`.

## Development

- `uv run pytest -q` runs the offline test suite.
- Each version has a script that checks the live APIs it depends on, then saves redacted responses as test fixtures:
  - V1: `scripts/with-secrets.sh uv run python scripts/contract_check.py`, under $0.10;
  - UGC: `scripts/with-secrets.sh uv run python scripts/ugc_contract_check.py`, about $0.50.
- Design specs, implementation plans and notes from real runs are in `docs/superpowers/`.

```text
src/jevtrends/        V1 pipeline, shared API clients (Jev, Claude, ScrapeCreators) and the CLI
src/jevtrends/ugc/    the UGC version
config/               settings, niches and product profiles
scripts/              key-loading helpers and live API checks
tests/                offline tests and recorded API responses
docs/superpowers/     specs, plans and run notes
```

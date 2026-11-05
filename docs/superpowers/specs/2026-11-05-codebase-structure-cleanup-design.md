# Codebase Structure Cleanup (`core`, `opportunities`, `ugc`): Design

| | |
|---|---|
| **Date** | 2026-11-05 |
| **Status** | Draft, awaiting user review |
| **Repo** | `jev-tiktok-trend-classifier` |
| **Packages / CLI** | `jevtrends.core`, `jevtrends.opportunities`, `jevtrends.ugc` / `jevtrends {opportunities,ugc}` |
| **Builds on** | [V1 design](2026-09-28-tiktok-trend-classifier-design.md), [UGC design](2026-09-30-ugc-trend-finder-design.md) |

## 1. Purpose

Reorganize the repository so that shared infrastructure lives in an explicit `core` layer (`src/jevtrends/core/`) and the two pipelines — startup opportunities (`opportunities`, formerly V1 at the package root) and UGC/ad trends (`ugc`, formerly V2) — are symmetric peers across `src/jevtrends/`, `config/`, `data/`, `reports/`, `scripts/`, `tests/`, and the CLI.

No model prompts, Jev questions, scoring formulas, or SQLite table schemas change. Existing SQLite databases and reports are migrated in place.

## 2. Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Primary goal | Separate shared core from two peer pipelines across `src/`, `config/`, and `tests/`. |
| V1 pipeline name | `opportunities` (matching the README's "startup opportunities" terminology). |
| Package layout | Option 1: explicit `src/jevtrends/core/` package plus peer `src/jevtrends/opportunities/` and `src/jevtrends/ugc/` packages, with a thin root `src/jevtrends/cli.py`. |
| Dependency rule | `opportunities` and `ugc` import only from `jevtrends.core` and their own package, never from each other. `jevtrends.core` imports from neither pipeline. |
| CLI structure | Symmetric sub-apps: `jevtrends opportunities <cmd>` and `jevtrends ugc <cmd>`. |
| Non-code directories | Symmetric layout across `config/`, `data/`, `reports/`, and `scripts/`, migrating existing local files in place (`data/jevtrends.db` → `data/opportunities.db`, `reports/*.md` → `reports/opportunities/*.md`, `scripts/contract_check.py` → `scripts/opportunities_contract_check.py`). |
| Test suite layout | Mirror `src/jevtrends/` with `tests/core/`, `tests/opportunities/`, `tests/ugc/`, and `tests/fixtures/contract/{opportunities,ugc}/`. |

## 3. Package architecture (`src/jevtrends/`)

```text
src/jevtrends/
├── __init__.py
├── cli.py                        # Root Typer app; mounts `opportunities` and `ugc` sub-apps
├── core/
│   ├── __init__.py
│   ├── budget.py                 # BudgetGuard, Trimmable, TrimResult, trim_to_fit, SEARCH_PAGES_PER_QUERY
│   ├── config.py                 # PricingCfg, BudgetCfg, ConcurrencyCfg, RetriesCfg, FailureCfg, LlmCfg,
│   │                             # KEYS, require_keys
│   ├── context.py                # ContextHelpers, JevLike, LLMLike, StageFailed, BudgetExceeded,
│   │                             # run_items, run_stages, is_english_or_unknown, gate_state,
│   │                             # truncate_words, clip
│   ├── http.py                   # APIError, TransientAPIError, FatalAPIError, send_with_retry
│   ├── jev.py                    # JEV_URL, JevClient, JevResult, parse_answer, Question, payload,
│   │                             # NONE_OF_THESE, IS_PROMOTIONAL
│   ├── llm.py                    # LLMClient, LLMResult, LLMOutputError, ImagePart, content_chars,
│   │                             # strict_schema, EvidenceRef
│   ├── models.py                 # Video, Comment, Enrichment, VisionRead, SoundInfo, Answer
│   ├── scoring.py                # support, confident, prune_reason, top_choices, self_check,
│   │                             # none_rate, recent_start, corpus_recent_share, momentum,
│   │                             # breadth_norm, promo_share, median_views, EVIDENCE_MIN_P, evidence_set
│   ├── store.py                  # CORE_SCHEMA, Store, _now
│   └── sources/
│       ├── __init__.py
│       ├── base.py               # Source, UgcSource, SearchPage, CommentsResult, TranscriptResult,
│       │                         # Song, SongsPage
│       └── scrapecreators.py     # ScrapeCreatorsSource and parsing helpers
├── opportunities/
│   ├── __init__.py
│   ├── budget.py                 # STAGE_ORDER, CHARS, GATE_PASS_RATE, SIGNAL_RATE, EXPECTED_TRENDS,
│   │                             # RemainingWork, Projection, Decision, remaining_work,
│   │                             # project_opportunities, decide_opportunities
│   ├── cli.py                    # `opportunities_app` (scan, resume, report, runs, label, eval)
│   ├── config.py                 # WEIGHT_KEYS, ScanCfg, ThresholdsCfg, EnrichCfg, TrendsCfg,
│   │                             # RankingCfg, BriefsCfg, ModelsCfg, Settings, Niche, NicheConfig,
│   │                             # load_settings, load_niches, parse_weights
│   ├── context.py                # RunContext(ContextHelpers), report_context
│   ├── evaluation.py             # sample_for_labeling, compute_metrics
│   ├── models.py                 # TrendKind, Trend, TrendScore
│   ├── pipeline.py               # STAGES, known_counts, check_budget, run_pipeline, estimate_scan
│   ├── prompts.py                # TrendProposal, DiscoverOut, StartupAngle, BriefOut,
│   │                             # trend_count_range, discover_system, DISCOVER_SYSTEM,
│   │                             # discover_user_prompt, BRIEF_SYSTEM, brief_user_prompt
│   ├── questions.py              # MAYBE_SIGNAL, IS_SIGNAL, SIGNAL_TYPE, PAIN, SPEND, UNDERSERVED,
│   │                             # MENTIONS_SOLUTIONS, TREND_QUESTIONS, niche_question,
│   │                             # judge_questions, assign_question
│   ├── scoring.py                # niche_affinity, assigned_niches, normalized_jev_scores,
│   │                             # opportunity, rank_scores, select_for_briefs
│   ├── store.py                  # OPPORTUNITIES_SCHEMA, OpportunitiesStore(Store)
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── assign.py
│   │   ├── brief.py
│   │   ├── collect.py
│   │   ├── discover.py
│   │   ├── enrich.py
│   │   ├── gate.py
│   │   ├── judge.py
│   │   ├── report.py
│   │   └── score.py
│   └── templates/
│       └── report.md.j2
└── ugc/
    ├── __init__.py
    ├── budget.py
    ├── cli.py                    # `ugc_app` (scan, resume, report, runs, niche-draft, review, eval)
    ├── config.py
    ├── context.py
    ├── images.py
    ├── models.py
    ├── niche_draft.py
    ├── pipeline.py
    ├── prompts.py
    ├── questions.py
    ├── review.py
    ├── scoring.py
    ├── store.py                  # UGC_SCHEMA, UgcStore(Store)
    ├── stages/
    │   ├── __init__.py
    │   ├── assign.py
    │   ├── brief.py
    │   ├── collect.py
    │   ├── discover.py
    │   ├── enrich.py
    │   ├── gate.py
    │   ├── judge.py
    │   ├── look.py
    │   ├── report.py
    │   ├── score.py
    │   └── sounds.py
    └── templates/
        └── report.md.j2
```

## 4. Core vs. pipeline responsibility split

### 4.1 Persistence (`core/store.py`, `opportunities/store.py`, `ugc/store.py`)

- `jevtrends.core.store`:
  - Defines `CORE_SCHEMA` containing only the tables shared by every pipeline: `runs`, `videos`, `run_videos`, `enrichments`, `judgments`, and `api_calls`.
  - Defines `Store` with connection lifecycle (`__init__`, `schema()`, `close`, `_write`), run metadata (`create_run`, `_run_row`, `run_basics`, `list_runs`, `set_run_status`, `mark_stage_done`, `stage_done`, `add_note`, `notes`, `mark_query_done`, `done_queries`, `query_counts`), video storage (`upsert_video`, `get_video`, `get_videos`, `add_run_video`, `run_video_ids`, `set_short_id`, `short_ids`), enrichment storage (`upsert_enrichment`, `get_enrichment`), judgment storage (`upsert_judgment`, `get_answers`), and API call/spend tracking (`record_api_call`, `spend_by_provider`, `total_spend`, `failures_by_stage`).
- `jevtrends.opportunities.store`:
  - Defines `OPPORTUNITIES_SCHEMA` with `trends`, `trend_members`, `trend_scores`, `briefs`, and `labels`.
  - Defines `OpportunitiesStore(Store)` whose `schema()` returns `CORE_SCHEMA + OPPORTUNITIES_SCHEMA`, implements `get_run(run_id)` returning parsed `Settings` and `NicheConfig`, and provides the opportunities-specific methods (`upsert_trend`, `list_trends`, `replace_trend_members`, `trend_members`, `upsert_trend_score`, `list_trend_scores`, `upsert_brief`, `list_briefs`, `add_label`, `list_labels`).
- `jevtrends.ugc.store`:
  - Defines `UgcStore(Store)` whose `schema()` returns `CORE_SCHEMA + UGC_SCHEMA`. Existing databases (`data/opportunities.db` and `data/ugc.db`) remain 100% compatible because all statements use `CREATE TABLE IF NOT EXISTS`.

### 4.2 Budget (`core/budget.py`, `opportunities/budget.py`, `ugc/budget.py`)

- `jevtrends.core.budget` provides `SEARCH_PAGES_PER_QUERY`, `Trimmable`, `TrimResult`, `trim_to_fit`, and `BudgetGuard` (`scraper_cost`, `jev_cost`, `llm_cost`).
- `jevtrends.opportunities.budget` provides `STAGE_ORDER`, `CHARS`, `GATE_PASS_RATE`, `SIGNAL_RATE`, `EXPECTED_TRENDS`, `RemainingWork`, `Projection`, `Decision`, `remaining_work`, `project_opportunities(guard, work)`, and `decide_opportunities(guard, spent, work, min_briefs)` — matching the structure of `jevtrends.ugc.budget` (`project_ugc`, `decide_ugc`).

### 4.3 Stage execution & shared stage helpers (`core/context.py`)

- `jevtrends.core.context` holds:
  - Protocols and exceptions: `JevLike`, `LLMLike`, `StageFailed`, `BudgetExceeded`.
  - Base context mixin: `ContextHelpers`.
  - Execution loops: `run_items` and `run_stages`.
  - Shared stage helpers used by both pipelines: `is_english_or_unknown`, `gate_state`, `truncate_words`, and `clip`.
- `jevtrends.opportunities.context` holds `RunContext(ContextHelpers)` and `report_context(store, run_id)` (mirroring `UgcRunContext` and `ugc_report_context` in `jevtrends.ugc.context`).

### 4.4 Jev & LLM clients (`core/jev.py`, `core/llm.py`)

- `jevtrends.core.jev` consolidates `src/jevtrends/jev/client.py` plus the shared question primitives (`Question`, `payload`, `NONE_OF_THESE`, `IS_PROMOTIONAL`). Pipeline-specific questions move to `jevtrends.opportunities.questions` and `jevtrends.ugc.questions`.
- `jevtrends.core.llm` consolidates `src/jevtrends/llm/client.py` plus the shared `EvidenceRef` schema model. Opportunities-specific prompts and output models move to `jevtrends.opportunities.prompts`.

### 4.5 Scoring (`core/scoring.py`, `opportunities/scoring.py`, `ugc/scoring.py`)

- `jevtrends.core.scoring` holds pure functions shared across pipelines: `support`, `confident`, `prune_reason`, `top_choices`, `self_check`, `none_rate`, `recent_start`, `corpus_recent_share`, `momentum`, `breadth_norm`, `promo_share`, `median_views`, `EVIDENCE_MIN_P`, and `evidence_set`.
- `jevtrends.opportunities.scoring` holds opportunities-specific math: `niche_affinity`, `assigned_niches`, `normalized_jev_scores`, `opportunity`, `rank_scores`, and `select_for_briefs`.

## 5. CLI & environment variables

### 5.1 Commands

`src/jevtrends/cli.py` defines the root Typer app (`app = typer.Typer(no_args_is_help=True, ...)`) and mounts both pipeline sub-apps:

```python
app.add_typer(opportunities_app, name="opportunities")
app.add_typer(ugc_app, name="ugc")
```

| Pipeline | Commands |
|---|---|
| Opportunities | `jevtrends opportunities scan`, `jevtrends opportunities resume`, `jevtrends opportunities report`, `jevtrends opportunities runs`, `jevtrends opportunities label`, `jevtrends opportunities eval` |
| UGC | `jevtrends ugc scan`, `jevtrends ugc resume`, `jevtrends ugc report`, `jevtrends ugc runs`, `jevtrends ugc niche-draft`, `jevtrends ugc review`, `jevtrends ugc eval` |

`require_keys()` lives in `jevtrends.core.config` and is imported directly by both `jevtrends.opportunities.cli` and `jevtrends.ugc.cli`, eliminating the circular lazy import between `cli.py` and `ugc/cli.py`.

### 5.2 Paths and environment variables

| Setting | Opportunities env var | Opportunities default | UGC env var | UGC default |
|---|---|---|---|---|
| Config directory | `JEVTRENDS_OPPORTUNITIES_CONFIG_DIR` | `config/opportunities` | `JEVTRENDS_UGC_CONFIG_DIR` | `config/ugc` |
| SQLite database | `JEVTRENDS_OPPORTUNITIES_DB` | `data/opportunities.db` | `JEVTRENDS_UGC_DB` | `data/ugc.db` |
| Reports directory | `JEVTRENDS_OPPORTUNITIES_REPORTS_DIR` | `reports/opportunities` | `JEVTRENDS_UGC_REPORTS_DIR` | `reports/ugc` |

## 6. Repository layout outside `src/`

```text
config/
├── opportunities/
│   ├── niches.yaml                           # moved from config/niches.yaml
│   └── settings.yaml                         # moved from config/settings.yaml
└── ugc/
    ├── niches/
    │   ├── consumer_apps.yaml
    │   └── hotels_travel.yaml
    ├── products/
    │   └── example.yaml
    └── settings.yaml

data/                                         # git-ignored
├── opportunities.db                          # migrated from data/jevtrends.db
└── ugc.db

reports/                                      # git-ignored
├── opportunities/                            # migrated from reports/*.md
│   ├── 2026-09-29-scan-1.md
│   └── 2026-09-29-scan-2.md
└── ugc/
    ├── 2026-10-01-hotels_travel-run-1.md
    └── 2026-10-01-hotels_travel-run-2.md

scripts/
├── opportunities_contract_check.py           # renamed from scripts/contract_check.py
├── ugc_contract_check.py
├── scan.sh
└── with-secrets.sh

tests/
├── __init__.py
├── helpers.py
├── fixtures/
│   └── contract/
│       ├── opportunities/                    # moved from tests/fixtures/contract/*.json
│       │   ├── jev_systemone.json
│       │   ├── llm_chat.json
│       │   ├── sc_comments.json
│       │   ├── sc_search.json
│       │   └── sc_transcript.json
│       └── ugc/
│           ├── jev_ugc.json
│           ├── llm_opus.json
│           ├── llm_vision.json
│           ├── sc_hashtag.json
│           ├── sc_song_videos.json
│           └── sc_top.json
├── core/
│   ├── __init__.py
│   ├── test_budget.py                        # Trimmable, trim_to_fit, BudgetGuard unit cost methods
│   ├── test_context.py                       # ContextHelpers, run_items, run_stages, shared stage helpers
│   ├── test_contract_fixtures.py             # Offline contract tests for both fixture sets
│   ├── test_http.py
│   ├── test_jev.py                           # JevClient, parse_answer, Question, payload
│   ├── test_llm.py                           # LLMClient, strict_schema
│   ├── test_llm_images.py
│   ├── test_scoring.py                       # Shared scoring functions in core/scoring.py
│   ├── test_scrapecreators.py
│   ├── test_scrapecreators_ugc.py
│   ├── test_store.py                         # Base Store (runs, videos, enrichments, judgments, spend)
│   └── test_video_fields.py                  # renamed from test_ugc_video_fields.py
├── opportunities/
│   ├── __init__.py
│   ├── fakes.py                              # moved from tests/fakes.py
│   ├── test_budget.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_evaluation.py
│   ├── test_pipeline_offline.py              # moved from tests/e2e/test_pipeline_offline.py
│   ├── test_prompts.py                       # prompt formatting & schema tests from test_llm.py
│   ├── test_questions.py                     # opportunities questions tests from test_jev.py
│   ├── test_report.py
│   ├── test_scoring.py
│   ├── test_stages_collect_gate_enrich.py
│   ├── test_stages_judge_discover_assign.py
│   ├── test_stages_score_brief.py
│   └── test_store.py
└── ugc/
    ├── __init__.py
    ├── fakes.py
    ├── test_budget.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_look.py
    ├── test_pipeline_offline.py
    ├── test_prompts.py
    ├── test_questions.py
    ├── test_report.py
    ├── test_review.py
    ├── test_scoring.py
    ├── test_stage_brief.py
    ├── test_stage_score.py
    ├── test_stages_collect_gate_enrich.py
    ├── test_stages_discover_assign.py
    ├── test_stages_judge_sounds.py
    └── test_store.py
```

Untracked scratch artifacts in `.superpowers/` will also be left ignored or cleaned up without affecting tracked files.

## 7. Verification criteria

1. **Test suite:** `uv run pytest -q` passes with all existing and split unit/e2e tests green.
2. **Import boundaries:**
   - Zero imports of `jevtrends.opportunities` inside `src/jevtrends/core/` or `src/jevtrends/ugc/`.
   - Zero imports of `jevtrends.ugc` inside `src/jevtrends/core/` or `src/jevtrends/opportunities/`.
3. **CLI smoke checks:**
   - `uv run jevtrends opportunities scan --estimate` succeeds using `config/opportunities/`.
   - `uv run jevtrends ugc scan --niche consumer_apps --estimate` succeeds using `config/ugc/`.
   - `uv run jevtrends opportunities runs` reads the migrated `data/opportunities.db` and lists existing runs.
   - `uv run jevtrends ugc runs` reads `data/ugc.db` and lists existing runs.
4. **Documentation:** `README.md` reflects the updated `jevtrends opportunities` commands, environment variables, config paths, report paths, and directory overview.

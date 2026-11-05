# Codebase Structure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `jevtrends` into a shared `jevtrends.core` package and two symmetric peer pipeline packages (`jevtrends.opportunities` and `jevtrends.ugc`) across `src/`, `config/`, `data/`, `reports/`, `scripts/`, `tests/`, and the CLI.

**Architecture:** Extract all shared HTTP/Jev/LLM/ScrapeCreators clients, base `Store` (`CORE_SCHEMA`), `BudgetGuard`, shared models, shared scoring math, and stage runner helpers into `src/jevtrends/core/`. Move V1 (startup opportunities) into `src/jevtrends/opportunities/` with `OpportunitiesStore(Store)` and `opportunities_app`, matching `src/jevtrends/ugc/` 1-to-1. Mount both pipelines symmetrically under the root `jevtrends` CLI (`jevtrends opportunities ...` and `jevtrends ugc ...`) and mirror the three-way split (`core/`, `opportunities/`, `ugc/`) in `tests/`.

**Tech Stack:** Python 3.12, uv, httpx, Pydantic v2, PyYAML, Typer, Jinja2, sqlite3, Pillow, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-05-codebase-structure-cleanup-design.md`

## Global Constraints

- Python `>=3.12`, managed with `uv`. Run tests with `uv run pytest -q`.
- Strict import boundary:
  - `src/jevtrends/core/` must never import from `jevtrends.opportunities` or `jevtrends.ugc`.
  - `src/jevtrends/opportunities/` must never import from `jevtrends.ugc`.
  - `src/jevtrends/ugc/` must never import from `jevtrends.opportunities`.
- No model prompts, Jev question wording/versions, scoring formulas, or SQLite table definitions change.
- Existing local SQLite databases (`data/jevtrends.db` → `data/opportunities.db`, `data/ugc.db`) and Markdown reports (`reports/*.md` → `reports/opportunities/*.md`) are migrated in place without data loss.
- Tests never touch the network.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/jevtrends/core/__init__.py` | Package marker for shared core | Task 1 |
| `src/jevtrends/core/models.py` | Shared domain models (`SoundInfo`, `Video`, `Comment`, `VisionRead`, `Enrichment`, `Answer`) | Task 1 |
| `src/jevtrends/core/config.py` | Shared config models (`PricingCfg`, `BudgetCfg`, `ConcurrencyCfg`, `RetriesCfg`, `FailureCfg`, `LlmCfg`) + `KEYS`, `require_keys()` | Task 1 |
| `src/jevtrends/core/http.py` | HTTP retry policy (`APIError`, `FatalAPIError`, `TransientAPIError`, `send_with_retry`) | Task 1 |
| `src/jevtrends/core/jev.py` | `JevClient`, `JevResult`, `parse_answer`, `Question`, `payload`, `NONE_OF_THESE`, `IS_PROMOTIONAL` | Task 1 |
| `src/jevtrends/core/llm.py` | `LLMClient`, `LLMResult`, `LLMOutputError`, `ImagePart`, `content_chars`, `strict_schema`, `EvidenceRef` | Task 1 |
| `src/jevtrends/core/budget.py` | `SEARCH_PAGES_PER_QUERY`, `Trimmable`, `TrimResult`, `trim_to_fit`, `BudgetGuard` | Task 1 |
| `src/jevtrends/core/scoring.py` | Shared math (`support`, `confident`, `prune_reason`, `top_choices`, `self_check`, `none_rate`, `recent_start`, `corpus_recent_share`, `momentum`, `breadth_norm`, `promo_share`, `median_views`, `EVIDENCE_MIN_P`, `evidence_set`) | Task 1 |
| `src/jevtrends/core/store.py` | `CORE_SCHEMA`, `Store` (runs, videos, run_videos, enrichments, judgments, api_calls), `_now` | Task 1 |
| `src/jevtrends/core/context.py` | `JevLike`, `LLMLike`, `StageFailed`, `BudgetExceeded`, `ContextHelpers`, `run_items`, `run_stages`, `is_english_or_unknown`, `gate_state`, `truncate_words`, `clip` | Task 1 |
| `src/jevtrends/core/sources/{__init__,base,scrapecreators}.py` | Source protocols (`Source`, `UgcSource`) and `ScrapeCreatorsSource` | Task 1 |
| `tests/helpers.py` | Shared test builders & fakes (`make_video`, `FakeSource`, `FakeJev`, `FakeLLM`) | Task 1 |
| `tests/fixtures/contract/opportunities/*.json` | Recorded contract fixtures for opportunities | Task 1 |
| `tests/core/test_*.py` | Unit tests for all `jevtrends.core` modules and contract fixtures | Task 1 |
| `src/jevtrends/ugc/**/*.py` | UGC pipeline updated to import only from `jevtrends.core` and `jevtrends.ugc` | Task 2 |
| `tests/ugc/**/*.py` | UGC tests updated to import only from `jevtrends.core`, `jevtrends.ugc`, and `tests.helpers` | Task 2 |
| `src/jevtrends/opportunities/**/*.py` | Opportunities pipeline package (`models`, `config`, `questions`, `prompts`, `scoring`, `budget`, `store`, `context`, `stages/*`, `templates/report.md.j2`, `pipeline`, `evaluation`, `cli`) | Task 3 |
| `src/jevtrends/cli.py` | Root Typer app mounting `opportunities_app` and `ugc_app` | Task 3 |
| `config/opportunities/{settings,niches}.yaml` | Opportunities configuration files | Task 3 |
| `scripts/opportunities_contract_check.py` | Opportunities live API contract check script | Task 3 |
| `tests/opportunities/**/*.py` | Opportunities unit and offline e2e test suite | Task 3 |
| `tests/core/test_architecture.py` | AST import-boundary test enforcing separation between `core`, `opportunities`, and `ugc` | Task 4 |
| `README.md` | Updated CLI commands, env vars, config/report paths, and repo layout | Task 4 |

---

### Task 1: Build `src/jevtrends/core/` and `tests/core/`

**Files:**
- Create: `src/jevtrends/core/__init__.py`
- Create: `src/jevtrends/core/models.py`
- Create: `src/jevtrends/core/config.py`
- Create: `src/jevtrends/core/http.py`
- Create: `src/jevtrends/core/jev.py`
- Create: `src/jevtrends/core/llm.py`
- Create: `src/jevtrends/core/budget.py`
- Create: `src/jevtrends/core/scoring.py`
- Create: `src/jevtrends/core/store.py`
- Create: `src/jevtrends/core/context.py`
- Create: `src/jevtrends/core/sources/__init__.py`
- Create: `src/jevtrends/core/sources/base.py`
- Create: `src/jevtrends/core/sources/scrapecreators.py`
- Modify: `tests/helpers.py`
- Move: `tests/fixtures/contract/{jev_systemone,llm_chat,sc_comments,sc_search,sc_transcript}.json` → `tests/fixtures/contract/opportunities/`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_http.py`
- Create: `tests/core/test_jev.py`
- Create: `tests/core/test_llm.py`
- Create: `tests/core/test_llm_images.py`
- Create: `tests/core/test_scrapecreators.py`
- Create: `tests/core/test_scrapecreators_ugc.py`
- Create: `tests/core/test_video_fields.py`
- Create: `tests/core/test_budget.py`
- Create: `tests/core/test_scoring.py`
- Create: `tests/core/test_store.py`
- Create: `tests/core/test_context.py`
- Create: `tests/core/test_contract_fixtures.py`

**Interfaces:**
- Consumes: standard library, `httpx`, `pydantic`, `typer`
- Produces: `jevtrends.core.{models,config,http,jev,llm,budget,scoring,store,context}` and `jevtrends.core.sources.{base,scrapecreators}`, plus `tests.helpers.{make_video,FakeSource,FakeJev,FakeLLM}`

- [ ] **Step 1: Create `src/jevtrends/core/` modules (`models.py`, `config.py`, `http.py`, `jev.py`, `llm.py`)**

Create `src/jevtrends/core/__init__.py` (empty) and write the following modules:

`src/jevtrends/core/models.py`:
```python
"""Domain models shared across pipelines."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SoundInfo(BaseModel):
    """The sound a video uses. `licensing` keeps TikTok's raw, undocumented flags (UGC spec §2.3)."""

    id: str
    title: str = ""
    author: str = ""
    is_original: bool = False
    use_count: int = 0
    licensing: dict[str, bool | int | None] = Field(default_factory=dict)
    id_rounded: bool = False  # Top search sends the id as a JSON number already rounded to a double upstream


class Video(BaseModel):
    id: str
    url: str
    author_id: str
    author_handle: str
    author_bio: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    sound: str = ""
    posted_at: datetime
    views: int = 0
    likes: int = 0
    comment_count: int = 0
    shares: int = 0
    language: str | None = None
    raw: dict = Field(default_factory=dict)
    # Filled for the UGC pipeline (UGC spec §5.2); opportunities ignores them.
    duration_ms: int | None = None
    is_slideshow: bool = False
    cover_url: str | None = None
    slide_urls: list[str] = Field(default_factory=list)
    sound_info: SoundInfo | None = None
    author_followers: int | None = None
    saves: int = 0
    editing_features: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    ad_flags: dict[str, bool | int] = Field(default_factory=dict)


class Comment(BaseModel):
    text: str
    likes: int = 0


class VisionRead(BaseModel):
    """On-screen text and setup read from a video's cover frame or first slides (UGC spec §6.4)."""

    on_screen_text: str = ""
    setup: str = ""
    status: Literal["ok", "no_image", "error"] = "ok"
    model: str = ""


class Enrichment(BaseModel):
    video_id: str
    transcript: str | None = None
    transcript_status: Literal["ok", "missing", "error", "not_applicable"] | None = None
    transcript_fetched_at: datetime | None = None
    comments: list[Comment] | None = None
    comments_fetched_at: datetime | None = None
    vision: VisionRead | None = None


class Answer(BaseModel):
    """One Jev answer. value is a probability (noul), an option key (choice) or a level score (score)."""

    value: float | str
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
```

`src/jevtrends/core/config.py`:
```python
"""Shared configuration building blocks and API key check."""

import os

import typer
from pydantic import BaseModel

KEYS = ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")


def require_keys() -> dict[str, str]:
    missing = [name for name in KEYS if not os.environ.get(name)]
    if missing:
        typer.echo(f"Missing {', '.join(missing)}. Run commands through scripts/scan.sh, which loads the keys "
                   "from ~/Repos/.env.secrets.", err=True)
        raise typer.Exit(2)
    return {name: os.environ[name] for name in KEYS}


class PricingCfg(BaseModel):
    jev_input_per_mtok: float = 0.042
    llm_input_per_mtok: float = 5.00
    llm_output_per_mtok: float = 25.00
    scrapecreators_per_credit: float = 0.00188
    discover_expected_output_tokens: int = 15_000
    brief_expected_output_tokens: int = 3_000


class BudgetCfg(BaseModel):
    max_usd_per_scan: float = 5.00


class ConcurrencyCfg(BaseModel):
    jev: int = 16
    scraper: int = 5
    llm: int = 5


class RetriesCfg(BaseModel):
    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0


class FailureCfg(BaseModel):
    max_item_failure_rate: float = 0.20


class LlmCfg(BaseModel):
    use_json_schema: bool = True
```

`src/jevtrends/core/http.py`:
Copy `src/jevtrends/http.py` changing `from jevtrends.config import RetriesCfg` to `from jevtrends.core.config import RetriesCfg`.

`src/jevtrends/core/jev.py`:
Combine `src/jevtrends/jev/client.py` with `Question`, `payload`, `NONE_OF_THESE`, and `IS_PROMOTIONAL` from `src/jevtrends/jev/questions.py`, importing from `jevtrends.core.{config,http,models}`.

`src/jevtrends/core/llm.py`:
Combine `src/jevtrends/llm/client.py` with `EvidenceRef` from `src/jevtrends/llm/prompts.py`, importing from `jevtrends.core.{config,http}`.

- [ ] **Step 2: Create `src/jevtrends/core/` modules (`budget.py`, `scoring.py`, `store.py`, `context.py`, `sources/*`)**

`src/jevtrends/core/budget.py`:
```python
"""Shared budget guard and trimming helper (spec §12.1)."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from jevtrends.core.config import PricingCfg

SEARCH_PAGES_PER_QUERY = 2


@dataclass
class Trimmable:
    """Optional work the guard may cut, listed in the order it is cut (spec §12.1)."""

    name: str
    units: int
    unit_cost: float
    minimum: int
    note: Callable[[int, int], str]  # (kept, original) -> the trim note


@dataclass
class TrimResult:
    ok: bool
    units: dict[str, int]
    projected: float
    trims: list[str] = field(default_factory=list)


def trim_to_fit(available: float, fixed_cost: float, items: list[Trimmable]) -> TrimResult:
    """Cuts each item in order, as little as needed, until fixed_cost plus the remaining items fit."""
    units = {item.name: item.units for item in items}

    def total() -> float:
        return fixed_cost + sum(units[item.name] * item.unit_cost for item in items)

    trims: list[str] = []
    for item in items:
        if total() > available and units[item.name] > item.minimum and item.unit_cost > 0:
            cut = min(units[item.name] - item.minimum, math.ceil((total() - available) / item.unit_cost))
            units[item.name] -= cut
            trims.append(item.note(units[item.name], item.units))
    projected = total()
    return TrimResult(ok=projected <= available, units=units, projected=projected, trims=trims)


class BudgetGuard:
    def __init__(self, cap_usd: float, pricing: PricingCfg):
        self.cap = cap_usd
        self.pricing = pricing

    def scraper_cost(self, requests: int) -> float:
        return requests * self.pricing.scrapecreators_per_credit

    def jev_cost(self, chars: int) -> float:
        return math.ceil(chars / 4) * 1.2 * self.pricing.jev_input_per_mtok / 1e6

    def llm_cost(self, input_chars: int, output_tokens: int) -> float:
        return (math.ceil(input_chars / 4) * self.pricing.llm_input_per_mtok
                + output_tokens * self.pricing.llm_output_per_mtok) / 1e6
```

`src/jevtrends/core/scoring.py`:
```python
"""Pure scoring functions shared across pipelines (spec §6.6–§6.8)."""

import math
import statistics
from datetime import datetime, timedelta

EVIDENCE_MIN_P = 0.2  # below this a video is not evidence for the trend (most Jev probabilities are exactly 0)


def support(members: dict[str, float]) -> float:
    return sum(members.values())


def confident(members: dict[str, float], threshold: float) -> list[str]:
    return [video_id for video_id, p in members.items() if p >= threshold]


def prune_reason(members: dict[str, float], creator_of: dict[str, str], min_support: float,
                 min_creators: int, threshold: float) -> str | None:
    total = support(members)
    if total < min_support:
        return f"support {total:.1f} < {min_support}"
    creators = {creator_of[video_id] for video_id in confident(members, threshold)}
    if len(creators) < min_creators:
        return f"{len(creators)} distinct creators < {min_creators}"
    return None


def top_choices(probs_by_video: dict[str, dict[str, float]]) -> dict[str, str]:
    return {video_id: max(probs, key=probs.get) for video_id, probs in probs_by_video.items() if probs}


def self_check(trend_id: str, example_ids: list[str], top_choice: dict[str, str]) -> float | None:
    judged = [video_id for video_id in example_ids if video_id in top_choice]
    if not judged:
        return None
    return sum(top_choice[video_id] == trend_id for video_id in judged) / len(judged)


def none_rate(top_choice: dict[str, str], none_key: str) -> float:
    if not top_choice:
        return 0.0
    return sum(choice == none_key for choice in top_choice.values()) / len(top_choice)


def recent_start(now: datetime, lookback_days: int, recent_fraction: float) -> datetime:
    return now - timedelta(days=lookback_days * recent_fraction)


def corpus_recent_share(posted_at: dict[str, datetime], start: datetime) -> float:
    if not posted_at:
        return 0.0
    return sum(ts >= start for ts in posted_at.values()) / len(posted_at)


def momentum(members: dict[str, float], posted_at: dict[str, datetime], start: datetime,
             c: float, k: float) -> tuple[float, float]:
    """Shrunk recent-share ratio against the corpus baseline c, and its 0-1 normalization."""
    if c <= 0 or c >= 1:
        return 1.0, 0.5
    total = support(members)
    recent = sum(p for video_id, p in members.items() if posted_at[video_id] >= start)
    ratio = (recent + k * c) / ((total + k) * c)
    return ratio, min(1.0, max(0.0, (math.log2(ratio) + 2) / 4))


def breadth_norm(creators: int) -> float:
    return min(1.0, math.log(1 + creators) / math.log(21))


def promo_share(members: dict[str, float], promo_prob: dict[str, float]) -> float:
    total = support(members)
    if total == 0:
        return 0.0
    return sum(p for video_id, p in members.items() if promo_prob.get(video_id, 0.0) >= 0.5) / total


def median_views(video_ids: list[str], views: dict[str, int]) -> float:
    return float(statistics.median(views[v] for v in video_ids)) if video_ids else 0.0


def evidence_set(members: dict[str, float], size: int, min_p: float = EVIDENCE_MIN_P) -> list[str]:
    ranked = sorted(((v, p) for v, p in members.items() if p >= min_p), key=lambda kv: (-kv[1], kv[0]))
    return [video_id for video_id, _ in ranked[:size]]
```

`src/jevtrends/core/store.py`:
Base `Store` with `CORE_SCHEMA` (tables `runs`, `videos`, `run_videos`, `enrichments`, `judgments`, `api_calls`), `_now()`, and the shared run, video, enrichment, judgment, and spend methods from `src/jevtrends/store.py` (excluding `get_run`, `trends`, `trend_members`, `trend_scores`, `briefs`, `labels` which belong to `OpportunitiesStore`). Keep `SCHEMA = CORE_SCHEMA` alias if helpful, and `schema(self) -> str: return CORE_SCHEMA`.

`src/jevtrends/core/context.py`:
`JevLike`, `LLMLike`, `StageFailed`, `BudgetExceeded`, `ContextHelpers`, `run_items`, `run_stages`, plus `is_english_or_unknown`, `gate_state`, `truncate_words`, `clip`.

`src/jevtrends/core/sources/`:
Copy `src/jevtrends/sources/{__init__,base,scrapecreators}.py` into `src/jevtrends/core/sources/`, updating imports to `jevtrends.core.{config,http,models}` and `jevtrends.core.sources.base`.

- [ ] **Step 3: Move contract fixtures and create `tests/helpers.py` and `tests/core/`**

1. Move `tests/fixtures/contract/{jev_systemone,llm_chat,sc_comments,sc_search,sc_transcript}.json` into `tests/fixtures/contract/opportunities/`.
2. Update `tests/helpers.py` to import `Video`, `Comment`, `Answer` from `jevtrends.core.models` and include `FakeSource`, `FakeJev`, and `FakeLLM` (importing from `jevtrends.core.{http,jev,llm}` and `jevtrends.core.sources.base`).
3. Create `tests/core/` with:
   - `test_http.py` (testing `jevtrends.core.http`)
   - `test_jev.py` (testing `JevClient`, `parse_answer`, `Question`, `payload`, and `tests/fixtures/contract/opportunities/jev_systemone.json`)
   - `test_llm.py` (testing `LLMClient`, `strict_schema` with a local schema model)
   - `test_llm_images.py` (testing `ImagePart`, `content_chars`, `LLMClient` image/effort support)
   - `test_scrapecreators.py` and `test_scrapecreators_ugc.py` (pointing `CONTRACT` to `tests/fixtures/contract/opportunities` and `tests/fixtures/contract/ugc`)
   - `test_video_fields.py` (testing `Video`, `SoundInfo`, `VisionRead`, `Enrichment` round-trip in `Store`)
   - `test_budget.py` (testing `BudgetGuard.llm_cost`, `scraper_cost`, `jev_cost`, and `trim_to_fit`)
   - `test_scoring.py` (testing `support`, `confident`, `prune_reason`, `top_choices`, `self_check`, `none_rate`, `recent_start`, `corpus_recent_share`, `momentum`, `breadth_norm`, `promo_share`, `median_views`, `evidence_set`)
   - `test_store.py` (testing `Store` run basics, videos, enrichments, judgments, spend, notes, failures, and subclass schema extension)
   - `test_context.py` (testing `ContextHelpers`, `run_items`, `run_stages`, `BudgetExceeded`, `is_english_or_unknown`, `gate_state`, `truncate_words`, `clip`)
   - `test_contract_fixtures.py` (checking both `tests/fixtures/contract/opportunities` and `tests/fixtures/contract/ugc`)

- [ ] **Step 4: Run `tests/core/` to verify all core tests pass**

Run: `uv run pytest tests/core -q`
Expected: PASS (all core unit and fixture tests pass).

- [ ] **Step 5: Commit Task 1**

```bash
git add src/jevtrends/core tests/helpers.py tests/fixtures/contract tests/core
git commit -m "refactor: extract shared jevtrends.core package and core tests"
```

---

### Task 2: Migrate `src/jevtrends/ugc/`, `tests/ugc/`, and `scripts/ugc_contract_check.py` onto `jevtrends.core`

**Files:**
- Modify: `src/jevtrends/ugc/budget.py`
- Modify: `src/jevtrends/ugc/cli.py`
- Modify: `src/jevtrends/ugc/config.py`
- Modify: `src/jevtrends/ugc/context.py`
- Modify: `src/jevtrends/ugc/images.py`
- Modify: `src/jevtrends/ugc/pipeline.py`
- Modify: `src/jevtrends/ugc/prompts.py`
- Modify: `src/jevtrends/ugc/questions.py`
- Modify: `src/jevtrends/ugc/store.py`
- Modify: `src/jevtrends/ugc/stages/{assign,brief,collect,discover,enrich,gate,judge,look,report,score,sounds}.py`
- Modify: `tests/ugc/fakes.py`
- Modify: `tests/ugc/test_{cli,look,pipeline_offline,prompts,questions,report,stage_brief,stage_score,stages_collect_gate_enrich,stages_discover_assign,stages_judge_sounds}.py`

**Interfaces:**
- Consumes: `jevtrends.core.*`, `tests.helpers.{make_video,FakeSource,FakeJev,FakeLLM}`
- Produces: `jevtrends.ugc.*` with zero imports from root `jevtrends.*` or V1 `stages/*`

- [ ] **Step 1: Update imports in `src/jevtrends/ugc/` to use `jevtrends.core`**

Update every module in `src/jevtrends/ugc/`:
- `ugc/budget.py`: `from jevtrends.core.budget import BudgetGuard, Trimmable, trim_to_fit`
- `ugc/config.py`: `from jevtrends.core.config import BudgetCfg, ConcurrencyCfg, FailureCfg, LlmCfg, PricingCfg, RetriesCfg`
- `ugc/store.py`: `from jevtrends.core.store import CORE_SCHEMA, Store, _now` and in `UgcStore.schema()`: `return CORE_SCHEMA + UGC_SCHEMA`
- `ugc/questions.py`: `from jevtrends.core.jev import IS_PROMOTIONAL, NONE_OF_THESE, Question`
- `ugc/prompts.py`: `from jevtrends.core.llm import EvidenceRef`
- `ugc/images.py`: `from jevtrends.core.config import RetriesCfg`, `from jevtrends.core.http import APIError, send_with_retry`, `from jevtrends.core.llm import ImagePart`
- `ugc/context.py`: import `BudgetGuard` from `jevtrends.core.budget`, `FatalAPIError` from `jevtrends.core.http`, `ImagePart, LLMResult` from `jevtrends.core.llm`, `UgcSource` from `jevtrends.core.sources.base`, `ContextHelpers, JevLike, LLMLike` from `jevtrends.core.context`
- `ugc/pipeline.py`: `from jevtrends.core.context import BudgetExceeded, run_stages`
- `ugc/cli.py`: import `BudgetGuard` from `jevtrends.core.budget`, `require_keys` from `jevtrends.core.config`, `APIError` from `jevtrends.core.http`, `JevClient` from `jevtrends.core.jev`, `LLMClient` from `jevtrends.core.llm`, `ScrapeCreatorsSource` from `jevtrends.core.sources.scrapecreators`, `BudgetExceeded, StageFailed` from `jevtrends.core.context` (and remove the lazy `from jevtrends.cli import require_keys` inside `require()`)
- `ugc/stages/collect.py`: import `APIError` from `jevtrends.core.http`, `SearchPage` from `jevtrends.core.sources.base`, `is_english_or_unknown, run_items` from `jevtrends.core.context`
- `ugc/stages/gate.py`: import `gate_state, run_items` from `jevtrends.core.context`
- `ugc/stages/enrich.py`: import `Enrichment` from `jevtrends.core.models`, `run_items` from `jevtrends.core.context`
- `ugc/stages/look.py`: import `ImagePart, LLMOutputError` from `jevtrends.core.llm`, `Enrichment, VisionRead` from `jevtrends.core.models`, `run_items, truncate_words` from `jevtrends.core.context`
- `ugc/stages/judge.py`: import `Enrichment, Video` from `jevtrends.core.models`, `run_items, truncate_words` from `jevtrends.core.context`
- `ugc/stages/sounds.py`: import `APIError` from `jevtrends.core.http`, `Song` from `jevtrends.core.sources.base`, `gate_state, run_items` from `jevtrends.core.context`
- `ugc/stages/discover.py`: import `LLMOutputError` from `jevtrends.core.llm`, `Enrichment, Video` from `jevtrends.core.models`, `StageFailed, clip` from `jevtrends.core.context`
- `ugc/stages/assign.py`: import `scoring as base` from `jevtrends.core`, `NONE_OF_THESE, Question` from `jevtrends.core.jev`, `run_items` from `jevtrends.core.context`
- `ugc/stages/score.py`: import `scoring as base` from `jevtrends.core`, ` evidence_set` from `jevtrends.core.scoring`, `Question` from `jevtrends.core.jev`, `Enrichment, Video` from `jevtrends.core.models`, `run_items, truncate_words` from `jevtrends.core.context`
- `ugc/stages/brief.py`: import `LLMOutputError` from `jevtrends.core.llm`, `Video` from `jevtrends.core.models`, `run_items, truncate_words` from `jevtrends.core.context`
- `ugc/stages/report.py`: import `scoring as base` from `jevtrends.core`, `NONE_OF_THESE` from `jevtrends.core.jev`, `Video` from `jevtrends.core.models`, `truncate_words` from `jevtrends.core.context`

- [ ] **Step 2: Update `tests/ugc/` to import from `jevtrends.core` and `tests.helpers`**

Update `tests/ugc/fakes.py` and `tests/ugc/test_*.py` so all shared imports come from `jevtrends.core.*` and `tests.helpers` (`FakeJev`, `FakeLLM`, `FakeSource`, `make_video`) rather than `tests.fakes` or root `jevtrends.*`.

- [ ] **Step 3: Run `tests/core` and `tests/ugc` to verify everything passes**

Run: `uv run pytest tests/core tests/ugc -q`
Expected: PASS.

- [ ] **Step 4: Commit Task 2**

```bash
git add src/jevtrends/ugc tests/ugc
git commit -m "refactor: point jevtrends.ugc and its tests at jevtrends.core"
```

---

### Task 3: Create `src/jevtrends/opportunities/`, migrate config/data/reports/scripts, and create `tests/opportunities/`

**Files:**
- Move: `config/settings.yaml` → `config/opportunities/settings.yaml`
- Move: `config/niches.yaml` → `config/opportunities/niches.yaml`
- Move (untracked local files if present): `data/jevtrends.db` → `data/opportunities.db`, `reports/2026-09-29-scan-*.md` → `reports/opportunities/`
- Move: `scripts/contract_check.py` → `scripts/opportunities_contract_check.py`
- Create: `src/jevtrends/opportunities/__init__.py`
- Create: `src/jevtrends/opportunities/models.py`
- Create: `src/jevtrends/opportunities/config.py`
- Create: `src/jevtrends/opportunities/questions.py`
- Create: `src/jevtrends/opportunities/prompts.py`
- Create: `src/jevtrends/opportunities/scoring.py`
- Create: `src/jevtrends/opportunities/budget.py`
- Create: `src/jevtrends/opportunities/store.py`
- Create: `src/jevtrends/opportunities/context.py`
- Create: `src/jevtrends/opportunities/stages/{__init__,collect,gate,enrich,judge,discover,assign,score,brief,report}.py`
- Move: `src/jevtrends/templates/report.md.j2` → `src/jevtrends/opportunities/templates/report.md.j2`
- Create: `src/jevtrends/opportunities/pipeline.py`
- Create: `src/jevtrends/opportunities/evaluation.py`
- Create: `src/jevtrends/opportunities/cli.py`
- Modify: `src/jevtrends/cli.py`
- Delete: old V1 files at `src/jevtrends/{budget,config,evaluation,http,models,pipeline,scoring,store}.py` and `src/jevtrends/{jev,llm,sources,stages,templates}/`
- Create: `tests/opportunities/{__init__,fakes,test_config,test_questions,test_prompts,test_scoring,test_budget,test_store,test_stages_collect_gate_enrich,test_stages_judge_discover_assign,test_stages_score_brief,test_report,test_evaluation,test_cli,test_pipeline_offline}.py`
- Delete: `tests/unit/`, `tests/e2e/`, `tests/fakes.py`

**Interfaces:**
- Consumes: `jevtrends.core.*`
- Produces: `jevtrends.opportunities.*`, symmetric `jevtrends {opportunities,ugc}` CLI, and `tests/opportunities/`

- [ ] **Step 1: Move config, local data/reports, and contract check script**

1. `git mv config/settings.yaml config/opportunities/settings.yaml` and `git mv config/niches.yaml config/opportunities/niches.yaml`.
2. If `data/jevtrends.db` exists locally, move it to `data/opportunities.db`. If `reports/2026-09-29-scan-*.md` exist locally, move them into `reports/opportunities/`.
3. `git mv scripts/contract_check.py scripts/opportunities_contract_check.py` and update `OUT` in `scripts/opportunities_contract_check.py` to `Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract" / "opportunities"` (and update its docstring/print messages accordingly).

- [ ] **Step 2: Create `src/jevtrends/opportunities/` modules and stages**

Create `src/jevtrends/opportunities/`:
- `models.py`: `TrendKind`, `Trend`, `TrendScore`.
- `config.py`: `WEIGHT_KEYS`, `ScanCfg`, `ThresholdsCfg`, `EnrichCfg`, `TrendsCfg`, `RankingCfg`, `BriefsCfg`, `ModelsCfg`, `Settings`, `Niche`, `NicheConfig`, `load_settings`, `load_niches`, `parse_weights` (importing `BudgetCfg, ConcurrencyCfg, FailureCfg, LlmCfg, PricingCfg, RetriesCfg` from `jevtrends.core.config`).
- `questions.py`: `MAYBE_SIGNAL`, `IS_SIGNAL`, `SIGNAL_TYPE`, `PAIN`, `SPEND`, `UNDERSERVED`, `MENTIONS_SOLUTIONS`, `TREND_QUESTIONS`, `niche_question`, `judge_questions`, `assign_question` (importing `IS_PROMOTIONAL, NONE_OF_THESE, Question, payload` from `jevtrends.core.jev`, `Niche` from `jevtrends.opportunities.config`, `Trend` from `jevtrends.opportunities.models`).
- `prompts.py`: `TrendProposal`, `DiscoverOut`, `StartupAngle`, `BriefOut`, `trend_count_range`, `discover_system`, `DISCOVER_SYSTEM`, `discover_user_prompt`, `BRIEF_SYSTEM`, `brief_user_prompt` (importing `EvidenceRef` from `jevtrends.core.llm`).
- `scoring.py`: `niche_affinity`, `assigned_niches`, `normalized_jev_scores`, `opportunity`, `rank_scores`, `select_for_briefs` (and re-exporting or using `jevtrends.core.scoring` functions as needed).
- `budget.py`: `STAGE_ORDER`, `CHARS`, `GATE_PASS_RATE`, `SIGNAL_RATE`, `EXPECTED_TRENDS`, `RemainingWork`, `Projection`, `Decision`, `remaining_work`, `project_opportunities(guard: BudgetGuard, work: RemainingWork) -> Projection`, `decide_opportunities(guard: BudgetGuard, spent: float, work: RemainingWork, min_briefs: int) -> Decision`.
- `store.py`: `OPPORTUNITIES_SCHEMA` (`trends`, `trend_members`, `trend_scores`, `briefs`, `labels`) and `OpportunitiesStore(Store)` with `schema()` returning `CORE_SCHEMA + OPPORTUNITIES_SCHEMA`, `get_run()`, `upsert_trend`, `list_trends`, `replace_trend_members`, `trend_members`, `upsert_trend_score`, `list_trend_scores`, `upsert_brief`, `list_briefs`, `add_label`, `list_labels`.
- `context.py`: `RunContext(ContextHelpers)` and `report_context(store: OpportunitiesStore, run_id: int) -> RunContext`.
- `stages/`: move `src/jevtrends/stages/{collect,gate,enrich,judge,discover,assign,score,brief,report}.py` into `src/jevtrends/opportunities/stages/`, updating imports to `jevtrends.core.*` and `jevtrends.opportunities.*`. Move `src/jevtrends/templates/report.md.j2` to `src/jevtrends/opportunities/templates/report.md.j2`.
- `pipeline.py`: `STAGES`, `known_counts`, `check_budget` (calling `decide_opportunities`), `run_pipeline`, `estimate_scan` (calling `project_opportunities` and `decide_opportunities`).
- `evaluation.py`: `PRECISION_TARGET`, `is_borderline`, `sample_for_labeling`, `compute_metrics` (importing `report_context` from `jevtrends.opportunities.context` and `OpportunitiesStore` from `jevtrends.opportunities.store`).
- `cli.py`: `opportunities_app = typer.Typer(no_args_is_help=True, help="Find startup opportunities in TikTok trends.")` with `config_dir()` (`JEVTRENDS_OPPORTUNITIES_CONFIG_DIR`, default `config/opportunities`), `db_path()` (`JEVTRENDS_OPPORTUNITIES_DB`, default `data/opportunities.db`), `reports_dir()` (`JEVTRENDS_OPPORTUNITIES_REPORTS_DIR`, default `reports/opportunities`), and commands `scan`, `resume`, `report`, `runs`, `label`, `eval`. Fix resume hint messages to say `scripts/scan.sh opportunities resume ...`.

- [ ] **Step 3: Update root `src/jevtrends/cli.py` and remove old root V1 modules**

Replace `src/jevtrends/cli.py` with:
```python
"""Command-line interface (spec §5). Run through scripts/scan.sh so API keys are loaded."""

import typer

from jevtrends.opportunities.cli import opportunities_app
from jevtrends.ugc.cli import ugc_app

app = typer.Typer(no_args_is_help=True, help="Find TikTok trends using Jev.")
app.add_typer(opportunities_app, name="opportunities")
app.add_typer(ugc_app, name="ugc")
```

Remove the old root V1 files and directories:
- `src/jevtrends/{budget,config,evaluation,http,models,pipeline,scoring,store}.py`
- `src/jevtrends/{jev,llm,sources,stages,templates}/`

- [ ] **Step 4: Create `tests/opportunities/` and remove `tests/unit/`, `tests/e2e/`, `tests/fakes.py`**

Create `tests/opportunities/`:
- `fakes.py` (`NOW`, `test_niches`, `make_ctx` using `OpportunitiesStore`, plus re-exporting `FakeSource`, `FakeJev`, `FakeLLM` from `tests.helpers`)
- `test_config.py` (pointing at `ROOT / "config" / "opportunities"`)
- `test_questions.py` (question catalog, `assign_question`, verbatim spec wording check for opportunities questions)
- `test_prompts.py` (prompt fencing, `BriefOut` fields, `trend_count_range`, `discover_system`)
- `test_scoring.py` (`niche_affinity`, `assigned_niches`, `normalized_jev_scores`, `opportunity`, `rank_scores`, `select_for_briefs`)
- `test_budget.py` (`remaining_work`, `project_opportunities`, `decide_opportunities`)
- `test_store.py` (`OpportunitiesStore` run lifecycle with `Settings`/`NicheConfig`, trends, members, scores, briefs, labels)
- `test_stages_collect_gate_enrich.py`
- `test_stages_judge_discover_assign.py`
- `test_stages_score_brief.py`
- `test_report.py`
- `test_evaluation.py`
- `test_cli.py` (invoking `["opportunities", "scan", ...]`, `["opportunities", "runs"]`, `["opportunities", "report", ...]`, `["opportunities", "eval", ...]`, `["opportunities", "label", ...]` with `JEVTRENDS_OPPORTUNITIES_*` env vars)
- `test_pipeline_offline.py` (moved from `tests/e2e/test_pipeline_offline.py`)

Delete `tests/unit/`, `tests/e2e/`, and `tests/fakes.py`.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -q`
Expected: PASS (all tests in `tests/core/`, `tests/opportunities/`, and `tests/ugc/` pass).

- [ ] **Step 6: Commit Task 3**

```bash
git add -A config scripts src tests
git commit -m "refactor: move V1 into jevtrends.opportunities and unify CLI and test layout"
```

---

### Task 4: Add architectural boundary test, update `README.md`, and run CLI verification

**Files:**
- Create: `tests/core/test_architecture.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `src/jevtrends/` AST and CLI
- Produces: automated import-boundary enforcement and updated user documentation

- [ ] **Step 1: Write `tests/core/test_architecture.py` to enforce package import boundaries**

```python
"""Enforces one-way dependency boundaries between core, opportunities, and ugc."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "jevtrends"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("subpackage", "forbidden_prefixes"),
    [
        ("core", ("jevtrends.opportunities", "jevtrends.ugc", "jevtrends.cli")),
        ("opportunities", ("jevtrends.ugc", "jevtrends.cli")),
        ("ugc", ("jevtrends.opportunities", "jevtrends.cli")),
    ],
)
def test_package_import_boundaries(subpackage: str, forbidden_prefixes: tuple[str, ...]):
    violations: list[str] = []
    for path in sorted((SRC / subpackage).rglob("*.py")):
        for mod in imported_modules(path):
            if mod.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(SRC)}: imports {mod}")
    assert violations == []
```

- [ ] **Step 2: Run `pytest` to verify the boundary test passes**

Run: `uv run pytest tests/core/test_architecture.py -v`
Expected: PASS (3 passed).

- [ ] **Step 3: Update `README.md` to reflect the symmetric layout and CLI**

Update `README.md`:
- Table at top: `jevtrends opportunities scan` alongside `jevtrends ugc scan`
- Setup / Check the cost first: `uv run jevtrends opportunities scan --estimate`
- V1 section (`## Startup opportunities`):
  - `config/opportunities/niches.yaml` and `config/opportunities/settings.yaml`
  - `scripts/scan.sh opportunities scan --max-videos 100 --budget 2` and `scripts/scan.sh opportunities scan`
  - Report path: `reports/opportunities/<date>-scan-<run>.md`
  - Command table: `scripts/scan.sh opportunities {scan,runs,resume,report,label,eval}`
- Configuration and data table:
  - `config/opportunities/settings.yaml`, `config/opportunities/niches.yaml`
  - `data/opportunities.db`, `data/ugc.db`
  - `reports/opportunities/`, `reports/ugc/`
  - Env vars: `JEVTRENDS_OPPORTUNITIES_CONFIG_DIR`, `JEVTRENDS_OPPORTUNITIES_DB`, `JEVTRENDS_OPPORTUNITIES_REPORTS_DIR`
- Development section:
  - `scripts/with-secrets.sh uv run python scripts/opportunities_contract_check.py`
  - Updated directory tree (`src/jevtrends/core/`, `src/jevtrends/opportunities/`, `src/jevtrends/ugc/`)

- [ ] **Step 4: Clean up `.superpowers` scratch directory if present and run full verification**

Run:
```bash
rm -rf .superpowers
uv run pytest -q
uv run jevtrends opportunities scan --estimate
uv run jevtrends ugc scan --niche consumer_apps --estimate
uv run jevtrends opportunities runs
uv run jevtrends ugc runs
```
Expected: All tests pass, both `--estimate` commands print projections without errors, and both `runs` commands read the local databases (`data/opportunities.db` and `data/ugc.db`).

- [ ] **Step 5: Commit Task 4**

```bash
git add tests/core/test_architecture.py README.md
git commit -m "docs: update README for symmetric opportunities/ugc layout and add boundary test"
```

# Direct Jev API Key (`TYPESAFE_API_KEY`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `jevtrends` to call Jev directly via TypeSafe's System One API (`https://api.typesafe.ai/v1/systemone`) when `TYPESAFE_API_KEY` is set, while falling back to `OPENROUTER_API_KEY` (`https://openrouter.ai/api/v1/systemone`) when it is not.

**Architecture:** `require_keys()` in `src/jevtrends/core/config.py` continues requiring `OPENROUTER_API_KEY` (needed for Claude LLM and vision calls) and `SCRAPECREATORS_API_KEY`, and additionally includes `TYPESAFE_API_KEY` in the returned dictionary whenever it is set and non-blank in the environment. `JevClient` in `src/jevtrends/core/jev.py` gains `TYPESAFE_JEV_URL = "https://api.typesafe.ai/v1/systemone"`, automatically strips the `"typesafe/"` prefix from `model` when targeting `TYPESAFE_JEV_URL` (turning `"typesafe/jev-1.13"` into `"jev-1.13"`), and exposes `JevClient.from_keys(client, keys, model, retries)` so both `opportunities` and `ugc` CLIs resolve Jev credentials and endpoint through a single factory.

**Tech Stack:** Python 3.12, uv, httpx, Pydantic v2, Typer, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-28-tiktok-trend-classifier-design.md` (§4.1, §14.1) and `docs/superpowers/specs/2026-09-30-ugc-trend-finder-design.md` (§3)

## Global Constraints

- Python `>=3.12`, managed with `uv`. Run tests with `uv run pytest -q`.
- Environment variable name for the direct Jev key is `TYPESAFE_API_KEY` (matching TypeSafe's official SDK).
- Provider selection is automatic: when `TYPESAFE_API_KEY` is set and non-whitespace, Jev calls use `TYPESAFE_API_KEY` against `https://api.typesafe.ai/v1/systemone`; otherwise Jev calls fall back to `OPENROUTER_API_KEY` against `https://openrouter.ai/api/v1/systemone`.
- `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY` remain required for all scans and `ugc niche-draft` because Claude Opus / Haiku calls still go through OpenRouter.
- When `JevClient` targets `https://api.typesafe.ai/v1/systemone`, any leading `"typesafe/"` prefix on `model` is stripped automatically (`"typesafe/jev-1.13"` → `"jev-1.13"`), so `config/*/settings.yaml` needs no changes.
- Strict import boundary enforced by `tests/core/test_architecture.py`: `jevtrends.core` never imports from `jevtrends.opportunities`, `jevtrends.ugc`, or `jevtrends.cli`.
- Tests never touch the network.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/jevtrends/core/config.py` | Validate required env vars (`KEYS`) and collect optional `TYPESAFE_API_KEY` (`OPTIONAL_KEYS`) in `require_keys()` | Task 1 |
| `src/jevtrends/core/jev.py` | Define `TYPESAFE_JEV_URL`, strip `"typesafe/"` prefix when using `TYPESAFE_JEV_URL`, and provide `JevClient.from_keys()` | Task 1 |
| `tests/core/test_config.py` | Unit tests for `require_keys()` with/without `TYPESAFE_API_KEY` | Task 1 |
| `tests/core/test_jev.py` | Unit tests for `JevClient` and `JevClient.from_keys()` against both OpenRouter and TypeSafe endpoints | Task 1 |
| `src/jevtrends/opportunities/cli.py` | Construct `JevClient` via `JevClient.from_keys()` in `_execute()` | Task 2 |
| `src/jevtrends/ugc/cli.py` | Construct `JevClient` via `JevClient.from_keys()` in `_execute()` | Task 2 |
| `scripts/opportunities_contract_check.py` | Prefer `TYPESAFE_API_KEY` + `https://api.typesafe.ai/v1/systemone` in `check_jev()` when `TYPESAFE_API_KEY` is set | Task 2 |
| `scripts/ugc_contract_check.py` | Prefer `TYPESAFE_API_KEY` + `https://api.typesafe.ai/v1/systemone` in `check_jev()` when `TYPESAFE_API_KEY` is set | Task 2 |
| `tests/opportunities/test_cli.py` | Verify `_execute()` wires `JevClient` to TypeSafe when `TYPESAFE_API_KEY` is present and OpenRouter otherwise | Task 2 |
| `tests/ugc/test_cli.py` | Verify `_execute()` wires `JevClient` to TypeSafe when `TYPESAFE_API_KEY` is present and OpenRouter otherwise | Task 2 |
| `README.md` | Document optional `TYPESAFE_API_KEY` alongside `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY` | Task 2 |

---

### Task 1: Core Key Loading and `JevClient` Direct TypeSafe Support

**Files:**
- Modify: `src/jevtrends/core/config.py:1-19`
- Modify: `src/jevtrends/core/jev.py:1-81`
- Create: `tests/core/test_config.py`
- Modify: `tests/core/test_jev.py:1-65`

**Interfaces:**
- Consumes: `os.environ`, `httpx.AsyncClient`, `jevtrends.core.config.RetriesCfg`, `jevtrends.core.http.send_with_retry`, `jevtrends.core.models.Answer`
- Produces:
  - `jevtrends.core.config.KEYS = ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")`
  - `jevtrends.core.config.OPTIONAL_KEYS = ("TYPESAFE_API_KEY",)`
  - `jevtrends.core.config.require_keys() -> dict[str, str]`
  - `jevtrends.core.jev.JEV_URL = "https://openrouter.ai/api/v1/systemone"`
  - `jevtrends.core.jev.TYPESAFE_JEV_URL = "https://api.typesafe.ai/v1/systemone"`
  - `JevClient(client: httpx.AsyncClient, api_key: str, model: str, retries: RetriesCfg, url: str = JEV_URL)`
  - `JevClient.from_keys(client: httpx.AsyncClient, keys: dict[str, str], model: str, retries: RetriesCfg) -> JevClient`

- [ ] **Step 1: Write failing unit tests for `require_keys()` and `JevClient` direct TypeSafe support**

Create `tests/core/test_config.py`:

```python
import pytest
import typer

from jevtrends.core.config import KEYS, OPTIONAL_KEYS, require_keys


def test_require_keys_returns_required_keys_when_typesafe_unset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert KEYS == ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")
    assert OPTIONAL_KEYS == ("TYPESAFE_API_KEY",)
    assert require_keys() == {"OPENROUTER_API_KEY": "or-key", "SCRAPECREATORS_API_KEY": "sc-key"}


def test_require_keys_includes_typesafe_api_key_when_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "  ts-key  ")
    assert require_keys() == {
        "OPENROUTER_API_KEY": "or-key",
        "SCRAPECREATORS_API_KEY": "sc-key",
        "TYPESAFE_API_KEY": "ts-key",
    }


def test_require_keys_ignores_blank_typesafe_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    assert require_keys() == {"OPENROUTER_API_KEY": "or-key", "SCRAPECREATORS_API_KEY": "sc-key"}


def test_require_keys_still_requires_openrouter_even_with_typesafe_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    with pytest.raises(typer.Exit) as exc_info:
        require_keys()
    assert exc_info.value.exit_code == 2
```

Update `tests/core/test_jev.py` to import `TYPESAFE_JEV_URL` and add tests for `JevClient.from_keys()` and `"typesafe/"` prefix stripping:

```python
import json
from pathlib import Path

import httpx
import pytest

from jevtrends.core.config import RetriesCfg
from jevtrends.core.jev import (IS_PROMOTIONAL, JEV_URL, NONE_OF_THESE, TYPESAFE_JEV_URL, JevClient, Question,
                                parse_answer, payload)
from jevtrends.core.models import Answer

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "opportunities" / "jev_systemone.json"
GATE_Q = Question("gate", "maybe_signal", 1, {"type": "noul", "instructions": "Might this video show a signal?"})


def test_parse_answer_types():
    assert parse_answer({"type": "noul", "noul": 0.93}) == Answer(value=0.93)
    choice = parse_answer({"type": "choice", "choice": "a", "probabilities": {"a": 0.9, "b": 0.1}, "confidence": 0.8})
    assert (choice.value, choice.probabilities["b"], choice.confidence) == ("a", 0.1, 0.8)
    score = parse_answer({"type": "score", "score": 1.43, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
                          "legend": {"0": "x"}, "confidence": 0.4})
    assert score.value == 1.43
    with pytest.raises(ValueError):
        parse_answer({"type": "mystery"})


def test_question_primitives():
    assert GATE_Q.id == "gate.maybe_signal" and GATE_Q.version == 1
    assert payload([GATE_Q, IS_PROMOTIONAL]) == {"maybe_signal": GATE_Q.body, "is_promotional": IS_PROMOTIONAL.body}
    assert NONE_OF_THESE == "none_of_these"


async def test_ask_posts_model_state_questions_and_parses_usage():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "jev-1.13", "answers": {"maybe_signal": {"type": "noul", "noul": 0.7}},
                                         "usage": {"input_tokens": 321, "output_tokens": 5}})

    client = JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "typesafe/jev-1.13",
                       RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == JEV_URL
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "typesafe/jev-1.13"
    assert seen["body"]["state"] == {"caption": "hi"}
    assert seen["body"]["questions"]["maybe_signal"]["type"] == "noul"
    assert result.answers["maybe_signal"].value == 0.7
    assert result.input_tokens == 321


async def test_from_keys_prefers_typesafe_and_strips_model_prefix():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "jev-1.13", "answers": {"maybe_signal": {"type": "noul", "noul": 0.8}},
                                         "usage": {"input_tokens": 120, "output_tokens": 12}})

    keys = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k", "TYPESAFE_API_KEY": "ts-k"}
    client = JevClient.from_keys(httpx.AsyncClient(transport=httpx.MockTransport(handler)), keys, "typesafe/jev-1.13",
                                 RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == TYPESAFE_JEV_URL == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer ts-k"
    assert seen["body"]["model"] == "jev-1.13"
    assert result.answers["maybe_signal"].value == 0.8
    assert result.input_tokens == 120


async def test_from_keys_falls_back_to_openrouter_when_typesafe_key_absent():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "typesafe/jev-1.13",
                                         "answers": {"maybe_signal": {"type": "noul", "noul": 0.6}},
                                         "usage": {"input_tokens": 200, "output_tokens": 8}})

    keys = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k"}
    client = JevClient.from_keys(httpx.AsyncClient(transport=httpx.MockTransport(handler)), keys, "typesafe/jev-1.13",
                                 RetriesCfg(max_attempts=1))
    result = await client.ask({"caption": "hi"}, payload([GATE_Q]))
    assert seen["url"] == JEV_URL
    assert seen["auth"] == "Bearer or-k"
    assert seen["body"]["model"] == "typesafe/jev-1.13"
    assert result.input_tokens == 200


async def test_ask_rejects_missing_answers():
    handler = lambda request: httpx.Response(200, json={"answers": {}, "usage": {"input_tokens": 1}})  # noqa: E731
    client = JevClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "m", RetriesCfg(max_attempts=1))
    with pytest.raises(ValueError, match="missing answers"):
        await client.ask({}, payload([GATE_Q]))


@pytest.mark.skipif(not CONTRACT.exists(), reason="Task 1 fixtures not recorded")
def test_parses_recorded_contract_fixture():
    answers = json.loads(CONTRACT.read_text())["response"]["answers"]
    parsed = {key: parse_answer(raw) for key, raw in answers.items()}
    assert set(parsed) == {"is_complaint", "topic", "pain"}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py tests/core/test_jev.py -v`
Expected: FAIL with `ImportError: cannot import name 'OPTIONAL_KEYS' from 'jevtrends.core.config'` and `ImportError: cannot import name 'TYPESAFE_JEV_URL' from 'jevtrends.core.jev'`.

- [ ] **Step 3: Implement `OPTIONAL_KEYS` in `src/jevtrends/core/config.py` and `TYPESAFE_JEV_URL` + `JevClient.from_keys` in `src/jevtrends/core/jev.py`**

Update lines 1-19 of `src/jevtrends/core/config.py`:

```python
"""Shared configuration building blocks and API key check."""

import os

import typer
from pydantic import BaseModel

KEYS = ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")
OPTIONAL_KEYS = ("TYPESAFE_API_KEY",)


def require_keys() -> dict[str, str]:
    missing = [name for name in KEYS if not os.environ.get(name, "").strip()]
    if missing:
        typer.echo(f"Missing {', '.join(missing)}. Run commands through scripts/scan.sh, which loads the keys "
                   "from ~/Repos/.env.secrets.", err=True)
        raise typer.Exit(2)
    found = {name: os.environ[name].strip() for name in KEYS}
    for name in OPTIONAL_KEYS:
        if value := os.environ.get(name, "").strip():
            found[name] = value
    return found
```

Update `src/jevtrends/core/jev.py`:

```python
"""Jev (TypeSafe System One) client via TypeSafe or OpenRouter and shared question primitives (spec §4.1, §7)."""

from dataclasses import dataclass

import httpx

from jevtrends.core.config import RetriesCfg
from jevtrends.core.http import send_with_retry
from jevtrends.core.models import Answer

JEV_URL = "https://openrouter.ai/api/v1/systemone"  # change here if Task 1 found a different endpoint
TYPESAFE_JEV_URL = "https://api.typesafe.ai/v1/systemone"
NONE_OF_THESE = "none_of_these"
```

And in `JevClient` in `src/jevtrends/core/jev.py`:

```python
class JevClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str, retries: RetriesCfg, url: str = JEV_URL):
        self.client = client
        self.api_key = api_key
        self.url = url
        self.model = model.removeprefix("typesafe/") if url == TYPESAFE_JEV_URL else model
        self.retries = retries

    @classmethod
    def from_keys(cls, client: httpx.AsyncClient, keys: dict[str, str], model: str,
                  retries: RetriesCfg) -> "JevClient":
        if typesafe_key := keys.get("TYPESAFE_API_KEY", "").strip():
            return cls(client, typesafe_key, model, retries, url=TYPESAFE_JEV_URL)
        return cls(client, keys["OPENROUTER_API_KEY"], model, retries, url=JEV_URL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py tests/core/test_jev.py -v`
Expected: PASS (all tests in `test_config.py` and `test_jev.py` pass).

- [ ] **Step 5: Commit**

```bash
git add src/jevtrends/core/config.py src/jevtrends/core/jev.py tests/core/test_config.py tests/core/test_jev.py
git commit -m "feat(core): support TYPESAFE_API_KEY in require_keys and JevClient"
```

---

### Task 2: Wire `JevClient.from_keys` into CLI Pipelines, Contract Scripts, and Docs

**Files:**
- Modify: `src/jevtrends/opportunities/cli.py:41-52`
- Modify: `src/jevtrends/ugc/cli.py:53-68`
- Modify: `scripts/opportunities_contract_check.py:16-22,79-90,182-196`
- Modify: `scripts/ugc_contract_check.py:25-30,330-357,380-408`
- Modify: `tests/opportunities/test_cli.py`
- Modify: `tests/ugc/test_cli.py`
- Modify: `README.md:18,32-39,53-68`

**Interfaces:**
- Consumes: `JevClient.from_keys`, `JEV_URL`, `TYPESAFE_JEV_URL` from `jevtrends.core.jev`; `require_keys` from `jevtrends.core.config`
- Produces:
  - `jevtrends.opportunities.cli._execute` wiring `ctx.jev` via `JevClient.from_keys`
  - `jevtrends.ugc.cli._execute` wiring `ctx.jev` via `JevClient.from_keys`

- [ ] **Step 1: Write failing CLI wiring tests in `tests/opportunities/test_cli.py` and `tests/ugc/test_cli.py`**

Add `test_execute_uses_typesafe_key_for_jev_and_openrouter_for_llm` to `tests/opportunities/test_cli.py`:

```python
from jevtrends.core.jev import JEV_URL, TYPESAFE_JEV_URL
from jevtrends.opportunities.cli import _execute
```

```python
async def test_execute_uses_typesafe_key_for_jev_and_openrouter_for_llm(tmp_path, monkeypatch):
    captured = {}

    async def fake_run_pipeline(ctx, out_dir):
        captured["ctx"] = ctx
        return out_dir / "report.md"

    monkeypatch.setattr("jevtrends.opportunities.cli.run_pipeline", fake_run_pipeline)
    store = OpportunitiesStore(tmp_path / "db.sqlite")
    settings = Settings()
    niches = test_niches()
    run_id = store.create_run({}, settings, niches, NOW)

    keys_with_ts = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k", "TYPESAFE_API_KEY": "ts-k"}
    await _execute(store, run_id, settings, niches, NOW, keys_with_ts)
    assert captured["ctx"].jev.api_key == "ts-k"
    assert captured["ctx"].jev.url == TYPESAFE_JEV_URL
    assert captured["ctx"].jev.model == "jev-1.13"
    assert captured["ctx"].llm.api_key == "or-k"

    keys_without_ts = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k"}
    await _execute(store, run_id, settings, niches, NOW, keys_without_ts)
    assert captured["ctx"].jev.api_key == "or-k"
    assert captured["ctx"].jev.url == JEV_URL
    assert captured["ctx"].jev.model == "typesafe/jev-1.13"
    store.close()
```

Add `test_execute_uses_typesafe_key_for_jev_and_openrouter_for_llm_and_vision` to `tests/ugc/test_cli.py`:

```python
from jevtrends.core.jev import JEV_URL, TYPESAFE_JEV_URL
from jevtrends.ugc.cli import _execute
```

```python
async def test_execute_uses_typesafe_key_for_jev_and_openrouter_for_llm_and_vision(tmp_path, monkeypatch):
    captured = {}

    async def fake_run_ugc_pipeline(ctx, out_dir):
        captured["ctx"] = ctx
        return out_dir / "report.md"

    monkeypatch.setattr("jevtrends.ugc.cli.run_ugc_pipeline", fake_run_ugc_pipeline)
    store = UgcStore(tmp_path / "ugc.sqlite")
    settings = UgcSettings()
    profiles = RunProfiles(niche=niche())
    run_id = store.create_run({}, settings, profiles, NOW)

    keys_with_ts = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k", "TYPESAFE_API_KEY": "ts-k"}
    await _execute(store, run_id, settings, profiles, NOW, keys_with_ts)
    assert captured["ctx"].jev.api_key == "ts-k"
    assert captured["ctx"].jev.url == TYPESAFE_JEV_URL
    assert captured["ctx"].jev.model == "jev-1.13"
    assert captured["ctx"].llm.api_key == "or-k"
    assert captured["ctx"].vision.api_key == "or-k"

    keys_without_ts = {"OPENROUTER_API_KEY": "or-k", "SCRAPECREATORS_API_KEY": "sc-k"}
    await _execute(store, run_id, settings, profiles, NOW, keys_without_ts)
    assert captured["ctx"].jev.api_key == "or-k"
    assert captured["ctx"].jev.url == JEV_URL
    assert captured["ctx"].jev.model == "typesafe/jev-1.13"
    store.close()
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `uv run pytest tests/opportunities/test_cli.py tests/ugc/test_cli.py -v`
Expected: FAIL with `AssertionError: assert 'or-k' == 'ts-k'`.

- [ ] **Step 3: Update `opportunities/cli.py`, `ugc/cli.py`, contract check scripts, and `README.md`**

In `src/jevtrends/opportunities/cli.py`, update `_execute` (lines 41-52):

```python
async def _execute(store: OpportunitiesStore, run_id: int, settings: Settings, niches: NicheConfig,
                   started_at: datetime, keys: dict[str, str]) -> Path:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
        ctx = RunContext(
            run_id=run_id, store=store, settings=settings, niches=niches,
            source=ScrapeCreatorsSource(http, keys["SCRAPECREATORS_API_KEY"], settings.retries),
            jev=JevClient.from_keys(http, keys, settings.models.jev, settings.retries),
            llm=LLMClient(http, keys["OPENROUTER_API_KEY"], settings.models.llm, settings.retries,
                          settings.llm.use_json_schema),
            budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=started_at)
        return await run_pipeline(ctx, reports_dir())
```

In `src/jevtrends/ugc/cli.py`, update `_execute` (lines 53-68):

```python
async def _execute(store: UgcStore, run_id: int, settings: UgcSettings, profiles: RunProfiles,
                   started_at: datetime, keys: dict[str, str]) -> Path:
    openrouter = keys["OPENROUTER_API_KEY"]
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as http:
        ctx = UgcRunContext(
            run_id=run_id, store=store, settings=settings, niche=profiles.niche, product=profiles.product,
            source=ScrapeCreatorsSource(http, keys["SCRAPECREATORS_API_KEY"], settings.retries),
            jev=JevClient.from_keys(http, keys, settings.models.jev, settings.retries),
            llm=LLMClient(http, openrouter, settings.models.llm, settings.retries, settings.llm.use_json_schema,
                          effort=settings.models.llm_effort or None),
            vision=LLMClient(http, openrouter, settings.models.vision, settings.retries, settings.llm.use_json_schema,
                             image_tokens=settings.pricing.tokens_per_image),
            images=ImageFetcher(http, settings.retries),
            budget=BudgetGuard(settings.budget.max_usd_per_scan, settings.pricing), now=started_at)
        return await run_ugc_pipeline(ctx, ugc_reports_dir())
```

In `scripts/opportunities_contract_check.py`, add `TYPESAFE = "https://api.typesafe.ai"` at line 18 and update `check_jev` and `main`:

```python
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract" / "opportunities"
OPENROUTER = "https://openrouter.ai/api"
TYPESAFE = "https://api.typesafe.ai"
SC = "https://api.scrapecreators.com"
JEV_MODEL = "typesafe/jev-1.13"
LLM_MODEL = "anthropic/claude-opus-5"
```

```python
async def check_jev(client: httpx.AsyncClient, key: str, typesafe_key: str = "") -> bool:
    if typesafe_key:
        print("Jev via TypeSafe")
        url = f"{TYPESAFE}/v1/systemone"
        body = {**JEV_BODY, "model": JEV_MODEL.removeprefix("typesafe/")}
        resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {typesafe_key}"})
        print(f"  POST {url} -> {resp.status_code}")
        if resp.status_code == 200:
            save("jev_systemone.json", {"endpoint": url, "response": resp.json()})
            return True
        print(f"  body: {resp.text[:300]}")
        return False
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
```

```python
async def main() -> int:
    if "--scrub-fixtures" in sys.argv:
        return scrub_fixtures()
    keys = {name: os.environ.get(name, "").strip() for name in ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")}
    missing = [name for name, value in keys.items() if not value]
    if missing:
        print(f"Missing environment variables: {missing}. Run via scripts/with-secrets.sh.")
        return 2
    typesafe_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    async with httpx.AsyncClient(timeout=120) as client:
        jev_ok = await check_jev(client, keys["OPENROUTER_API_KEY"], typesafe_key)
        llm_ok = await check_llm(client, keys["OPENROUTER_API_KEY"])
        sc_ok = await check_scrapecreators(client, keys["SCRAPECREATORS_API_KEY"])
    print(f"\nRESULT jev={jev_ok} llm={llm_ok} scrapecreators={sc_ok}")
    return 0 if (jev_ok and llm_ok and sc_ok) else 1
```

In `scripts/ugc_contract_check.py`, add `TYPESAFE = "https://api.typesafe.ai/v1"` at line 27 and update `check_jev` and `main`:

```python
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "contract" / "ugc"
OPENROUTER = "https://openrouter.ai/api/v1"
TYPESAFE = "https://api.typesafe.ai/v1"
SC = "https://api.scrapecreators.com"
```

```python
async def check_jev(client: httpx.AsyncClient, key: str, typesafe_key: str = "") -> bool:
    provider = "TypeSafe" if typesafe_key else "OpenRouter"
    base = TYPESAFE if typesafe_key else OPENROUTER
    auth_key = typesafe_key or key
    model = "jev-1.13" if typesafe_key else "typesafe/jev-1.13"
    print(f"Jev via {provider} (D8)")
    niche = {"name": "Consumer apps", "covers": "Apps people use in everyday life", "not_for": "Business software"}
    gate = {"model": model,
            "state": {"caption": "5 apps that feel illegal to know #apps", "hashtags": ["apps"]},
            "questions": {"relevant": {
                "type": "noul",
                "instructions": {"question": "Could this video be about the niche described in `niche`, judging "
                                             "by its caption and hashtags?", "niche": niche},
                "criteria": {"true": "The caption or hashtags hint at anything the niche covers.",
                             "false": "They clearly point to something else."}}}}
    none = {"what": "None of the options clearly fits this video."}
    choices = {"model": model, "state": {"caption": "POV: you finally found an app that tracks habits",
                                         "on_screen_text": "POV: you finally found the app"},
               "questions": {facet: {"type": "choice", "instructions": f"Which of these {facet}s fits this video?",
                                     "criteria": {f"{facet[0]}01": {"what": option}, "none_of_these": none}}
                             for facet, option in (("format", "Green-screen reaction over app screenshots"),
                                                   ("hook", "POV: you finally found an app that ___"),
                                                   ("topic", "Lock-in season"),
                                                   ("need", "I can't stay consistent with habits"))}}
    results = {}
    for name, body in (("gate", gate), ("choices", choices)):
        resp = await client.post(f"{base}/systemone", json=body, headers={"Authorization": f"Bearer {auth_key}"})
        print(f"  {name}: POST {base}/systemone -> {resp.status_code}")
        results[name] = {"status": resp.status_code, "response": resp.json() if resp.status_code == 200 else resp.text[:300]}
    save("jev_ugc.json", results)
    return all(r["status"] == 200 for r in results.values())
```

```python
async def main() -> int:
    keys = {name: os.environ.get(name, "").strip() for name in ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")}
    missing = [name for name, value in keys.items() if not value]
    if missing:
        print(f"Missing environment variables: {missing}. Run via scripts/with-secrets.sh.")
        return 2
    sc, orkey = keys["SCRAPECREATORS_API_KEY"], keys["OPENROUTER_API_KEY"]
    tskey = os.environ.get("TYPESAFE_API_KEY", "").strip()
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
        jev_ok = await check_jev(client, orkey, tskey)
    results = {"hashtag": hashtag_ok, "top": top_ok, "songs": songs_ok, "song_videos": song_videos_ok,
               "images": images_ok, "opus": opus_ok, "haiku": haiku_ok, "jev": jev_ok}
    print("\nRESULT " + " ".join(f"{name}={ok}" for name, ok in results.items()))
    return 0 if all(results.values()) else 1
```

In `README.md`, update the Jev and API keys sections (lines 18, 32-39, 53-68):

```markdown
2. **Judge:** Jev is TypeSafe's decision model (`typesafe/jev-1.13` on OpenRouter, or `jev-1.13` directly on TypeSafe). It answers yes/no, multiple-choice and score questions about every video with calibrated probabilities: whether it's on topic, and whether it's promotional.
```

```markdown
- **An OpenRouter API key** ([openrouter.ai](https://openrouter.ai)) with credits. Claude calls (and Jev calls, unless `TYPESAFE_API_KEY` is set) go through it:
  - `typesafe/jev-1.13` (Jev) for both versions, when `TYPESAFE_API_KEY` is not set;
  - `anthropic/claude-opus-5` for V1;
  - `anthropic/claude-opus-5.5` and `anthropic/claude-haiku-4.5` for the UGC version.
- **A TypeSafe API key (optional)** ([typesafe.ai](https://typesafe.ai)). If `TYPESAFE_API_KEY` is set, Jev calls go directly to `https://api.typesafe.ai/v1/systemone` with model `jev-1.13` instead of OpenRouter.
- **A ScrapeCreators API key** ([scrapecreators.com](https://scrapecreators.com)) with credits.
```

```markdown
### API keys

The CLI requires two environment variables, `OPENROUTER_API_KEY` and `SCRAPECREATORS_API_KEY`, and optionally uses `TYPESAFE_API_KEY` (when set) to call Jev directly via TypeSafe instead of OpenRouter. You can provide them in either of two ways:

- **Export them yourself,** then run commands as `uv run jevtrends …`.
- **Keep them in a file outside the repo,** and run commands as `scripts/scan.sh …`. For example, create `~/.jevtrends.env`:

  ```
  OPENROUTER_API_KEY=your-openrouter-key
  SCRAPECREATORS_API_KEY=your-scrapecreators-key
  # Optional: call Jev directly via TypeSafe instead of OpenRouter
  # TYPESAFE_API_KEY=your-typesafe-key
  ```
```

- [ ] **Step 4: Run the full offline test suite to verify everything passes**

Run: `uv run pytest -q`
Expected: PASS (all tests pass, including the new `test_config.py`, `test_jev.py`, `opportunities/test_cli.py`, `ugc/test_cli.py`, and `test_architecture.py`).

- [ ] **Step 5: Commit**

```bash
git add src/jevtrends/opportunities/cli.py src/jevtrends/ugc/cli.py scripts/opportunities_contract_check.py scripts/ugc_contract_check.py tests/opportunities/test_cli.py tests/ugc/test_cli.py README.md
git commit -m "feat(cli): route Jev calls to TypeSafe when TYPESAFE_API_KEY is set"
```

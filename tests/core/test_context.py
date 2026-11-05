from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from jevtrends.core.config import FailureCfg, PricingCfg
from jevtrends.core.context import (BudgetExceeded, ContextHelpers, StageFailed, clip, gate_state,
                                    is_english_or_unknown, run_items, run_stages, truncate_words)
from jevtrends.core.http import TransientAPIError
from jevtrends.core.jev import Question
from jevtrends.core.store import Store
from tests.helpers import FakeJev, make_video

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
GATE_Q = Question("gate", "maybe_signal", 1, {"type": "noul", "instructions": "Might this video show a signal?"})


class DummySettings(BaseModel):
    pricing: PricingCfg = PricingCfg()
    failure: FailureCfg = FailureCfg()


@dataclass
class DummyCtx(ContextHelpers):
    run_id: int
    store: Store
    settings: DummySettings = field(default_factory=DummySettings)
    jev: object = field(default_factory=FakeJev)


def new_ctx() -> DummyCtx:
    store = Store(":memory:")
    run_id = store.create_run({"x": 1}, DummySettings(), DummySettings(), NOW)
    return DummyCtx(run_id=run_id, store=store)


def recorder(calls: list[str], name: str):
    async def run(ctx) -> None:
        calls.append(name)

    return run


def test_shared_stage_helpers():
    assert [is_english_or_unknown(x) for x in (None, "", "en", "un", "es")] == [True, True, True, True, False]
    assert gate_state(make_video(caption="", hashtags=[])) == {"caption": "", "hashtags": []}
    assert truncate_words("one two three four", 2) == "one two"
    assert truncate_words(None, 5) == ""
    assert clip("  hello   world  ", 20) == "hello world"
    assert clip("abcdefghij", 5) == "abcd…"


async def test_context_helpers_record_spend_and_answers_for_any_context():
    ctx = new_ctx()
    answers = await ctx.ask_jev("gate", "video", "v1", {"caption": "x"}, [GATE_Q])
    assert answers["maybe_signal"].value == 0.9
    assert ctx.answers(GATE_Q)["v1"].value == 0.9
    ctx.record_scraper("collect", "search", 2)
    ctx.record_llm("discover", 1000, 200, None)
    spend = ctx.store.spend_by_provider(ctx.run_id)
    assert spend["scrapecreators"] == pytest.approx(2 * 0.00188)
    assert spend["llm"] == pytest.approx((1000 * 5 + 200 * 25) / 1e6)


async def test_run_items_failure_rate_uses_the_stage_total():
    ctx = new_ctx()

    async def always_fails(item):
        raise TransientAPIError("jev", 503, "busy")

    assert await run_items(ctx, "judge", "jev", list(range(7)), always_fails, 2, total=100) == 7
    with pytest.raises(StageFailed):
        await run_items(ctx, "judge", "jev", list(range(7)), always_fails, 2)


async def test_run_stages_runs_unfinished_stages_in_order_and_completes_the_run():
    ctx = new_ctx()
    ctx.store.mark_stage_done(ctx.run_id, "a")
    calls, checked = [], []
    stages = [(name, recorder(calls, name)) for name in ("a", "b", "c")]
    await run_stages(ctx, stages, lambda c, stage: checked.append(stage))
    assert calls == ["b", "c"] and checked == ["b", "c"]
    assert ctx.store.stage_done(ctx.run_id, "c") and ctx.store.run_basics(ctx.run_id)["status"] == "completed"


async def test_run_stages_records_budget_stops_with_the_stage_name():
    ctx = new_ctx()

    def check(c, stage):
        if stage == "b":
            raise BudgetExceeded("too much")

    with pytest.raises(BudgetExceeded):
        await run_stages(ctx, [("a", recorder([], "a")), ("b", recorder([], "b"))], check)
    assert ctx.store.run_basics(ctx.run_id)["status"] == "budget_exceeded"
    assert ctx.store.notes(ctx.run_id) == ["Attempt stopped at b: too much"]

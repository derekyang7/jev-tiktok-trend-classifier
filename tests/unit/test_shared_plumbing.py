from dataclasses import dataclass

import pytest

from jevtrends.budget import Trimmable, trim_to_fit
from jevtrends.config import Settings
from jevtrends.jev.questions import MAYBE_SIGNAL
from jevtrends.pipeline import BudgetExceeded, run_stages
from jevtrends.stages.context import ContextHelpers
from jevtrends.store import SCHEMA, Store
from tests.fakes import NOW, FakeJev, test_niches


def new_run(store: Store) -> int:
    return store.create_run({"x": 1}, Settings(), test_niches(), NOW)


def recorder(calls: list[str], name: str):
    async def run(ctx) -> None:
        calls.append(name)

    return run


@dataclass
class OtherCtx(ContextHelpers):
    run_id: int
    store: Store
    settings: Settings
    jev: object


async def test_context_helpers_record_spend_and_answers_for_any_context():
    store = Store(":memory:")
    ctx = OtherCtx(new_run(store), store, Settings(), FakeJev())
    answers = await ctx.ask_jev("gate", "video", "v1", {"caption": "x"}, [MAYBE_SIGNAL])
    assert answers["maybe_signal"].value == 0.9
    assert ctx.answers(MAYBE_SIGNAL)["v1"].value == 0.9
    ctx.record_scraper("collect", "search", 2)
    assert store.spend_by_provider(ctx.run_id)["scrapecreators"] == pytest.approx(2 * 0.00188)


@dataclass
class TinyCtx:
    run_id: int
    store: Store


async def test_run_stages_runs_unfinished_stages_in_order_and_completes_the_run():
    store = Store(":memory:")
    ctx = TinyCtx(new_run(store), store)
    store.mark_stage_done(ctx.run_id, "a")
    calls, checked = [], []
    stages = [(name, recorder(calls, name)) for name in ("a", "b", "c")]
    await run_stages(ctx, stages, lambda c, stage: checked.append(stage))
    assert calls == ["b", "c"] and checked == ["b", "c"]
    assert store.stage_done(ctx.run_id, "c") and store.get_run(ctx.run_id)["status"] == "completed"


async def test_run_stages_records_budget_stops_with_the_stage_name():
    store = Store(":memory:")
    ctx = TinyCtx(new_run(store), store)

    def check(c, stage):
        if stage == "b":
            raise BudgetExceeded("too much")

    with pytest.raises(BudgetExceeded):
        await run_stages(ctx, [("a", recorder([], "a")), ("b", recorder([], "b"))], check)
    assert store.get_run(ctx.run_id)["status"] == "budget_exceeded"
    assert store.notes(ctx.run_id) == ["Attempt stopped at b: too much"]


def test_trim_to_fit_cuts_items_in_order_down_to_their_minimums():
    items = [Trimmable("briefs", 10, 0.1, 5, lambda kept, was: f"{kept} of {was} briefs"),
             Trimmable("comments", 100, 0.002, 0, lambda kept, was: f"{kept} of {was} comments")]
    fits = trim_to_fit(2.0, 0.5, items)
    assert fits.ok and fits.units == {"briefs": 10, "comments": 100} and fits.trims == []
    tight = trim_to_fit(1.0, 0.5, items)  # 0.5 + 1.0 + 0.2 = 1.7: briefs go to 5, then comments to 0
    assert tight.ok and tight.units == {"briefs": 5, "comments": 0}
    assert tight.trims == ["5 of 10 briefs", "0 of 100 comments"]
    assert not trim_to_fit(0.4, 0.5, items).ok


class ExtraStore(Store):
    def schema(self) -> str:
        return SCHEMA + "CREATE TABLE IF NOT EXISTS extra (id INTEGER PRIMARY KEY);"


def test_store_subclass_extends_the_schema_and_shares_run_helpers():
    store = ExtraStore(":memory:")
    run_id = new_run(store)
    store.conn.execute("INSERT INTO extra (id) VALUES (1)")
    store.add_note(run_id, "hello")
    store.mark_stage_done(run_id, "collect")
    basics = store.run_basics(run_id)
    assert basics["params"] == {"x": 1, "notes": ["hello"]} and basics["stage_status"] == {"collect": "done"}
    assert basics["started_at"] == NOW and "settings" not in basics

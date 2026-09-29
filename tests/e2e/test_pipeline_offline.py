from datetime import UTC, datetime

import pytest

from jevtrends.config import Settings
from jevtrends.http import FatalAPIError
from jevtrends.llm.prompts import BriefOut, DiscoverOut, EvidenceRef, StartupAngle, TrendProposal
from jevtrends.pipeline import BudgetExceeded, run_pipeline
from jevtrends.store import Store
from tests.fakes import FakeJev, FakeLLM, FakeSource, make_ctx
from tests.helpers import make_video

RECENT, OLD = datetime(2026, 9, 26, tzinfo=UTC), datetime(2026, 9, 6, tzinfo=UTC)


def world() -> dict[str, list[list]]:
    rent = [make_video(id=f"r{i}", author_handle=f"renter{i % 6}", caption=f"rent #{i}",
                       posted_at=RECENT if i % 2 else OLD, comment_count=i) for i in range(12)]
    phones = [make_video(id=f"p{i}", author_handle=f"phone{i}", caption=f"new phone {i}") for i in range(5)]
    dances = [make_video(id=f"d{i}", author_handle=f"dancer{i}", caption=f"dance {i}") for i in range(3)]
    return {"ai app": [phones + dances], "budgeting app": [rent[:6], rent[6:]], "rant": [[]]}


RULES = {
    "maybe_signal": lambda s, k: 0.1 if "dance" in s["caption"] else 0.8,
    "is_signal": lambda s, k: 0.9,
    "is_promotional": lambda s, k: 0.1,
    "niche_*": lambda s, k: 0.8 if k == "niche_fintech_payments" and "rent" in s["caption"] else 0.1,
    "trend": lambda s, k: "t01" if "rent" in s["caption"] else ("t02" if "phone" in s["caption"] else "none_of_these"),
    "pain": lambda s, k: 2.0, "spend": lambda s, k: 2.0, "underserved": lambda s, k: 2.0,
    "mentions_solutions": lambda s, k: 0.8,
}


def responder(system: str, user: str, schema: type):
    if schema is DiscoverOut:
        return DiscoverOut(trends=[
            TrendProposal(id="a", name="Rent splitting", kind="behavior_need", definition="Roommates split rent.",
                          example_video_ids=["v001", "v002"]),
            TrendProposal(id="b", name="Phone upgrades", kind="product_traction", definition="New phones.",
                          example_video_ids=["v003"]),
        ])
    return BriefOut(headline="h", whats_happening="w", who="who", underlying_need="n",
                    evidence=[EvidenceRef(video_id="e01", why="y")], existing_solutions=[],
                    startup_angles=[StartupAngle(idea="i", why_now="n")], risks=["r"])


def settings(**budget) -> Settings:
    s = Settings()
    s.scan = s.scan.model_copy(update={"max_videos": 40})
    if budget:
        s.budget = s.budget.model_copy(update=budget)
    return s


async def test_full_pipeline_offline(tmp_path):
    llm = FakeLLM(responder)
    ctx = make_ctx(source=FakeSource(pages=world(), transcripts={"r1": "splitting rent is a pain"}),
                   jev=FakeJev(rules=RULES), llm=llm, settings=settings())
    path = await run_pipeline(ctx, tmp_path)
    text = path.read_text()
    assert ctx.store.get_run(ctx.run_id)["status"] == "completed"
    assert all(ctx.store.stage_done(ctx.run_id, s) for s in ("collect", "gate", "brief", "report"))
    assert "20 collected → 17 passed filter → 17 signals → 2 trends proposed → 2 kept" in text
    # Phone upgrades outranks Rent splitting on momentum, so match the section and headline, not the rank.
    assert "## Fintech & payments\n\n### " in text and "Rent splitting\n\n**h**" in text
    assert "## Outside your niches" in text and "Phone upgrades" in text
    assert len(llm.calls) == 3  # discover + 2 briefs
    assert ctx.store.total_spend(ctx.run_id) < 5.0


async def test_resume_after_fatal_error_does_not_repeat_work(tmp_path):
    store = Store(":memory:")
    boom = lambda s, q: FatalAPIError("jev", 401, "boom") if "is_signal" in q and s["caption"] == "rent #7" else None  # noqa: E731
    first = make_ctx(source=FakeSource(pages=world()), jev=FakeJev(rules=RULES, fail_when=boom),
                     llm=FakeLLM(responder), settings=settings(), store=store)
    with pytest.raises(FatalAPIError):
        await run_pipeline(first, tmp_path)
    assert store.get_run(first.run_id)["status"] == "failed_resumable"
    assert store.stage_done(first.run_id, "enrich") and not store.stage_done(first.run_id, "judge")
    judged_before = len(store.get_answers(first.run_id, "video", "judge.is_signal", 1))

    source, jev = FakeSource(pages=world()), FakeJev(rules=RULES)
    second = make_ctx(source=source, jev=jev, llm=FakeLLM(responder), settings=settings(), store=store,
                      run_id=first.run_id)
    store.set_run_status(first.run_id, "running")
    await run_pipeline(second, tmp_path)
    assert store.get_run(first.run_id)["status"] == "completed"
    assert source.calls == []
    judge_calls = [q for _, q in jev.calls if "is_signal" in q]
    assert len(judge_calls) == 17 - judged_before
    assert not any("maybe_signal" in q for _, q in jev.calls)
    assert any("Attempt stopped at judge" in note for note in store.notes(first.run_id))


async def test_empty_corpus_produces_a_valid_report(tmp_path):
    dances = [make_video(id=f"d{i}", author_handle=f"dancer{i}", caption=f"dance {i}") for i in range(3)]
    llm = FakeLLM(lambda *args: pytest.fail("LLM must not be called"))
    ctx = make_ctx(source=FakeSource(pages={"ai app": [dances]}), jev=FakeJev(rules=RULES), llm=llm,
                   settings=settings())
    text = (await run_pipeline(ctx, tmp_path)).read_text()
    assert "3 collected → 0 passed filter → 0 signals → 0 trends proposed → 0 kept" in text
    assert "No trends were kept in this scan." in text
    assert "No signal videos, so no trends were proposed." in text


async def test_budget_guard_stops_before_spending(tmp_path):
    source = FakeSource(pages=world())
    ctx = make_ctx(source=source, settings=settings(max_usd_per_scan=0.01))
    with pytest.raises(BudgetExceeded):
        await run_pipeline(ctx, tmp_path)
    assert ctx.store.get_run(ctx.run_id)["status"] == "budget_exceeded"
    assert source.calls == []


async def test_unexpected_error_marks_run_resumable(tmp_path):
    jev = FakeJev(rules=RULES, fail_when=lambda s, q: RuntimeError("bad payload") if "maybe_signal" in q else None)
    ctx = make_ctx(source=FakeSource(pages=world()), jev=jev, settings=settings())
    with pytest.raises(Exception):
        await run_pipeline(ctx, tmp_path)
    assert ctx.store.get_run(ctx.run_id)["status"] == "failed_resumable"
    assert any("Attempt stopped at gate" in note for note in ctx.store.notes(ctx.run_id))

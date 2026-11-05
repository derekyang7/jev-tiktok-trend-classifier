from datetime import UTC, datetime

from pydantic import BaseModel

from jevtrends.core.models import Answer, Comment, Enrichment
from jevtrends.core.store import CORE_SCHEMA, Store
from tests.helpers import make_video

T0 = datetime(2026, 9, 28, 12, tzinfo=UTC)


class DummySnap(BaseModel):
    v: int = 1


def new_store_and_run() -> tuple[Store, int]:
    store = Store(":memory:")
    run_id = store.create_run({"lookback_days": 30}, DummySnap(), DummySnap(), T0)
    return store, run_id


def test_run_basics_and_status_lifecycle():
    store, run_id = new_store_and_run()
    run = store.run_basics(run_id)
    assert run["status"] == "running"
    assert run["started_at"] == T0
    assert not store.stage_done(run_id, "collect")
    store.mark_stage_done(run_id, "collect")
    assert store.stage_done(run_id, "collect")
    store.set_run_status(run_id, "completed", finished=True)
    run = store.run_basics(run_id)
    assert run["status"] == "completed" and run["finished_at"] is not None
    assert [r["id"] for r in store.list_runs()] == [run_id]


def test_videos_and_seed_query_merge():
    store, run_id = new_store_and_run()
    video = make_video()
    store.upsert_video(video)
    store.add_run_video(run_id, video.id, "budgeting app")
    store.add_run_video(run_id, video.id, "credit card hack")
    store.add_run_video(run_id, video.id, "budgeting app")
    assert store.get_video(video.id) == video
    assert store.run_video_ids(run_id) == [video.id]
    row = store.conn.execute("SELECT seed_queries FROM run_videos").fetchone()
    assert row["seed_queries"] == '["budgeting app", "credit card hack"]'
    assert store.query_counts(run_id) == {"budgeting app": 1}
    store.mark_query_done(run_id, "budgeting app")
    assert store.done_queries(run_id) == {"budgeting app"}
    store.set_short_id(run_id, video.id, "v001")
    assert store.short_ids(run_id) == {"v001": video.id}


def test_enrichment_roundtrip():
    store, _ = new_store_and_run()
    enrichment = Enrichment(video_id="1", transcript="hello", transcript_status="ok",
                            transcript_fetched_at=T0, comments=[Comment(text="same", likes=3)], comments_fetched_at=T0)
    store.upsert_enrichment(enrichment)
    assert store.get_enrichment("1") == enrichment
    assert store.get_enrichment("missing") is None


def test_judgments_are_idempotent_and_versioned():
    store, run_id = new_store_and_run()
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 1, Answer(value=0.2))
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 1, Answer(value=0.9))
    store.upsert_judgment(run_id, "video", "1", "judge.is_signal", 2, Answer(value=0.1))
    store.upsert_judgment(run_id, "video", "2", "judge.signal_type", 1,
                          Answer(value="behavior_need", probabilities={"behavior_need": 0.8, "other": 0.2}, confidence=0.7))
    assert store.get_answers(run_id, "video", "judge.is_signal", 1) == {"1": Answer(value=0.9)}
    answer = store.get_answers(run_id, "video", "judge.signal_type", 1)["2"]
    assert answer.value == "behavior_need" and answer.probabilities["other"] == 0.2
    count = store.conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    assert count == 3


def test_spend_and_failures():
    store, run_id = new_store_and_run()
    store.record_api_call(run_id, "gate", "jev", "systemone", {"input_tokens": 100}, 0.01, "ok")
    store.record_api_call(run_id, "enrich", "scrapecreators", "transcript", {"credits": 1}, 0.00188, "ok")
    store.record_api_call(run_id, "judge", "jev", "systemone", {"input_tokens": 100}, 0.02, "ok")
    store.record_api_call(run_id, "judge", "jev", "judge", {"item": "1"}, 0.0, "failed")
    assert store.spend_by_provider(run_id) == {"jev": 0.03, "scrapecreators": 0.00188}
    assert round(store.total_spend(run_id), 5) == 0.03188
    assert store.failures_by_stage(run_id) == {"judge": 1}


def test_run_notes_are_deduplicated_and_persisted():
    store, run_id = new_store_and_run()
    store.add_note(run_id, "momentum undefined")
    store.add_note(run_id, "momentum undefined")
    store.add_note(run_id, "budget trim: 11 briefs written instead of 20")
    assert store.notes(run_id) == ["momentum undefined", "budget trim: 11 briefs written instead of 20"]
    assert store.run_basics(run_id)["params"]["lookback_days"] == 30


class ExtraStore(Store):
    def schema(self) -> str:
        return CORE_SCHEMA + "CREATE TABLE IF NOT EXISTS extra (id INTEGER PRIMARY KEY);"


def test_store_subclass_extends_the_schema_and_shares_run_helpers():
    store = ExtraStore(":memory:")
    run_id = store.create_run({"x": 1}, DummySnap(), DummySnap(), T0)
    store.conn.execute("INSERT INTO extra (id) VALUES (1)")
    store.add_note(run_id, "hello")
    store.mark_stage_done(run_id, "collect")
    basics = store.run_basics(run_id)
    assert basics["params"] == {"x": 1, "notes": ["hello"]} and basics["stage_status"] == {"collect": "done"}
    assert basics["started_at"] == T0 and "settings" not in basics

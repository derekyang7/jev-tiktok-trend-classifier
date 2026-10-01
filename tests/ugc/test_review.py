import sqlite3

import pytest
from typer.testing import CliRunner

from jevtrends.cli import app
from jevtrends.ugc.review import compute_review_metrics, review_items
from jevtrends.ugc.store import UgcStore
from tests.fakes import FakeLLM
from tests.ugc.test_stage_brief import ranked_world

runner = CliRunner()


def world():
    """Task 17's ranked run (f01, h01, s01), with one borderline member (o0 at p = 0.4) added to f01."""
    ctx = ranked_world(FakeLLM(lambda *a: None))
    members = ctx.store.facet_members(ctx.run_id)["f01"]
    members["o0"] = 0.4
    ctx.store.replace_members(ctx.run_id, ["f01"], [("f01", video_id, p) for video_id, p in members.items()])
    return ctx


def test_review_items_sample_confident_and_borderline_members_but_not_for_sounds():
    ctx = world()
    items = {item.trend.trend_id: item for item in review_items(ctx.store, ctx.run_id, n_trends=3)}
    assert list(items) == ["f01", "h01", "s01"]
    f01 = items["f01"]
    assert len(f01.evidence) == 3
    confident = [v for v, p in f01.members if p >= 0.5]
    borderline = [v for v, p in f01.members if p < 0.5]
    assert len(confident) == 4 and borderline == ["o0"]
    assert items["s01"].members == []


def test_metrics_count_verdicts_precision_and_suggest_a_threshold():
    ctx = world()
    store, run_id = ctx.store, ctx.run_id
    for tid, real, brief in (("f01", True, True), ("h01", True, False), ("s01", False, False)):
        store.add_review(run_id, tid, "", "real", real)
        store.add_review(run_id, tid, "", "would_brief", brief)
    for video, fits in (("m0", True), ("m1", True), ("m2", True), ("m3", False), ("o0", True)):
        store.add_review(run_id, "f01", video, "fits", fits)
    metrics = compute_review_metrics(store, run_id)
    assert (metrics["reviewed"], metrics["real"], metrics["would_brief"]) == (3, 2, 1)
    assert metrics["per_facet"]["format"]["precision"] == pytest.approx(0.75)
    assert metrics["per_facet"]["sound"]["precision"] is None
    assert metrics["suggested_threshold"] == 0.35  # 4 of 5 reviewed members at p >= 0.35 fit: 0.80


def test_review_and_eval_commands(tmp_path):
    ctx = world()
    db = tmp_path / "ugc.sqlite"
    target = sqlite3.connect(db)
    ctx.store.conn.backup(target)  # copy the in-memory run to a file the CLI can open
    target.close()
    # f01: real, would brief, 5 members fit | h01: real, would not brief, 4 members fit | s01: neither, no members
    answers = "y\ny\n" + "y\n" * 5 + "y\nn\n" + "y\n" * 4 + "n\nn\n"
    result = runner.invoke(app, ["ugc", "review", str(ctx.run_id), "--trends", "3"],
                           env={"JEVTRENDS_UGC_DB": str(db)}, input=answers)
    assert result.exit_code == 0, result.output
    reviews = UgcStore(db).list_reviews(ctx.run_id)
    assert len(reviews) == 6 + 5 + 4
    result = runner.invoke(app, ["ugc", "eval", str(ctx.run_id)], env={"JEVTRENDS_UGC_DB": str(db)})
    assert result.exit_code == 0 and "Would brief: 1 of 3 reviewed trends" in result.output

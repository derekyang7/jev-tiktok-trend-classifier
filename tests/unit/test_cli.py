from pathlib import Path

from typer.testing import CliRunner

from jevtrends.cli import app
from jevtrends.config import Settings
from jevtrends.store import Store
from tests.fakes import NOW, test_niches

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def env(tmp_path: Path) -> dict[str, str]:
    return {"JEVTRENDS_CONFIG_DIR": str(ROOT / "config"), "JEVTRENDS_DB": str(tmp_path / "db.sqlite"),
            "JEVTRENDS_REPORTS_DIR": str(tmp_path / "reports")}


def test_scan_estimate_prints_projection_without_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(app, ["scan", "--estimate"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Projected cost: $5." in result.output and "cap $5.00" in result.output
    assert "Budget guard would trim: 12 briefs written instead of 20" in result.output
    assert not (tmp_path / "db.sqlite").exists()


def test_scan_without_keys_exits_before_creating_a_run(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)
    result = runner.invoke(app, ["scan"], env=env(tmp_path))
    assert result.exit_code == 2
    assert "scripts/scan.sh" in result.output
    assert not (tmp_path / "db.sqlite").exists()


def test_runs_and_report_commands(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    run_id = store.create_run({}, Settings(), test_niches(), NOW)
    store.close()
    result = runner.invoke(app, ["runs"], env=env(tmp_path))
    assert result.exit_code == 0 and f"#{run_id}" in result.output and "running" in result.output
    weights = "momentum=0.2,pain=0.2,spend=0.2,underserved=0.2,breadth=0.2"
    result = runner.invoke(app, ["report", str(run_id), "--weights", weights], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / "reports" / f"2026-09-28-scan-{run_id}.md").exists()


def test_eval_command_prints_metrics(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    run_id = store.create_run({}, Settings(), test_niches(), NOW)
    store.close()
    result = runner.invoke(app, ["eval", str(run_id)], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Random-sample labels: 0" in result.output and "precision n/a" in result.output


def test_label_command_records_labels_and_reprompts_invalid_type(tmp_path):
    from jevtrends.models import Answer
    from tests.helpers import make_video

    store = Store(tmp_path / "db.sqlite")
    run_id = store.create_run({}, Settings(), test_niches(), NOW)
    store.upsert_video(make_video(id="a"))
    store.add_run_video(run_id, "a", "q")
    store.upsert_judgment(run_id, "video", "a", "gate.maybe_signal", 1, Answer(value=0.9))
    store.upsert_judgment(run_id, "video", "a", "judge.is_signal", 1, Answer(value=0.9))
    store.close()
    answers = "y\nbogus\nbehavior_need\nfintech_payments, not_a_niche\nn\n"
    result = runner.invoke(app, ["label", str(run_id), "--n", "2"], env=env(tmp_path), input=answers)
    assert result.exit_code == 0, result.output
    assert "Choose one of" in result.output
    labels = {row["field"]: row["value"] for row in Store(tmp_path / "db.sqlite").list_labels()}
    assert labels == {"is_signal": True, "signal_type": "behavior_need", "niches": ["fintech_payments"],
                      "is_promotional": False}

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
    assert "Projected cost: $4." in result.output and "cap $5.00" in result.output
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

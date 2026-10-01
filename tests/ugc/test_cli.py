from pathlib import Path

from typer.testing import CliRunner

from jevtrends.cli import app
from jevtrends.ugc.config import RunProfiles, UgcSettings, load_niche
from jevtrends.ugc.niche_draft import draft_niche, render_niche_yaml
from jevtrends.ugc.prompts import NicheDraftOut
from jevtrends.ugc.store import UgcStore
from tests.fakes import FakeLLM
from tests.ugc.fakes import NOW, niche

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def env(tmp_path: Path) -> dict[str, str]:
    return {"JEVTRENDS_UGC_CONFIG_DIR": str(ROOT / "config" / "ugc"), "JEVTRENDS_UGC_DB": str(tmp_path / "ugc.sqlite"),
            "JEVTRENDS_UGC_REPORTS_DIR": str(tmp_path / "reports")}


def test_scan_estimate_prints_the_projection_without_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(app, ["ugc", "scan", "--niche", "consumer_apps", "--estimate"], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Projected cost: $4." in result.output and "cap $5.00" in result.output and "vision $" in result.output
    assert "Budget guard would cut" not in result.output
    assert not (tmp_path / "ugc.sqlite").exists()


def test_scan_without_keys_exits_before_creating_a_run(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)
    result = runner.invoke(app, ["ugc", "scan", "--niche", "consumer_apps"], env=env(tmp_path))
    assert result.exit_code == 2 and "scripts/scan.sh" in result.output
    assert not (tmp_path / "ugc.sqlite").exists()


def test_an_unknown_niche_or_product_is_a_clear_error(tmp_path):
    result = runner.invoke(app, ["ugc", "scan", "--niche", "nope", "--estimate"], env=env(tmp_path))
    assert result.exit_code == 2 and "No niche profile" in result.output
    result = runner.invoke(app, ["ugc", "scan", "--niche", "consumer_apps", "--product", "nope", "--estimate"],
                           env=env(tmp_path))
    assert result.exit_code == 2 and "No product profile" in result.output


def test_runs_and_report_commands(tmp_path):
    store = UgcStore(tmp_path / "ugc.sqlite")
    run_id = store.create_run({}, UgcSettings(), RunProfiles(niche=niche()), NOW)
    store.close()
    result = runner.invoke(app, ["ugc", "runs"], env=env(tmp_path))
    assert result.exit_code == 0 and f"#{run_id}" in result.output
    assert "consumer_apps" in result.output and "generic" in result.output
    weights = "momentum=0.2,performance=0.2,fit=0.2,breadth=0.2,ease=0.2"
    result = runner.invoke(app, ["ugc", "report", str(run_id), "--weights", weights], env=env(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / "reports" / f"2026-10-01-consumer_apps-run-{run_id}.md").exists()


def test_niche_draft_refuses_to_overwrite_an_existing_profile(tmp_path):
    result = runner.invoke(app, ["ugc", "niche-draft", "consumer_apps", "consumer apps"], env=env(tmp_path))
    assert result.exit_code == 1 and "not overwriting" in result.output


async def test_draft_niche_renders_a_loadable_profile(tmp_path):
    draft = NicheDraftOut(name="Pet care", covers="How people care for pets.", not_for="Pet food ads.",
                          audience="Pet owners", seed_queries=[f"Query {i}" for i in range(25)],
                          hashtags=["#dogs", "cats"])
    llm = FakeLLM(lambda *args: draft)
    out, cost = await draft_niche(llm, "pet care apps")
    assert "<niche>\npet care apps\n</niche>" in llm.calls[0][1] and cost == 0.0
    text = render_niche_yaml("pets", out, NOW.date())
    assert text.startswith("# Drafted by `jevtrends ugc niche-draft` on 2026-10-01.")
    (tmp_path / "niches").mkdir()
    (tmp_path / "niches" / "pets.yaml").write_text(text)
    profile = load_niche(tmp_path, "pets")
    assert len(profile.seed_queries) == 20 and profile.seed_queries[0] == "query 0"
    assert profile.hashtags == ["dogs", "cats"]

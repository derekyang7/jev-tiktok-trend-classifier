from pathlib import Path

import pytest
from pydantic import ValidationError

from jevtrends.config import NicheConfig, Settings, load_niches, load_settings, parse_weights

ROOT = Path(__file__).resolve().parents[2]


def test_repo_config_files_load():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    niches = load_niches(ROOT / "config" / "niches.yaml")
    assert settings.models.jev == "typesafe/jev-1.13"
    assert settings.budget.max_usd_per_scan == 5.0
    assert settings.thresholds.borderline == (0.35, 0.65)
    assert len(niches.niches) == 11
    assert len(niches.all_queries()) == 65
    assert niches.ids()[0] == "creator_economy"


def test_weights_must_sum_to_one():
    bad = {"momentum": 0.3, "pain": 0.2, "spend": 0.2, "underserved": 0.1, "breadth": 0.1}
    with pytest.raises(ValidationError, match="sum to 1"):
        Settings.model_validate({"ranking": {"weights": bad}})


def test_weights_need_exactly_the_five_components():
    with pytest.raises(ValidationError, match="keys must be exactly"):
        Settings.model_validate({"ranking": {"weights": {"momentum": 1.0}}})


def test_duplicate_niche_ids_rejected():
    niche = {"id": "ai", "name": "AI", "covers": "c", "not_for": "n", "seed_queries": ["x"]}
    with pytest.raises(ValidationError, match="duplicate niche id"):
        NicheConfig.model_validate({"niches": [niche, niche], "global_seed_queries": []})


def test_all_queries_dedupes_preserving_order():
    cfg = NicheConfig.model_validate({
        "niches": [{"id": "a", "name": "A", "covers": "c", "not_for": "n", "seed_queries": ["x", "y"]}],
        "global_seed_queries": ["y", "z"],
    })
    assert cfg.all_queries() == ["x", "y", "z"]


def test_parse_weights():
    weights = parse_weights("momentum=0.5,pain=0.2,spend=0.1,underserved=0.1,breadth=0.1")
    assert weights == {"momentum": 0.5, "pain": 0.2, "spend": 0.1, "underserved": 0.1, "breadth": 0.1}
    with pytest.raises(ValueError):
        parse_weights("momentum=abc")

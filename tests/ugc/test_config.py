from pathlib import Path

import pytest
from pydantic import ValidationError

from jevtrends.ugc.config import (NicheProfile, ProductProfile, UgcSettings, load_niche, load_product,
                                  load_ugc_settings, parse_ugc_weights)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "ugc"


def test_repo_config_files_load():
    settings = load_ugc_settings(CONFIG / "settings.yaml")
    assert (settings.scan.lookback_days, settings.scan.max_videos) == (14, 600)
    assert settings.budget.max_usd_per_scan == 5.0 and settings.briefs.max_briefs == 11
    assert settings.ranking.weights == {"momentum": 0.25, "performance": 0.25, "fit": 0.30, "breadth": 0.10,
                                        "ease": 0.10}
    assert settings.models.jev == "typesafe/jev-1.13" and settings.concurrency.vision == 8
    assert settings.pricing.llm_output_per_mtok == 20.0 and settings.pricing.scrapecreators_per_credit == 0.00188
    niche = load_niche(CONFIG, "consumer_apps")
    # Hashtag search returns all-time posts, so the first niche uses none (contract check D1).
    assert (len(niche.seed_queries), len(niche.hashtags)) == (15, 0)
    assert len(niche.searches(top_search=True)) == 30
    product = load_product(CONFIG, "example")
    assert [claim.id for claim in product.claims_allowed] == ["c1", "c2"]


def test_defaults_match_the_repo_file():
    assert UgcSettings() == load_ugc_settings(CONFIG / "settings.yaml")


def test_weights_and_quotas_are_validated():
    with pytest.raises(ValidationError, match="sum to 1"):
        UgcSettings.model_validate({"ranking": {"weights": {"momentum": 0.5, "performance": 0.5, "fit": 0.5,
                                                            "breadth": 0.0, "ease": 0.0}}})
    with pytest.raises(ValidationError, match="keys must be exactly"):
        UgcSettings.model_validate({"ranking": {"weights": {"momentum": 1.0}}})
    with pytest.raises(ValidationError, match="quotas keys"):
        UgcSettings.model_validate({"briefs": {"quotas": {"format": 3}}})
    with pytest.raises(ValidationError, match="negative"):
        UgcSettings.model_validate({"briefs": {"quotas": {"format": -1, "hook": 2, "sound": 2, "topic": 2,
                                                          "need": 2}}})


def test_niche_profile_cleans_hashtags_dedupes_queries_and_orders_searches():
    niche = NicheProfile(id="n", name="N", covers="c", not_for="x", seed_queries=["a b", "a b", " c "],
                         hashtags=["#one", "two", "#"])
    assert niche.seed_queries == ["a b", "c"] and niche.hashtags == ["one", "two"]
    assert niche.searches(top_search=True) == ["keyword:a b", "keyword:c", "hashtag:one", "hashtag:two",
                                               "top:a b", "top:c"]
    assert niche.searches(top_search=False) == ["keyword:a b", "keyword:c", "hashtag:one", "hashtag:two"]
    with pytest.raises(ValidationError, match="at least one seed query"):
        NicheProfile(id="n", name="N", covers="c", not_for="x", seed_queries=["  "])


def test_product_claims_need_unique_ids_of_the_form_cN():
    base = {"id": "p", "name": "P", "what_it_does": "w"}
    with pytest.raises(ValidationError, match="unique"):
        ProductProfile.model_validate({**base, "claims_allowed": [{"id": "c1", "text": "a"}, {"id": "c1", "text": "b"}]})
    with pytest.raises(ValidationError):
        ProductProfile.model_validate({**base, "claims_allowed": [{"id": "claim-1", "text": "a"}]})


def test_loading_checks_the_file_and_its_id(tmp_path):
    (tmp_path / "niches").mkdir()
    (tmp_path / "niches" / "pets.yaml").write_text("id: dogs\nname: D\ncovers: c\nnot_for: x\nseed_queries: [q]\n")
    with pytest.raises(ValueError, match="expected 'pets'"):
        load_niche(tmp_path, "pets")
    with pytest.raises(FileNotFoundError, match="No product profile"):
        load_product(tmp_path, "missing")


def test_parse_ugc_weights():
    weights = parse_ugc_weights("momentum=0.2,performance=0.2,fit=0.4,breadth=0.1,ease=0.1")
    assert weights["fit"] == 0.4
    with pytest.raises(ValueError):
        parse_ugc_weights("momentum=abc")

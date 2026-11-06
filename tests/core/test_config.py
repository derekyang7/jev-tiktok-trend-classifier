import pytest
import typer

from jevtrends.core.config import KEYS, OPTIONAL_KEYS, require_keys


def test_require_keys_returns_required_keys_when_typesafe_unset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert KEYS == ("OPENROUTER_API_KEY", "SCRAPECREATORS_API_KEY")
    assert OPTIONAL_KEYS == ("TYPESAFE_API_KEY",)
    assert require_keys() == {"OPENROUTER_API_KEY": "or-key", "SCRAPECREATORS_API_KEY": "sc-key"}


def test_require_keys_includes_typesafe_api_key_when_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "  ts-key  ")
    assert require_keys() == {
        "OPENROUTER_API_KEY": "or-key",
        "SCRAPECREATORS_API_KEY": "sc-key",
        "TYPESAFE_API_KEY": "ts-key",
    }


def test_require_keys_ignores_blank_typesafe_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    assert require_keys() == {"OPENROUTER_API_KEY": "or-key", "SCRAPECREATORS_API_KEY": "sc-key"}


def test_require_keys_still_requires_openrouter_even_with_typesafe_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    with pytest.raises(typer.Exit) as exc_info:
        require_keys()
    assert exc_info.value.exit_code == 2

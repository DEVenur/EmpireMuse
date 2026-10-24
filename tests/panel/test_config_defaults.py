"""config_loader.DEFAULT_CONFIG e .example.env — variáveis PANEL_*."""

import re

import pytest

from tests.panel.helpers import ROOT

EXPECTED_DEFAULTS = {
    "PANEL_ENABLED": False,
    "PANEL_BASE_URL": "",
    "PANEL_OAUTH_CLIENT_ID": "",
    "PANEL_OAUTH_CLIENT_SECRET": "",
    "PANEL_COOKIE_SECRET": "",
    "PANEL_SESSION_TTL_HOURS": 12,
    "PANEL_SESSION_IDLE_MINUTES": 60,
    "PANEL_TRUST_PROXY": False,
    "PANEL_INSECURE_COOKIES": False,
}


def _config_loader(monkeypatch, tmp_path):
    monkeypatch.chdir(
        tmp_path
    )  # isola o config.json real; o .env real é isolado pelo fixture autouse de tests/conftest.py
    for key in EXPECTED_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    import empiremuse.config_loader as config_loader

    return config_loader


@pytest.mark.parametrize("key,expected", list(sorted(EXPECTED_DEFAULTS.items()))[:2])
def test_default_config_has_panel_default(monkeypatch, tmp_path, key, expected):
    default = _config_loader(monkeypatch, tmp_path).DEFAULT_CONFIG.get(key, "<ausente>")
    assert default == expected and type(default) is type(expected), f"DEFAULT_CONFIG[{key!r}] = {default!r}"


def test_load_config_converts_panel_types_from_environment(monkeypatch, tmp_path):
    module = _config_loader(monkeypatch, tmp_path)
    monkeypatch.setenv("PANEL_ENABLED", "true")
    monkeypatch.setenv("PANEL_TRUST_PROXY", "true")
    monkeypatch.setenv("PANEL_INSECURE_COOKIES", "true")
    monkeypatch.setenv("PANEL_SESSION_TTL_HOURS", "24")
    monkeypatch.setenv("PANEL_SESSION_IDLE_MINUTES", "30")
    config = module.load_config()
    assert config["PANEL_ENABLED"] is True
    assert config["PANEL_TRUST_PROXY"] is True
    assert config["PANEL_INSECURE_COOKIES"] is True
    assert config["PANEL_SESSION_TTL_HOURS"] == 24
    assert config["PANEL_SESSION_IDLE_MINUTES"] == 30


def _example_env() -> dict:
    values = {}
    for line in (ROOT / ".example.env").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("'\"")
    return values


@pytest.mark.parametrize("key", list(sorted(EXPECTED_DEFAULTS))[:2])
def test_example_env_declares_panel_variable(key):
    assert key in _example_env(), f".example.env sem {key}"


def test_example_env_documents_redirect_uri_in_portuguese():
    assert "/painel/callback" in (ROOT / ".example.env").read_text(encoding="utf-8")

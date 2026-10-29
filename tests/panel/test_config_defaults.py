"""config_loader.load_config — conversão de tipos das variáveis PANEL_* vindas do ambiente."""

EXPECTED_DEFAULTS = (
    "PANEL_ENABLED",
    "PANEL_TRUST_PROXY",
    "PANEL_INSECURE_COOKIES",
    "PANEL_SESSION_TTL_HOURS",
    "PANEL_SESSION_IDLE_MINUTES",
)


def test_load_config_converts_panel_types_from_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(
        tmp_path
    )  # isola o config.json real; o .env real é isolado pelo fixture autouse de tests/conftest.py
    for key in EXPECTED_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    import empiremuse.config_loader as module

    padrao = module.load_config()
    assert padrao["PANEL_TRUST_PROXY"] is False and padrao["PANEL_INSECURE_COOKIES"] is False

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

"""Guarda de isolamento: a suíte nunca lê o .env/config.json REAIS do desenvolvedor.

Se este arquivo falhar, algum teste voltou a depender do ambiente da máquina (resultado não determinístico e risco de
segredos aparecerem na saída). As mensagens de falha NÃO imprimem valores de configuração.
"""

import pytest


def test_dotenv_values_is_neutralized_for_every_test():
    import empiremuse.config_loader as config_loader

    if config_loader.dotenv_values() != {}:
        pytest.fail(
            "config_loader.dotenv_values() devolveu dados: o fixture autouse de tests/conftest.py não está ativo",
            pytrace=False,
        )


def test_load_config_ignores_the_developers_real_dot_env(monkeypatch, tmp_path):
    import empiremuse.config_loader as config_loader

    monkeypatch.chdir(tmp_path)
    for key in (
        "PANEL_ENABLED",
        "PANEL_OAUTH_CLIENT_ID",
        "PANEL_OAUTH_CLIENT_SECRET",
        "PANEL_COOKIE_SECRET",
        "PANEL_BASE_URL",
        "TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    config = config_loader.load_config()
    leaked = sorted(
        k
        for k in ("PANEL_OAUTH_CLIENT_ID", "PANEL_OAUTH_CLIENT_SECRET", "PANEL_COOKIE_SECRET", "TOKEN")
        if config.get(k)
    )
    if leaked:
        pytest.fail(f"load_config() carregou valores de um .env real para: {leaked}", pytrace=False)


def test_a_test_can_still_provide_its_own_dot_env(monkeypatch, tmp_path):
    import empiremuse.config_loader as config_loader
    import dotenv

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PANEL_BASE_URL='https://teste.invalid'\n", encoding="utf-8")
    monkeypatch.delenv("PANEL_BASE_URL", raising=False)
    monkeypatch.setattr(config_loader, "dotenv_values", lambda *a, **k: dotenv.dotenv_values(tmp_path / ".env"))
    assert config_loader.load_config()["PANEL_BASE_URL"] == "https://teste.invalid"

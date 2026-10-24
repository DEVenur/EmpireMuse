"""Guarda de isolamento: a suíte nunca lê o .env/config.json REAIS do desenvolvedor.

Se este arquivo falhar, algum teste voltou a depender do ambiente da máquina (resultado não determinístico e risco de
segredos aparecerem na saída). As mensagens de falha NÃO imprimem valores de configuração.
"""

import pytest


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

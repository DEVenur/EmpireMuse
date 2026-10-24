"""Padrões seguros do RPC: servidor desligado e autenticação por token ligada, no código e no ``.example.env``.

Sem rede, sem ``.env`` real (o ``conftest`` neutraliza o ``dotenv_values``) e com ``EMPIREMUSE_HOME`` em ``tmp_path``.
"""

import re

import pytest

from empiremuse import config_loader
from tests.support.raiz import RAIZ

EXAMPLE_ENV = RAIZ / ".example.env"


@pytest.fixture
def config_padrao(monkeypatch, tmp_path):
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.chdir(cwd)
    for chave in ("RUN_RPC_SERVER", "ENABLE_RPC_AUTH"):
        monkeypatch.delenv(chave, raising=False)
    return config_loader.load_config()


@pytest.mark.smoke
def test_autenticacao_do_rpc_vem_ligada_por_padrao(config_padrao):
    assert config_padrao["ENABLE_RPC_AUTH"] is True


@pytest.mark.parametrize(("chave", "valor"), [("RUN_RPC_SERVER", "false"), ("ENABLE_RPC_AUTH", "true")])
def test_example_env_acompanha_os_padroes_do_codigo(chave, valor):
    achado = re.search(rf"^{chave}=(\S+)$", EXAMPLE_ENV.read_text(encoding="utf-8"), re.MULTILINE)

    assert achado is not None, f"{chave} sumiu do .example.env"
    assert achado.group(1) == valor

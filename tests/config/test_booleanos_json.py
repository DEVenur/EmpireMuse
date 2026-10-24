"""``config.json`` com ``true``/``false`` nativos do JSON (não texto) vale como escrito, não vira o padrão.

``CONFIG[i] in (True, False, None, "")`` mandava para o padrão qualquer booleano nativo: ``ENABLE_RPC_AUTH: false`` no
``config.json`` virava ``True`` (o padrão seguro). Pelo ambiente e pelo ``.env`` o valor chega como texto e já funcionava,
e é o oráculo aqui. Os inteiros nativos (inclusive ``0``) já eram respeitados: ver ``test_zero_inteiro.py``.
"""

import json

import pytest

from empiremuse import config_loader

pytestmark = pytest.mark.critical


@pytest.fixture
def home(monkeypatch, tmp_path):
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.chdir(cwd)
    return pasta


def pelo_config_json(home, chave, valor):
    (home / "config.json").write_text(json.dumps({chave: valor}), encoding="utf-8")
    return config_loader.load_config()[chave]


@pytest.mark.smoke
def test_true_nativo_contra_padrao_false(home):
    assert config_loader.DEFAULT_CONFIG["RUN_RPC_SERVER"] is False
    assert pelo_config_json(home, "RUN_RPC_SERVER", True) is True


@pytest.mark.smoke
@pytest.mark.parametrize("vazio", ["", None])
def test_ausente_ou_vazio_continua_usando_o_padrao(home, vazio):
    assert pelo_config_json(home, "ENABLE_RPC_AUTH", vazio) is config_loader.DEFAULT_CONFIG["ENABLE_RPC_AUTH"]


def test_a_lista_de_booleanos_inteira_aceita_o_nativo(home):
    chaves = [k for k, v in config_loader.DEFAULT_CONFIG.items() if isinstance(v, bool) and k.isupper()]
    (home / "config.json").write_text(json.dumps({k: not config_loader.DEFAULT_CONFIG[k] for k in chaves}))

    config = config_loader.load_config()

    convertidas = {k for k in chaves if config[k] is (not config_loader.DEFAULT_CONFIG[k])}
    assert {"ENABLE_RPC_AUTH", "RUN_RPC_SERVER", "PANEL_ENABLED", "MEMBERS_INTENT"} <= convertidas


def test_enable_rpc_auth_none_nao_desliga_a_autenticacao(home):
    assert pelo_config_json(home, "ENABLE_RPC_AUTH", "none") is True

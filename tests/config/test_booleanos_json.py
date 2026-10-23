"""``config.json`` com ``true``/``false`` nativos do JSON (não texto) vale como escrito, não vira o padrão.

``CONFIG[i] in (True, False, None, "")`` mandava para o padrão qualquer booleano nativo: ``ENABLE_RPC_AUTH: false`` no
``config.json`` virava ``True`` (o padrão seguro). Pelo ambiente e pelo ``.env`` o valor chega como texto e já funcionava,
e é o oráculo aqui. Os inteiros nativos (inclusive ``0``) já eram respeitados: ver ``test_zero_inteiro.py``.
"""

import json

import pytest

from empiremuse import config_loader


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


def test_o_exemplo_do_bug_auth_false_no_config_json_nao_vira_true(home):
    assert config_loader.DEFAULT_CONFIG["ENABLE_RPC_AUTH"] is True
    assert pelo_config_json(home, "ENABLE_RPC_AUTH", False) is False


def test_true_nativo_contra_padrao_false(home):
    assert config_loader.DEFAULT_CONFIG["RUN_RPC_SERVER"] is False
    assert pelo_config_json(home, "RUN_RPC_SERVER", True) is True


@pytest.mark.parametrize("valor", [True, False])
@pytest.mark.parametrize(
    "chave", ["RUN_RPC_SERVER", "ENABLE_RPC_AUTH", "PANEL_ENABLED", "ENABLE_LOGGER", "MEMBERS_INTENT"]
)
def test_booleano_nativo_igual_ao_texto_do_ambiente(home, monkeypatch, chave, valor):
    pelo_json = pelo_config_json(home, chave, valor)
    (home / "config.json").unlink()
    monkeypatch.setenv(chave, str(valor).lower())

    assert pelo_json is valor
    assert config_loader.load_config()[chave] is valor


@pytest.mark.parametrize("vazio", ["", None])
def test_ausente_ou_vazio_continua_usando_o_padrao(home, vazio):
    assert pelo_config_json(home, "ENABLE_RPC_AUTH", vazio) is config_loader.DEFAULT_CONFIG["ENABLE_RPC_AUTH"]


def test_texto_invalido_continua_dando_erro(home):
    with pytest.raises(Exception, match="ENABLE_RPC_AUTH"):
        pelo_config_json(home, "ENABLE_RPC_AUTH", "talvez")


def test_a_lista_de_booleanos_inteira_aceita_o_nativo(home):
    chaves = [k for k, v in config_loader.DEFAULT_CONFIG.items() if isinstance(v, bool) and k.isupper()]
    (home / "config.json").write_text(json.dumps({k: not config_loader.DEFAULT_CONFIG[k] for k in chaves}))

    config = config_loader.load_config()

    convertidas = {k for k in chaves if config[k] is (not config_loader.DEFAULT_CONFIG[k])}
    assert {"ENABLE_RPC_AUTH", "RUN_RPC_SERVER", "PANEL_ENABLED", "MEMBERS_INTENT"} <= convertidas


@pytest.mark.parametrize("texto", ["none", "None", "NONE"])
@pytest.mark.parametrize("chave", ["ENABLE_RPC_AUTH", "RUN_RPC_SERVER", "PANEL_ENABLED", "MEMBERS_INTENT"])
def test_none_em_chave_booleana_e_ausente_e_vale_o_padrao(home, monkeypatch, chave, texto):
    padrao = config_loader.DEFAULT_CONFIG[chave]

    assert pelo_config_json(home, chave, texto) is padrao
    (home / "config.json").unlink()
    monkeypatch.setenv(chave, texto)
    assert config_loader.load_config()[chave] is padrao


def test_enable_rpc_auth_none_nao_desliga_a_autenticacao(home):
    assert pelo_config_json(home, "ENABLE_RPC_AUTH", "none") is True

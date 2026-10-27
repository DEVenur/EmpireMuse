"""A26 (item 18, P4) — ``UPDATE_PROXY_SOCKET``: vazio (padrão) ou caminho absoluto; qualquer outra coisa vira vazio com um aviso sem o valor.

Sem rede, sem ``.env`` real e com ``EMPIREMUSE_HOME`` em ``tmp_path``.
"""

import json
import logging

import pytest

from empiremuse import config_loader

pytestmark = pytest.mark.critical

CHAVE = "UPDATE_PROXY_SOCKET"


@pytest.fixture
def home(monkeypatch, tmp_path):
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.delenv(CHAVE, raising=False)
    monkeypatch.chdir(cwd)
    return pasta


def carregar(home, valor) -> dict:
    (home / "config.json").write_text(json.dumps({CHAVE: valor}), encoding="utf-8")
    return config_loader.load_config()


def test_the_default_is_empty_and_does_not_warn(home, caplog):
    with caplog.at_level(logging.WARNING):
        config = config_loader.load_config()

    assert config[CHAVE] == "" and CHAVE not in caplog.text


@pytest.mark.parametrize(
    ("informado", "esperado"),
    [("/run/empiremuse/updater.sock", "/run/empiremuse/updater.sock"), ("  /run/x.sock  ", "/run/x.sock"), ("", "")],
    ids=["absoluto", "espacos-nas-pontas", "vazio"],
)
def test_an_empty_or_absolute_path_is_kept_without_the_surrounding_spaces(home, caplog, informado, esperado):
    with caplog.at_level(logging.WARNING):
        config = carregar(home, informado)

    assert config[CHAVE] == esperado and CHAVE not in caplog.text


@pytest.mark.parametrize("informado", ["updater.sock", "./updater.sock", "../run/x.sock", 123, ["/run/x.sock"], True])
def test_a_relative_or_non_string_value_becomes_empty_with_a_warning_that_hides_the_value(home, caplog, informado):
    with caplog.at_level(logging.WARNING):
        config = carregar(home, informado)

    assert config[CHAVE] == ""
    assert CHAVE in caplog.text and "updater.sock" not in caplog.text and "x.sock" not in caplog.text


def test_the_environment_variable_follows_the_same_rule(home, monkeypatch, caplog):
    monkeypatch.setenv(CHAVE, "relativo.sock")

    with caplog.at_level(logging.WARNING):
        config = config_loader.load_config()

    assert config[CHAVE] == "" and "relativo.sock" not in caplog.text

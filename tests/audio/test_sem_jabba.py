"""S-27 — o caminho do jabba (script ``install.sh`` baixado do ``master`` e executado) deixou de existir.

O JDK vem só do pacote com SHA-256 fixo (``_install_jdk_linux``/``_install_jdk_windows``). A chave ``USE_JABBA``, se
ainda estiver no ``.env``, é ignorada sem erro.
"""

import inspect

import pytest

from empiremuse import config_loader
from empiremuse.utils.music import local_lavalink as ll
from tests.support.raiz import RAIZ


def test_as_funcoes_do_java_nao_aceitam_mais_use_jabba():
    assert "use_jabba" not in inspect.signature(ll.run_lavalink).parameters
    assert "use_jabba" not in inspect.signature(ll._find_or_install_java).parameters
    assert "use_jabba" not in inspect.signature(ll._install_jdk).parameters


def test_nenhum_script_externo_e_baixado_ou_executado_pelo_modulo():
    fonte = inspect.getsource(ll)

    assert "shyiko" not in fonte
    assert "install_jabba" not in fonte
    assert "jabba install" not in fonte


def test_use_jabba_saiu_da_configuracao_e_do_example_env():
    assert "USE_JABBA" not in config_loader.DEFAULT_CONFIG
    assert "USE_JABBA" not in (RAIZ / ".example.env").read_text(encoding="utf-8")


def test_use_jabba_antigo_no_ambiente_e_ignorado_sem_erro(monkeypatch, tmp_path):
    for nome in ("home", "cwd"):
        (tmp_path / nome).mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "cwd")
    (tmp_path / "home" / "config.json").write_text('{"USE_JABBA": "true"}', encoding="utf-8")

    config = config_loader.load_config()

    assert config["RUN_LOCAL_LAVALINK"] is False


@pytest.mark.parametrize("sistema", ["posix"])
def test_o_jdk_no_linux_so_passa_pelo_pacote_verificado(monkeypatch, sistema):
    chamadas = []
    monkeypatch.setattr(ll.os, "name", sistema)
    monkeypatch.setattr(ll, "_install_jdk_linux", lambda *args: chamadas.append(args) or "/jdk/bin/java")
    monkeypatch.setattr(ll.subprocess, "call", lambda *a, **k: pytest.fail("não pode executar script"))
    monkeypatch.setattr(ll, "download_file", lambda *a, **k: pytest.fail("não pode baixar script"))

    assert ll._install_jdk("/tmp/x", "Linux-64bit-ELF", "64bit") == "/jdk/bin/java"
    assert chamadas == [("/tmp/x", "Linux-64bit-ELF", "64bit")]

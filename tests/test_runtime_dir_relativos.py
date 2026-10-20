"""F3-7 — dados de execução nunca dependem do cwd: tudo parte de ``paths.RUNTIME_DIR``.

``enter_runtime_dir`` já leva o cwd para o ``RUNTIME_DIR``, mas quem lê ou grava por caminho relativo só funciona se o
processo entrou por ``main()``. Estes testes fixam o caminho absoluto em cada ponto que sobrou
(``guild_bots.json``, ``install_jabba.sh`` e o padrão ``directory="."`` do ``prepare_lavalink_files``) e uma guarda
estática contra novos acessos relativos. Cada teste tem o ``EMPIREMUSE_HOME`` e o cwd em pastas diferentes do ``tmp_path``.
"""

import ast
import json
import os
from pathlib import Path

import pytest

from empiremuse import paths
from empiremuse.utils import client
from empiremuse.utils.music import local_lavalink

PACOTE = Path(paths.PACKAGE_DIR)


@pytest.fixture
def home_e_cwd(monkeypatch, tmp_path):
    """``EMPIREMUSE_HOME`` e cwd em pastas distintas: o que for relativo cai fora do RUNTIME_DIR."""
    home = (tmp_path / "home").resolve()
    cwd = (tmp_path / "cwd").resolve()
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    return home, cwd


class TestGuildBots:
    def test_le_o_guild_bots_json_do_runtime_dir_e_nao_do_cwd(self, home_e_cwd):
        home, cwd = home_e_cwd
        (home / "guild_bots.json").write_text(json.dumps({"111": ["token-a", "token-b"]}), encoding="utf-8")
        (cwd / "guild_bots.json").write_text(json.dumps({"999": ["token-do-cwd"]}), encoding="utf-8")

        assert client.read_guild_bots() == {"111": ["token-a", "token-b"]}

    def test_arquivo_ausente_no_runtime_dir_devolve_vazio_mesmo_com_um_no_cwd(self, home_e_cwd):
        _, cwd = home_e_cwd
        (cwd / "guild_bots.json").write_text(json.dumps({"999": ["token-do-cwd"]}), encoding="utf-8")

        assert client.read_guild_bots() == {}

    def test_json_invalido_devolve_vazio_sem_derrubar_o_boot(self, home_e_cwd, capsys):
        home, _ = home_e_cwd
        (home / "guild_bots.json").write_text("{não é json", encoding="utf-8")

        assert client.read_guild_bots() == {}


class TestJabba:
    @pytest.fixture
    def instalacao(self, monkeypatch, home_e_cwd):
        chamadas = {"download": [], "subprocess": [], "remove": []}
        monkeypatch.setattr(
            local_lavalink, "download_file", lambda url, filename: chamadas["download"].append(filename)
        )
        monkeypatch.setattr(
            local_lavalink.subprocess, "call", lambda cmd, **kw: chamadas["subprocess"].append(cmd) or 0
        )
        monkeypatch.setattr(local_lavalink.os, "remove", lambda caminho: chamadas["remove"].append(str(caminho)))
        monkeypatch.setattr(local_lavalink.os, "name", "posix")
        return chamadas

    def test_o_script_do_jabba_e_baixado_e_removido_no_runtime_dir(self, instalacao, home_e_cwd):
        home, _ = home_e_cwd

        local_lavalink._install_jdk(str(home), "Linux-64bit-ELF", "64bit", use_jabba=True)

        script = str(home / "install_jabba.sh")
        assert instalacao["download"] == [script]
        assert instalacao["remove"] == [script]

    def test_o_bash_executa_o_script_pelo_caminho_absoluto(self, instalacao, home_e_cwd):
        home, _ = home_e_cwd

        local_lavalink._install_jdk(str(home), "Linux-64bit-ELF", "64bit", use_jabba=True)

        comandos_bash = [c for c in instalacao["subprocess"] if "install_jabba.sh" in str(c)]
        assert len(comandos_bash) == 1
        assert str(home / "install_jabba.sh") in str(comandos_bash[0])


class TestPrepareLavalinkFilesPadrao:
    def test_sem_directory_usa_o_runtime_dir_e_nao_o_cwd(self, monkeypatch, home_e_cwd):
        home, _ = home_e_cwd
        recebidos = []
        monkeypatch.setattr(
            local_lavalink, "_verify_preinstalled_files", lambda directory, *a: recebidos.append(directory)
        )

        local_lavalink.prepare_lavalink_files(lavalink_offline=True)

        assert recebidos == [str(home)]


# Funções que abrem, criam ou removem caminhos no disco. ``Path`` e ``os.path.*`` entram pelo primeiro argumento.
FUNCOES_DE_ARQUIVO = {"open", "Path"}
FUNCOES_DE_OS = {"remove", "unlink", "makedirs", "mkdir", "rmdir", "rename", "replace", "listdir", "scandir", "walk"}
FUNCOES_DE_OS_PATH = {"isfile", "isdir", "exists", "getsize", "abspath", "realpath"}
FUNCOES_DE_SHUTIL = {"rmtree", "copyfile", "copy", "move"}


def _nome_da_chamada(no: ast.Call) -> str | None:
    funcao = no.func
    if isinstance(funcao, ast.Name) and funcao.id in FUNCOES_DE_ARQUIVO:
        return funcao.id
    if not isinstance(funcao, ast.Attribute):
        return None
    base = funcao.value
    if isinstance(base, ast.Name) and base.id == "os" and funcao.attr in FUNCOES_DE_OS:
        return f"os.{funcao.attr}"
    if isinstance(base, ast.Name) and base.id == "shutil" and funcao.attr in FUNCOES_DE_SHUTIL:
        return f"shutil.{funcao.attr}"
    if (
        isinstance(base, ast.Attribute)
        and isinstance(base.value, ast.Name)
        and (base.value.id, base.attr) == ("os", "path")
        and funcao.attr in FUNCOES_DE_OS_PATH
    ):
        return f"os.path.{funcao.attr}"
    return None


class TestGuardaEstatica:
    def test_nenhum_acesso_a_arquivo_com_literal_relativo_no_pacote(self):
        """``open("x.json")``, ``os.remove("x.sh")`` e afins dependem do cwd; use ``paths.RUNTIME_DIR / "x"``.

        Literais absolutos (``/proc/...``) não entram na conta.
        """
        achados = []
        for arquivo in sorted(PACOTE.rglob("*.py")):
            for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
                if not isinstance(no, ast.Call) or not no.args:
                    continue
                nome = _nome_da_chamada(no)
                primeiro = no.args[0]
                if nome and isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
                    if primeiro.value and not os.path.isabs(primeiro.value):
                        achados.append(f"{arquivo.relative_to(PACOTE.parent)}:{no.lineno} {nome}({primeiro.value!r})")
        assert not achados, f"acessos a arquivo relativos ao cwd: {achados}"

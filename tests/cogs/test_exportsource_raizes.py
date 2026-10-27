"""S-29 (ampliação) — raízes permitidas do ``source.zip``: ``PROJECT_DIR`` E a ``RUNTIME_DIR`` resolvidas.

Layout Docker/Pterodactyl: ``PROJECT_DIR=<tmp>/app`` e ``RUNTIME_DIR=<tmp>/data`` (cwd do processo). O que está em ``data/`` entra no zip
(``local_database``, ``lavalink.ini``, ``application.yml``, ``discloud.config``); link que resolve para fora das DUAS raízes segue recusado e
os nomes secretos seguem recusados também em ``data/``. Tudo em pastas do ``tmp_path``.
"""

import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs.legacy_cmds import Owner

pytestmark = pytest.mark.critical

SEGREDO = "SEGREDO-REAL-123"
FORA = "CONTEUDO-DE-FORA-123"
ENV_MASCARADO = "TOKEN=\nPREFIX=!\n"
NOMES_SECRETOS = [".env", "config.json", ".ytdl_cookie", ".spotify_cache.json", "guild_bots.json"]
DO_DATA = {
    "local_database/x.json": '{"x": 1}',
    "lavalink.ini": "[lavalink]\n",
    "application.yml": "server:\n",
    "discloud.config": "NAME=bot\n",
}


@pytest.fixture
def docker(monkeypatch, tmp_path):
    """``app/`` (código) e ``data/`` (runtime) irmãs, mais ``fora/`` que não pertence a nenhuma das duas."""
    app, data, fora = tmp_path / "app", tmp_path / "data", tmp_path / "fora"
    for pasta in (app, data / "local_database", fora / "pasta"):
        pasta.mkdir(parents=True)
    (app / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (fora / "segredo.txt").write_text(FORA, encoding="utf-8")
    (fora / "pasta" / "x.txt").write_text(FORA, encoding="utf-8")
    for nome, texto in DO_DATA.items():
        (data / nome).write_text(texto, encoding="utf-8")
    for nome in NOMES_SECRETOS:
        (data / nome).write_text(f"{nome}={SEGREDO}", encoding="utf-8")
    (data / ".env-temp").write_text(ENV_MASCARADO, encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", app.resolve())
    monkeypatch.setenv("EMPIREMUSE_HOME", str(data))  # ``paths.RUNTIME_DIR`` é dinâmico: lê a variável a cada acesso
    assert paths.RUNTIME_DIR.resolve() == data.resolve()
    monkeypatch.chdir(data)
    return type("Docker", (), {"app": app, "data": data, "fora": fora})


def zipar(lista: list[str]) -> dict[str, str]:
    Owner.zip_dir(lista)
    with ZipFile(Path(os.environ["EMPIREMUSE_HOME"]) / "source.zip") as pacote:
        nomes = pacote.namelist()
        assert len(nomes) == len(set(nomes)), f"entradas duplicadas no zip: {nomes}"
        return {nome: pacote.read(nome).decode("utf-8", "replace") for nome in nomes}


def assert_sem_vazamento(entradas: dict[str, str]) -> None:
    assert not [n for n, t in entradas.items() if SEGREDO in t], "segredo real no zip"
    assert not [n for n, t in entradas.items() if FORA in t], "conteúdo de fora das raízes no zip"
    assert ".env-temp" not in entradas
    if ".env" in entradas:
        assert entradas[".env"] == ENV_MASCARADO


class TestArquivosDoRuntimeEntram:
    @pytest.mark.parametrize("nome", list(DO_DATA))
    def test_arquivo_do_data_entra_no_zip(self, docker, nome):
        entradas = zipar([nome, "../app/ok.py"])

        assert entradas[nome] == DO_DATA[nome]

    def test_todos_juntos_com_o_env_mascarado(self, docker):
        entradas = zipar([*DO_DATA, ".env-temp"])

        assert {n: entradas[n] for n in DO_DATA} == DO_DATA
        assert entradas[".env"] == ENV_MASCARADO
        assert_sem_vazamento(entradas)

    def test_caminho_absoluto_de_arquivo_do_data_entra(self, docker):
        entradas = zipar([str(docker.data / "lavalink.ini")])

        assert list(entradas.values()) == [DO_DATA["lavalink.ini"]]

    def test_arquivo_do_projeto_continua_entrando(self, docker):
        entradas = zipar([str(docker.app / "ok.py")])

        assert list(entradas.values()) == ["print('ok')\n"]


class TestLinksNoData:
    def test_link_do_data_para_dentro_do_app_entra(self, docker):
        (docker.data / "para_app.txt").symlink_to(docker.app / "ok.py")

        entradas = zipar(["para_app.txt"])

        assert entradas == {"para_app.txt": "print('ok')\n"}

    def test_link_do_data_para_dentro_do_proprio_data_entra(self, docker):
        (docker.data / "para_data.ini").symlink_to(docker.data / "lavalink.ini")

        entradas = zipar(["para_data.ini"])

        assert entradas == {"para_data.ini": DO_DATA["lavalink.ini"]}

    def test_link_do_data_para_fora_das_duas_raizes_nao_entra(self, docker):
        (docker.data / "fora.txt").symlink_to(docker.fora / "segredo.txt")

        entradas = zipar(["fora.txt", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]

    def test_link_de_diretorio_do_data_para_fora_nao_leva_os_filhos(self, docker):
        (docker.data / "dir_fora").symlink_to(docker.fora / "pasta", target_is_directory=True)

        entradas = zipar(["dir_fora/x.txt", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]

    def test_link_do_app_para_fora_continua_recusado(self, docker):
        (docker.app / "fora.txt").symlink_to(docker.fora / "segredo.txt")

        entradas = zipar([str(docker.app / "fora.txt"), "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]

    def test_link_do_data_para_um_segredo_do_data_nao_entra(self, docker):
        (docker.data / "apelido.txt").symlink_to(docker.data / "config.json")

        entradas = zipar(["apelido.txt", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]


class TestForaDasRaizes:
    def test_caminho_absoluto_de_fora_nao_entra(self, docker):
        entradas = zipar([str(docker.fora / "segredo.txt"), "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]

    def test_caminho_relativo_com_pontos_para_fora_nao_entra(self, docker):
        entradas = zipar(["../fora/segredo.txt", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]

    def test_pasta_irma_com_prefixo_parecido_nao_conta_como_raiz(self, docker, tmp_path):
        parecida = tmp_path / "data-outro"
        parecida.mkdir()
        (parecida / "x.txt").write_text(FORA, encoding="utf-8")

        entradas = zipar([str(parecida / "x.txt"), "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert list(entradas) == ["lavalink.ini"]


class TestSegredosSeguemRecusadosNoData:
    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    def test_nome_secreto_relativo_nao_entra(self, docker, nome):
        entradas = zipar([nome, "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert nome not in entradas or (nome == ".env" and entradas[nome] == ENV_MASCARADO)
        assert "lavalink.ini" in entradas

    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    def test_nome_secreto_por_caminho_absoluto_nao_entra(self, docker, nome):
        entradas = zipar([str(docker.data / nome), "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert not [n for n in entradas if os.path.basename(n) == nome]

    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    def test_nome_secreto_em_subpasta_do_data_nao_entra(self, docker, nome):
        (docker.data / "local_database" / nome).write_text(SEGREDO, encoding="utf-8")

        entradas = zipar([f"local_database/{nome}", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert not [n for n in entradas if os.path.basename(n) == nome]

    def test_nome_secreto_com_caixa_diferente_nao_entra(self, docker):
        (docker.data / "Config.JSON").write_text(SEGREDO, encoding="utf-8")

        entradas = zipar(["Config.JSON", "lavalink.ini"])

        assert_sem_vazamento(entradas)
        assert "Config.JSON" not in entradas

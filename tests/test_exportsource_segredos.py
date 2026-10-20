"""F3-7 (AppSec A1) — o ``zip_dir`` do ``exportsource`` nunca leva segredo nem nada da ``.runtime/``.

O ``exportsource`` monta a lista de arquivos com ``git ls-files --others --exclude-standard --cached`` e grava cada nome,
relativo ao cwd, no ``source.zip`` enviado por DM. Com o cwd na ``.runtime/`` de desenvolvimento e um ``GIT_DIR`` fora
dela, o git trata o cwd como árvore de trabalho, o ``.gitignore`` da raiz deixa de valer e a lista traz o ``.env`` e o
``config.json`` reais. A defesa em profundidade é do ``zip_dir``: recusar esses nomes MESMO QUE a lista do git os traga.

Tudo roda em pastas e repositórios git descartáveis do ``tmp_path``; o repositório real nunca é tocado.
"""

import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs.legacy_cmds import Owner

SEGREDO = "SEGREDO-REAL-123"
ENV_MASCARADO = "TOKEN=\nPREFIX=!\n"
NOMES_SECRETOS = [".env", "config.json", ".ytdl_cookie", ".spotify_cache.json", "guild_bots.json"]


@pytest.fixture
def projeto(monkeypatch, tmp_path):
    """Projeto descartável com uma ``.runtime/`` cheia de segredos reais; o cwd é a ``.runtime/``."""
    raiz = tmp_path / "projeto"
    runtime = raiz / ".runtime"
    (runtime / "local_database").mkdir(parents=True)
    (runtime / "sub").mkdir()
    for nome in NOMES_SECRETOS:
        (runtime / nome).write_text(f"{nome}={SEGREDO}", encoding="utf-8")
    (runtime / "local_database" / "d.json").write_text(SEGREDO, encoding="utf-8")
    (runtime / ".env-temp").write_text(ENV_MASCARADO, encoding="utf-8")
    (runtime / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz.resolve())  # a regra é por PROJECT_DIR/.runtime
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    monkeypatch.chdir(runtime)
    return raiz


def zipar(lista: list[str]) -> dict[str, str]:
    """Roda o ``zip_dir`` real e devolve ``{nome: conteúdo}`` do ``source.zip``; nomes repetidos falham o teste."""
    Owner.zip_dir(None, lista)
    with ZipFile(Path(os.environ["EMPIREMUSE_HOME"]) / "source.zip") as pacote:
        nomes = pacote.namelist()
        assert len(nomes) == len(set(nomes)), f"entradas duplicadas no zip: {nomes}"
        return {nome: pacote.read(nome).decode("utf-8", "replace") for nome in nomes}


def assert_sem_segredo(entradas: dict[str, str]) -> None:
    vazaram = sorted(nome for nome, texto in entradas.items() if SEGREDO in texto)
    assert not vazaram, f"o zip leva conteúdo real de: {vazaram}"
    assert ".env-temp" not in entradas, "o .env-temp não pode aparecer com o próprio nome"
    if ".env" in entradas:
        assert entradas[".env"] == ENV_MASCARADO, "o único .env permitido é o mascarado (.env-temp)"


class TestNomesSecretos:
    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    def test_nome_secreto_listado_nao_entra_no_zip(self, projeto, nome):
        entradas = zipar([nome, "ok.py"])

        assert_sem_segredo(entradas)
        assert nome not in entradas

    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    @pytest.mark.parametrize("forma", ["./{}", ".//{}", "sub/../{}"])
    def test_nome_secreto_com_caminho_disfarcado_nao_entra(self, projeto, nome, forma):
        entradas = zipar([forma.format(nome), "ok.py"])

        assert_sem_segredo(entradas)
        assert set(entradas) <= {"ok.py", ".env"}

    @pytest.mark.parametrize("nome", NOMES_SECRETOS)
    def test_nome_secreto_por_caminho_absoluto_nao_entra(self, projeto, nome):
        entradas = zipar([os.path.join(os.getcwd(), nome), "ok.py"])

        assert_sem_segredo(entradas)
        assert not [n for n in entradas if os.path.basename(n) in NOMES_SECRETOS and n != ".env"]

    def test_local_database_nao_entra(self, projeto):
        entradas = zipar(["local_database/d.json", "ok.py"])

        assert_sem_segredo(entradas)
        assert not [nome for nome in entradas if nome.startswith("local_database")]


class TestEnvMascarado:
    def test_env_temp_nunca_aparece_com_o_proprio_nome(self, projeto):
        entradas = zipar([".env-temp", "ok.py"])

        assert_sem_segredo(entradas)

    def test_env_real_e_env_temp_juntos_dao_um_unico_env_mascarado(self, projeto):
        entradas = zipar([".env", ".env-temp", "ok.py"])

        assert_sem_segredo(entradas)
        assert list(entradas).count(".env") <= 1


class TestPastaRuntime:
    """Lista vinda de um cwd na RAIZ do projeto, com nomes que passam pela ``.runtime/``."""

    @pytest.fixture
    def da_raiz(self, projeto, monkeypatch):
        monkeypatch.chdir(projeto)
        return projeto

    @pytest.mark.parametrize(
        "nome",
        [
            ".runtime/.env",
            ".runtime/config.json",
            ".runtime/guild_bots.json",
            ".runtime/local_database/d.json",
            ".runtime/ok.py",
            "./.runtime/config.json",
            ".runtime//.spotify_cache.json",
            "x/../.runtime/.ytdl_cookie",
        ],
    )
    def test_nada_dentro_da_runtime_entra_no_zip(self, da_raiz, nome):
        (da_raiz / "x").mkdir(exist_ok=True)
        (da_raiz / "ok_raiz.py").write_text("print('raiz')\n", encoding="utf-8")

        entradas = zipar([nome, "ok_raiz.py"])

        assert entradas == {"ok_raiz.py": "print('raiz')\n"}

    def test_a_propria_pasta_runtime_listada_nao_leva_o_conteudo(self, da_raiz):
        entradas = zipar([".runtime", "."])

        assert_sem_segredo(entradas)
        assert not [nome for nome in entradas if nome.startswith(".runtime")]


@pytest.mark.skipif(shutil.which("git") is None, reason="git indisponível")
class TestListaRealDoGitComGitDirForaDaRuntime:
    """O cenário do achado A1, com git de verdade em repositório descartável."""

    @staticmethod
    def _git(argumentos, cwd, **ambiente):
        base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        base.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, **ambiente)
        return subprocess.run(
            ["git", *argumentos], cwd=cwd, env=base, check=True, capture_output=True, text=True
        ).stdout

    def test_lista_do_git_com_cwd_na_runtime_nao_vaza_pelo_zip(self, projeto):
        self._git(["init", "-q"], projeto)
        (projeto / ".gitignore").write_text(".env*\nconfig.json\n.runtime\n", encoding="utf-8")
        (projeto / "empiremuse").mkdir()
        (projeto / "empiremuse" / "a.py").write_text("a = 1\n", encoding="utf-8")
        self._git(["add", ".gitignore", "empiremuse/a.py"], projeto)
        self._git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], projeto)

        lista = self._git(
            ["ls-files", "--others", "--exclude-standard", "--cached"],
            os.getcwd(),  # a .runtime/
            GIT_DIR=str(projeto / ".git"),
        ).split("\n")
        assert ".env" in lista and "config.json" in lista, (
            "o cenário A1 deixou de listar os segredos: o teste não prova nada"
        )

        entradas = zipar(lista)

        assert_sem_segredo(entradas)
        assert not [nome for nome in entradas if os.path.basename(nome) in NOMES_SECRETOS and nome != ".env"]
        assert not [nome for nome in entradas if nome.startswith("local_database")]

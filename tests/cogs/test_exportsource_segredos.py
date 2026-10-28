"""F3-7 (AppSec A1) — o ``zip_dir`` do ``exportsource`` nunca leva segredo nem nada da ``.runtime/``.

O ``exportsource`` monta a lista de arquivos com ``git ls-files --others --exclude-standard --cached`` e grava cada nome,
relativo ao cwd, no ``source.zip`` enviado por DM. Com o cwd na ``.runtime/`` de desenvolvimento e um ``GIT_DIR`` fora
dela, o git trata o cwd como árvore de trabalho, o ``.gitignore`` da raiz deixa de valer e a lista traz o ``.env`` e o
``config.json`` reais. A defesa em profundidade é do ``zip_dir``: recusar esses nomes MESMO QUE a lista do git os traga.

Tudo roda em pastas e repositórios git descartáveis do ``tmp_path``; o repositório real nunca é tocado.
"""

import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs.legacy_cmds import Owner

pytestmark = pytest.mark.critical

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
    Owner.zip_dir(lista)
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
    @pytest.mark.smoke
    @pytest.mark.parametrize("nome", list(NOMES_SECRETOS)[:2])
    def test_nome_secreto_listado_nao_entra_no_zip(self, projeto, nome):
        entradas = zipar([nome, "ok.py"])

        assert_sem_segredo(entradas)
        assert nome not in entradas

    @pytest.mark.parametrize("nome", list(NOMES_SECRETOS)[:2])
    def test_nome_secreto_por_caminho_absoluto_nao_entra(self, projeto, nome):
        entradas = zipar([os.path.join(os.getcwd(), nome), "ok.py"])

        assert_sem_segredo(entradas)
        assert not [n for n in entradas if os.path.basename(n) in NOMES_SECRETOS and n != ".env"]


class TestEnvMascarado:
    def test_env_temp_nunca_aparece_com_o_proprio_nome(self, projeto):
        entradas = zipar([".env-temp", "ok.py"])

        assert_sem_segredo(entradas)


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
            "x/../.runtime/.ytdl_cookie",
        ],
    )
    def test_nada_dentro_da_runtime_entra_no_zip(self, da_raiz, nome):
        (da_raiz / "x").mkdir(exist_ok=True)
        (da_raiz / "ok_raiz.py").write_text("print('raiz')\n", encoding="utf-8")

        entradas = zipar([nome, "ok_raiz.py"])

        assert entradas == {"ok_raiz.py": "print('raiz')\n"}

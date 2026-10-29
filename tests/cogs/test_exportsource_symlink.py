"""S-29 — o ``zip_dir`` do ``exportsource`` nunca leva arquivo cujo caminho resolvido sai do ``PROJECT_DIR``.

Um symlink rastreado (arquivo, ou diretório pai) que aponta para fora do projeto faria o ``ZipFile.write`` seguir o
link e gravar no ``source.zip`` enviado por DM o conteúdo de um arquivo qualquer da máquina. A defesa é do ``zip_dir``:
pular o que resolve para fora da raiz, mesmo que a lista do git o traga. Links que ficam dentro do projeto continuam.

Tudo roda em pastas descartáveis do ``tmp_path``.
"""

import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs.legacy_cmds import Owner

pytestmark = pytest.mark.critical

FORA = "CONTEUDO-DE-FORA-123"
ENV_MASCARADO = "TOKEN=\nPREFIX=!\n"


@pytest.fixture
def projeto(monkeypatch, tmp_path):
    """Projeto descartável (cwd na raiz) e uma pasta ``fora`` irmã, com conteúdo que não pode vazar."""
    raiz = tmp_path / "projeto"
    runtime = raiz / ".runtime"
    runtime.mkdir(parents=True)
    (runtime / ".env-temp").write_text(ENV_MASCARADO, encoding="utf-8")
    (raiz / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (raiz / "dentro").mkdir()
    (raiz / "dentro" / "real.txt").write_text("dentro\n", encoding="utf-8")
    fora = tmp_path / "fora"
    (fora / "pasta").mkdir(parents=True)
    (fora / "segredo.txt").write_text(FORA, encoding="utf-8")
    (fora / "pasta" / "x.txt").write_text(FORA, encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz.resolve())
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    monkeypatch.chdir(raiz)
    return raiz


def zipar(lista: list[str]) -> dict[str, str]:
    Owner.zip_dir(lista)
    with ZipFile(Path(os.environ["EMPIREMUSE_HOME"]) / "source.zip") as pacote:
        nomes = pacote.namelist()
        assert len(nomes) == len(set(nomes)), f"entradas duplicadas no zip: {nomes}"
        return {nome: pacote.read(nome).decode("utf-8", "replace") for nome in nomes}


def assert_nada_de_fora(entradas: dict[str, str]) -> None:
    vazaram = sorted(nome for nome, texto in entradas.items() if FORA in texto)
    assert not vazaram, f"o zip leva conteúdo de fora do projeto em: {vazaram}"


class TestSymlinkParaFora:
    def test_link_de_arquivo_para_fora_nao_entra(self, projeto):
        (projeto / "link.txt").symlink_to(projeto.parent / "fora" / "segredo.txt")

        entradas = zipar(["link.txt", "ok.py"])

        assert_nada_de_fora(entradas)
        assert "link.txt" not in entradas
        assert entradas["ok.py"] == "print('ok')\n"

    def test_link_de_diretorio_para_fora_nao_leva_os_filhos(self, projeto):
        (projeto / "dir_link").symlink_to(projeto.parent / "fora" / "pasta", target_is_directory=True)

        entradas = zipar(["dir_link/x.txt", "ok.py"])

        assert_nada_de_fora(entradas)
        assert "dir_link/x.txt" not in entradas
        assert "ok.py" in entradas

    def test_link_encadeado_que_acaba_fora_nao_entra(self, projeto):
        (projeto / "b.txt").symlink_to(projeto.parent / "fora" / "segredo.txt")
        (projeto / "a.txt").symlink_to(projeto / "b.txt")

        entradas = zipar(["a.txt", "ok.py"])

        assert_nada_de_fora(entradas)
        assert "a.txt" not in entradas

    def test_link_relativo_com_pontos_para_fora_nao_entra(self, projeto):
        (projeto / "rel.txt").symlink_to(Path("..") / "fora" / "segredo.txt")

        entradas = zipar(["rel.txt", "ok.py"])

        assert_nada_de_fora(entradas)
        assert "rel.txt" not in entradas


class TestLacoEQuebrado:
    """V-S29-1 — ``Path.resolve()`` não estrito não levanta em laço (a→b→a): o nome passa e o ``ZipFile.write`` dá ELOOP."""

    def test_laco_de_links_e_link_quebrado_sao_pulados_sem_levantar(self, projeto):
        (projeto / "a.txt").symlink_to(projeto / "b.txt")
        (projeto / "b.txt").symlink_to(projeto / "a.txt")
        (projeto / "quebrado.txt").symlink_to(projeto / "nao_existe.txt")

        entradas = zipar(["a.txt", "quebrado.txt", "b.txt", "ok.py"])

        assert entradas == {"ok.py": "print('ok')\n"}

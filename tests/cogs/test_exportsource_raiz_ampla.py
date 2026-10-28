"""V-S29-4 — uma ``RUNTIME_DIR`` ampla demais (``/`` ou ancestral do projeto) NÃO vale como raiz permitida do ``source.zip``.

Nesses casos só o ``PROJECT_DIR`` vale e a recusa é registrada com um único ``logger.warning`` (não um por arquivo). O layout irmão
(``app/`` + ``data/``) segue valendo. ``is_export_refused`` é chamado direto: o ``zip_dir`` gravaria o ``source.zip`` na própria
``RUNTIME_DIR`` e, com ``/``, fora do ``tmp_path``. O ``paths.RUNTIME_DIR`` é dinâmico (lê ``EMPIREMUSE_HOME``).
"""

import os
from pathlib import Path

import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import is_export_refused

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def avisou_de_novo(monkeypatch):
    """Zera o "já avisei" entre testes."""
    monkeypatch.setattr(legacy_cmds, "_warned_runtime_root", False, raising=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """``home/`` com o projeto em ``home/x/EmpireMuse`` e arquivos de fora do projeto, mas sob ``home/``."""
    casa = tmp_path / "home"
    projeto = casa / "x" / "EmpireMuse"
    projeto.mkdir(parents=True)
    (projeto / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (casa / ".ssh").mkdir()
    (casa / ".ssh" / "id_x").write_text("CHAVE", encoding="utf-8")
    (casa / "outro.txt").write_text("outro", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", projeto.resolve())
    monkeypatch.chdir(projeto)
    return type("Casa", (), {"casa": casa, "projeto": projeto})


class TestRuntimeAncestralDoProjeto:
    @pytest.fixture(autouse=True)
    def runtime_no_pai(self, home, monkeypatch):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home.casa))

    @pytest.mark.parametrize("alvo", [".ssh/id_x", "outro.txt"])
    def test_arquivo_fora_do_projeto_mas_sob_o_runtime_e_recusado(self, home, alvo):
        assert is_export_refused(str(home.casa / alvo)) is True


class TestRuntimeNaRaizDoSistema:
    @pytest.fixture(autouse=True)
    def runtime_na_raiz(self, home, monkeypatch):
        monkeypatch.setenv("EMPIREMUSE_HOME", "/")
        assert paths.RUNTIME_DIR.resolve() == Path("/")

    def test_arquivo_fora_do_projeto_e_recusado(self, home):
        assert is_export_refused(str(home.casa / "outro.txt")) is True
        assert is_export_refused(os.path.realpath("/etc/hostname")) is True

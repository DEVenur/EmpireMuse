"""V-S29-4 — uma ``RUNTIME_DIR`` ampla demais (``/`` ou ancestral do projeto) NÃO vale como raiz permitida do ``source.zip``.

Nesses casos só o ``PROJECT_DIR`` vale e a recusa é registrada com um único ``logger.warning`` (não um por arquivo). O layout irmão
(``app/`` + ``data/``) segue valendo. ``is_export_refused`` é chamado direto: o ``zip_dir`` gravaria o ``source.zip`` na própria
``RUNTIME_DIR`` e, com ``/``, fora do ``tmp_path``. O ``paths.RUNTIME_DIR`` é dinâmico (lê ``EMPIREMUSE_HOME``).
"""

import logging
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner, is_export_refused

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


def avisos(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING and r.name == legacy_cmds.logger.name]


class TestRuntimeAncestralDoProjeto:
    @pytest.fixture(autouse=True)
    def runtime_no_pai(self, home, monkeypatch):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home.casa))

    @pytest.mark.parametrize("alvo", [".ssh/id_x", "outro.txt"])
    def test_arquivo_fora_do_projeto_mas_sob_o_runtime_e_recusado(self, home, alvo):
        assert is_export_refused(str(home.casa / alvo)) is True

    def test_arquivo_do_projeto_continua_entrando(self, home):
        assert is_export_refused(str(home.projeto / "ok.py")) is False
        assert is_export_refused("ok.py") is False

    def test_o_zip_nao_leva_o_que_esta_fora_do_projeto(self, home):
        Owner.zip_dir([str(home.casa / ".ssh" / "id_x"), str(home.casa / "outro.txt"), "ok.py"])

        with ZipFile(home.casa / "source.zip") as pacote:
            assert [n for n in pacote.namelist() if n.endswith("ok.py")] and len(pacote.namelist()) == 1

    def test_registra_um_unico_aviso_para_varias_chamadas(self, home, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                is_export_refused(str(home.casa / "outro.txt"))
                is_export_refused(str(home.projeto / "ok.py"))
                is_export_refused(str(home.casa / ".ssh" / "id_x"))

        assert len(avisos(caplog)) == 1

    def test_o_aviso_nao_traz_segredo_nem_caminho_de_arquivo(self, home, caplog):
        with caplog.at_level(logging.WARNING):
            is_export_refused(str(home.casa / ".ssh" / "id_x"))

        (aviso,) = avisos(caplog)
        assert "id_x" not in aviso.getMessage() and "CHAVE" not in aviso.getMessage()


class TestRuntimeNaRaizDoSistema:
    @pytest.fixture(autouse=True)
    def runtime_na_raiz(self, home, monkeypatch):
        monkeypatch.setenv("EMPIREMUSE_HOME", "/")
        assert paths.RUNTIME_DIR.resolve() == Path("/")

    def test_arquivo_fora_do_projeto_e_recusado(self, home):
        assert is_export_refused(str(home.casa / "outro.txt")) is True
        assert is_export_refused(os.path.realpath("/etc/hostname")) is True

    def test_arquivo_do_projeto_continua_entrando(self, home):
        assert is_export_refused(str(home.projeto / "ok.py")) is False

    def test_registra_um_unico_aviso(self, home, caplog):
        with caplog.at_level(logging.WARNING):
            for _ in range(4):
                is_export_refused(str(home.casa / "outro.txt"))
                is_export_refused(str(home.projeto / "ok.py"))

        assert len(avisos(caplog)) == 1


class TestLayoutValido:
    """Guarda: ``app/`` + ``data/`` (runtime irmão, não ancestral) e ``.runtime`` filha seguem sem aviso."""

    def test_runtime_irma_do_projeto_segue_valendo_como_raiz_sem_aviso(self, tmp_path, monkeypatch, caplog):
        app, data = tmp_path / "app", tmp_path / "data"
        app.mkdir()
        data.mkdir()
        (data / "lavalink.ini").write_text("[lavalink]\n", encoding="utf-8")
        monkeypatch.setattr(paths, "PROJECT_DIR", app.resolve())
        monkeypatch.setenv("EMPIREMUSE_HOME", str(data))

        with caplog.at_level(logging.WARNING):
            recusado = [is_export_refused(str(data / "lavalink.ini")) for _ in range(3)]

        assert recusado == [False, False, False]
        assert avisos(caplog) == []

    def test_runtime_dentro_do_projeto_nao_avisa(self, tmp_path, monkeypatch, caplog):
        projeto = tmp_path / "projeto"
        (projeto / ".runtime").mkdir(parents=True)
        (projeto / "ok.py").write_text("x\n", encoding="utf-8")
        monkeypatch.setattr(paths, "PROJECT_DIR", projeto.resolve())
        monkeypatch.setenv("EMPIREMUSE_HOME", str(projeto / ".runtime"))

        with caplog.at_level(logging.WARNING):
            assert is_export_refused(str(projeto / "ok.py")) is False

        assert avisos(caplog) == []

    def test_runtime_igual_ao_projeto_nao_avisa(self, tmp_path, monkeypatch, caplog):
        projeto = tmp_path / "projeto"
        projeto.mkdir()
        (projeto / "ok.py").write_text("x\n", encoding="utf-8")
        monkeypatch.setattr(paths, "PROJECT_DIR", projeto.resolve())
        monkeypatch.setenv("EMPIREMUSE_HOME", str(projeto))

        with caplog.at_level(logging.WARNING):
            assert is_export_refused(str(projeto / "ok.py")) is False

        assert avisos(caplog) == []

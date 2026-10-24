"""F3-7 — a mensagem do ``SystemExit`` de ``enter_runtime_dir`` aponta para a origem certa do diretório.

Com ``EMPIREMUSE_HOME`` o conserto é a variável; com a ``.runtime/`` de desenvolvimento a variável nem existe, então a
mensagem fala da pasta. Entrar numa pasta é forçado a falhar trocando ``os.chdir`` (o teste roda inclusive como root).
"""

import pytest

from empiremuse import paths
from empiremuse import __main__ as main_module


@pytest.fixture
def chdir_falha(monkeypatch):
    def recusar(_destino):
        raise PermissionError(13, "Permissão negada")

    monkeypatch.setattr(main_module.os, "chdir", recusar)


@pytest.fixture
def projeto(monkeypatch, tmp_path):
    raiz = (tmp_path / "projeto").resolve()
    raiz.mkdir()
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz)
    monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return raiz


class TestMensagemDoSystemExit:
    def test_com_a_runtime_de_desenvolvimento_nao_cita_a_variavel(self, projeto, chdir_falha):
        (projeto / ".runtime").mkdir()

        with pytest.raises(SystemExit) as erro:
            main_module.enter_runtime_dir()

        texto = str(erro.value)
        assert "EMPIREMUSE_HOME" not in texto
        assert ".runtime" in texto
        assert str(projeto / ".runtime") in texto
        assert "Permissão negada" in texto

"""F3-7 (AppSec A3) — a subida diz de onde vem o ``RUNTIME_DIR``: o caminho e a origem, nunca conteúdo de arquivo.

A ``.runtime/`` é escolhida em silêncio quando existe; num pacote da Discloud que a levasse por engano ela passaria a
valer no lugar do ``.env`` da raiz sem aviso nenhum. Uma linha na subida torna a escolha visível.

Contrato: ``enter_runtime_dir()`` (a primeira coisa que ``main()`` chama) emite UMA linha, pelo ``logging`` ou por
``print``, com o caminho do ``RUNTIME_DIR`` e a origem:

- ``EMPIREMUSE_HOME`` definido        -> a linha cita ``EMPIREMUSE_HOME``;
- ``PROJECT_DIR/.runtime`` existente  -> a linha cita ``.runtime`` e não cita as outras duas origens;
- nenhuma das duas                    -> a linha cita ``pasta atual``.
"""

import logging
import os

import pytest

from empiremuse import __main__ as main_module
from empiremuse import paths

SEGREDO = "SEGREDO-NO-LOG-123"
ORIGENS = ("EMPIREMUSE_HOME", "pasta atual")


@pytest.fixture
def pastas(monkeypatch, tmp_path_factory):
    """Projeto falso, uma pasta de container e um cwd; nomes neutros para não confundir com o texto da origem."""
    raiz = tmp_path_factory.mktemp("proj").resolve()
    home = tmp_path_factory.mktemp("cnt").resolve()
    cwd = tmp_path_factory.mktemp("cwd").resolve()
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz)
    monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
    monkeypatch.chdir(cwd)
    for pasta in (home, cwd):
        (pasta / ".env").write_text(f"TOKEN={SEGREDO}", encoding="utf-8")
        (pasta / "config.json").write_text(f'{{"MONGO": "{SEGREDO}"}}', encoding="utf-8")
    return raiz, home, cwd


@pytest.fixture
def runtime_dev(pastas):
    pasta = pastas[0] / ".runtime"
    pasta.mkdir()
    (pasta / ".env").write_text(f"TOKEN={SEGREDO}", encoding="utf-8")
    (pasta / "config.json").write_text(f'{{"MONGO": "{SEGREDO}"}}', encoding="utf-8")
    return pasta


def _saida(caplog, capsys) -> list[str]:
    capturado = capsys.readouterr()
    linhas = [r.getMessage() for r in caplog.records] + capturado.out.splitlines() + capturado.err.splitlines()
    return [linha for linha in linhas if linha.strip()]


def _linhas_do_runtime(linhas: list[str], runtime) -> list[str]:
    return [linha for linha in linhas if str(runtime) in linha]


@pytest.fixture(autouse=True)
def _captura_info(caplog):
    caplog.set_level(logging.INFO)


class TestLinhaDeOrigem:
    def test_empiremuse_home_loga_caminho_e_a_variavel(self, monkeypatch, pastas, caplog, capsys):
        _, home, _ = pastas
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home))

        main_module.enter_runtime_dir()

        linhas = _linhas_do_runtime(_saida(caplog, capsys), home)
        assert len(linhas) == 1
        assert "EMPIREMUSE_HOME" in linhas[0]
        assert "pasta atual" not in linhas[0]

    def test_runtime_de_desenvolvimento_loga_caminho_e_a_origem(self, pastas, runtime_dev, caplog, capsys):
        main_module.enter_runtime_dir()

        linhas = _linhas_do_runtime(_saida(caplog, capsys), runtime_dev)
        assert len(linhas) == 1
        assert ".runtime" in linhas[0]
        assert not [origem for origem in ORIGENS if origem in linhas[0]]

    def test_sem_nada_loga_o_cwd_como_pasta_atual(self, pastas, caplog, capsys):
        _, _, cwd = pastas

        main_module.enter_runtime_dir()

        linhas = _linhas_do_runtime(_saida(caplog, capsys), cwd)
        assert len(linhas) == 1
        assert "pasta atual" in linhas[0]
        assert "EMPIREMUSE_HOME" not in linhas[0]

    def test_runtime_que_e_arquivo_conta_como_pasta_atual(self, pastas, caplog, capsys):
        raiz, _, cwd = pastas
        (raiz / ".runtime").write_text("não sou uma pasta", encoding="utf-8")

        main_module.enter_runtime_dir()

        linhas = _linhas_do_runtime(_saida(caplog, capsys), cwd)
        assert len(linhas) == 1
        assert "pasta atual" in linhas[0]

    def test_empiremuse_home_vazio_com_runtime_loga_a_runtime(self, monkeypatch, pastas, runtime_dev, caplog, capsys):
        monkeypatch.setenv("EMPIREMUSE_HOME", "")

        main_module.enter_runtime_dir()

        linhas = _linhas_do_runtime(_saida(caplog, capsys), runtime_dev)
        assert len(linhas) == 1
        assert "EMPIREMUSE_HOME" not in linhas[0]


class TestSemConteudoDeArquivo:
    @pytest.mark.parametrize("origem", ["home", "dev", "cwd"])
    def test_nenhuma_saida_leva_conteudo_de_env_ou_config(self, monkeypatch, pastas, caplog, capsys, request, origem):
        if origem == "home":
            monkeypatch.setenv("EMPIREMUSE_HOME", str(pastas[1]))
        elif origem == "dev":
            request.getfixturevalue("runtime_dev")

        main_module.enter_runtime_dir()

        assert not [linha for linha in _saida(caplog, capsys) if SEGREDO in linha]

    def test_entra_na_pasta_e_a_linha_sai_uma_vez_so(self, pastas, runtime_dev, caplog, capsys):
        main_module.enter_runtime_dir()
        assert os.path.samefile(os.getcwd(), runtime_dev)

        assert len(_linhas_do_runtime(_saida(caplog, capsys), runtime_dev)) == 1

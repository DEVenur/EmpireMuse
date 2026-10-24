"""D-23 — o bot sob o Pterodactyl: cwd no EMPIREMUSE_HOME e porta vinda de SERVER_PORT.

O Wings cria o container sem ``Cmd`` e sem ``WorkingDir`` (o cwd fica no ``/data`` da imagem, que o usuário do nó não
grava) e exporta ``SERVER_PORT``/``SERVER_IP``. O valor das variáveis do egg vai literal, sem interpolação.
"""

import os
from unittest.mock import MagicMock

import pytest

from empiremuse import config_loader


@pytest.fixture
def sem_porta(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("SERVER_PORT", raising=False)


@pytest.fixture
def cwd_restaurado(monkeypatch):
    """Garante que o chdir do ponto de entrada não vaza para os outros testes."""
    monkeypatch.chdir(os.getcwd())


# --------------------------------------------------------------------------------------------------------------
# 1. Diretório de trabalho
# --------------------------------------------------------------------------------------------------------------


class TestCwdNoRuntimeDir:
    @pytest.fixture
    def main_module(self, monkeypatch):
        import empiremuse.__main__ as main_module

        self.cwd_na_construcao = []

        class PoolFalso:
            def __init__(inner):
                self.cwd_na_construcao.append(os.getcwd())
                inner.exit_code = 0

            def setup(inner):
                pass

        monkeypatch.setattr(main_module, "BotPool", PoolFalso)
        return main_module

    @pytest.mark.smoke
    def test_empiremuse_home_vazio_e_ignorado(self, monkeypatch, tmp_path, main_module, cwd_restaurado):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMPIREMUSE_HOME", "")

        with pytest.raises(SystemExit):
            main_module.main()

        assert os.path.samefile(os.getcwd(), tmp_path)


# --------------------------------------------------------------------------------------------------------------
# 2. Porta
# --------------------------------------------------------------------------------------------------------------


class TestResolvePort:
    def test_nenhuma_usa_6000(self, sem_porta):
        assert config_loader.resolve_port(None) == 6000


class TestLoadConfigRpcServer:
    @pytest.fixture(autouse=True)
    def runtime_vazio(self, monkeypatch, tmp_path, sem_porta):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))

    @pytest.mark.smoke
    def test_rpc_server_port_vence_server_port(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv("SERVER_PORT", "25565")
        assert config_loader.load_config()["RPC_SERVER"] == "ws://localhost:8080/ws"


class TestServidorHttp:
    @pytest.fixture
    def listen_chamado(self, monkeypatch):
        from empiremuse import web_app

        chamadas = []

        class ServidorFalso:
            def __init__(self, *args, **kwargs):
                pass

            def listen(self, porta, address=None, **kwargs):
                chamadas.append(porta)

        monkeypatch.setattr(web_app.tornado.httpserver, "HTTPServer", ServidorFalso)
        monkeypatch.setattr(web_app, "_build_panel", lambda pool, config: (None, False))
        monkeypatch.setattr(web_app, "make_router", lambda app, panel: app)
        return web_app, chamadas

    def test_porta_invalida_e_erro_claro_e_nao_escuta(self, monkeypatch, sem_porta, listen_chamado):
        web_app, chamadas = listen_chamado
        monkeypatch.setenv("SERVER_PORT", "{{SERVER_PORT}}")
        with pytest.raises(ValueError, match="SERVER_PORT"):
            web_app.run_app(MagicMock(), config={"PORT": None})
        assert chamadas == []

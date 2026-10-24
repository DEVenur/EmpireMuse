"""O log em arquivo do bot (``.logs/disnake.log``): rotativo, em append, sem token de webhook e privado ao dono."""

import logging
import logging.handlers
import os
import stat
import sys

import pytest

from empiremuse.utils import file_log

ID = "1234567890123456"
TOKEN = "AbC-dEf_123.xYz-SECRETO-token_do_webhook"
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="modos de arquivo POSIX")


@pytest.fixture
def handler(tmp_path):
    criado = file_log.build_file_log_handler(tmp_path / ".logs")
    yield criado
    criado.close()


def registro(mensagem, *args, **kwargs):
    return logging.LogRecord("t", logging.DEBUG, __file__, 1, mensagem, args or None, kwargs.get("exc_info"))


@pytest.mark.smoke
def test_o_handler_e_rotativo_com_5_mb_e_3_copias(handler):
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3


class TestRedacaoDeTokenDeWebhook:
    @pytest.mark.parametrize("host", ["discord.com", "canary.discordapp.com"])
    @pytest.mark.parametrize("versao", ["", "/v10"])
    def test_o_token_vira_asteriscos_em_cada_host(self, handler, tmp_path, host, versao):
        url = f"https://{host}/api{versao}/webhooks/{ID}/{TOKEN}"

        handler.handle(registro("POST %s retornou 204", url))
        handler.flush()

        texto = (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")
        assert TOKEN not in texto
        assert f"/webhooks/{ID}/*** retornou 204" in texto

    def test_mensagem_sem_webhook_nao_e_alterada(self):
        gravado = registro("Pedido %s feito por %d", "play", 7)

        assert file_log.RedactWebhookTokens().filter(gravado) is True
        assert gravado.getMessage() == "Pedido play feito por 7"


@POSIX
class TestPermissoes:
    def test_o_arquivo_recriado_na_rotacao_continua_privado(self, handler, tmp_path):
        handler.handle(registro("antes"))
        handler.doRollover()
        handler.handle(registro("depois"))

        assert stat.S_IMODE(os.stat(tmp_path / ".logs" / "disnake.log").st_mode) == 0o600
        assert stat.S_IMODE(os.stat(tmp_path / ".logs" / "disnake.log.1").st_mode) == 0o600

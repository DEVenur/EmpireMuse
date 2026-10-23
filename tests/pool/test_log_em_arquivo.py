"""O log em arquivo do bot (``.logs/disnake.log``): rotativo, em append, sem token de webhook e privado ao dono."""

import logging
import logging.handlers
import os
import stat
import sys

import pytest

from empiremuse.utils import client, file_log

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


def test_a_funcao_continua_acessivel_pelo_client():
    assert client.build_file_log_handler is file_log.build_file_log_handler


def test_o_handler_e_rotativo_com_5_mb_e_3_copias(handler):
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3


def test_o_arquivo_fica_em_logs_dir_disnake_log(handler, tmp_path):
    assert handler.baseFilename == str(tmp_path / ".logs" / "disnake.log")


def test_reabrir_preserva_o_que_ja_estava_no_arquivo(tmp_path):
    pasta = tmp_path / ".logs"
    pasta.mkdir()
    (pasta / "disnake.log").write_text("ERR-ANTIGO linha anterior\n", encoding="utf-8")

    novo = file_log.build_file_log_handler(pasta)
    novo.emit(registro("ERR-NOVO depois do reinício"))
    novo.close()

    texto = (pasta / "disnake.log").read_text(encoding="utf-8")
    assert "ERR-ANTIGO linha anterior" in texto
    assert "ERR-NOVO depois do reinício" in texto


def test_o_formato_tem_data_nivel_nome_e_mensagem(handler):
    assert "WARNING t mensagem" in handler.format(
        logging.LogRecord("t", logging.WARNING, __file__, 1, "mensagem", None, None)
    )


class TestRedacaoDeTokenDeWebhook:
    @pytest.mark.parametrize(
        "host", ["discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com", "canary.discordapp.com"]
    )
    @pytest.mark.parametrize("versao", ["", "/v10"])
    def test_o_token_vira_asteriscos_em_cada_host(self, handler, tmp_path, host, versao):
        url = f"https://{host}/api{versao}/webhooks/{ID}/{TOKEN}"

        handler.handle(registro("POST %s retornou 204", url))
        handler.flush()

        texto = (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")
        assert TOKEN not in texto
        assert f"/webhooks/{ID}/*** retornou 204" in texto

    def test_o_resto_da_mensagem_e_dos_args_continua_igual(self, handler, tmp_path):
        handler.handle(
            registro("Enviando %s para %s (%d bytes)", f"/api/v10/webhooks/{ID}/{TOKEN}?wait=true", "canal", 42)
        )
        handler.flush()

        texto = (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")
        assert f"Enviando /api/v10/webhooks/{ID}/***?wait=true para canal (42 bytes)" in texto

    def test_o_token_no_corpo_ou_no_traceback_tambem_some(self, handler, tmp_path):
        try:
            raise RuntimeError(f"falha em https://discord.com/api/webhooks/{ID}/{TOKEN}")
        except RuntimeError:
            handler.handle(registro("erro", exc_info=sys.exc_info()))
        handler.flush()

        texto = (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")
        assert TOKEN not in texto and "RuntimeError" in texto

    def test_mensagem_sem_webhook_nao_e_alterada(self):
        gravado = registro("Pedido %s feito por %d", "play", 7)

        assert file_log.RedactWebhookTokens().filter(gravado) is True
        assert gravado.getMessage() == "Pedido play feito por 7"

    def test_registro_com_args_quebrados_nao_e_descartado(self):
        gravado = registro("valor %d", "não é número")

        assert file_log.RedactWebhookTokens().filter(gravado) is True
        assert "falha ao redigir" in gravado.getMessage()


@POSIX
class TestPermissoes:
    def test_a_pasta_e_o_arquivo_sao_privados(self, handler, tmp_path):
        handler.handle(registro("linha"))

        assert stat.S_IMODE(os.stat(tmp_path / ".logs").st_mode) == 0o700
        assert stat.S_IMODE(os.stat(tmp_path / ".logs" / "disnake.log").st_mode) == 0o600

    def test_pasta_e_arquivo_antigos_com_modo_aberto_sao_restringidos(self, tmp_path):
        pasta = tmp_path / ".logs"
        pasta.mkdir(mode=0o755)
        arquivo = pasta / "disnake.log"
        arquivo.write_text("antigo\n", encoding="utf-8")
        arquivo.chmod(0o644)

        file_log.build_file_log_handler(pasta).close()

        assert stat.S_IMODE(os.stat(pasta).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(arquivo).st_mode) == 0o600

    def test_o_arquivo_recriado_na_rotacao_continua_privado(self, handler, tmp_path):
        handler.handle(registro("antes"))
        handler.doRollover()
        handler.handle(registro("depois"))

        assert stat.S_IMODE(os.stat(tmp_path / ".logs" / "disnake.log").st_mode) == 0o600
        assert stat.S_IMODE(os.stat(tmp_path / ".logs" / "disnake.log.1").st_mode) == 0o600


def test_falha_ao_ajustar_permissao_nao_impede_o_log(monkeypatch, tmp_path):
    def negar(*args, **kwargs):
        raise PermissionError("sem permissão")

    monkeypatch.setattr(file_log.os, "chmod", negar)
    criado = file_log.build_file_log_handler(tmp_path / ".logs")
    criado.handle(registro("segue gravando"))
    criado.close()

    assert "segue gravando" in (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")

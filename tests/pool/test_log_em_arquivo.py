"""O log em arquivo do bot (``.logs/disnake.log``) é rotativo e em append, para sobreviver a reinícios."""

import logging
import logging.handlers

import pytest

from empiremuse.utils import client


@pytest.fixture
def handler(tmp_path):
    criado = client.build_file_log_handler(tmp_path)
    yield criado
    criado.close()


def test_o_handler_e_rotativo_com_5_mb_e_3_copias(handler):
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3


def test_o_arquivo_fica_em_logs_dir_disnake_log(handler, tmp_path):
    assert handler.baseFilename == str(tmp_path / "disnake.log")


def test_reabrir_preserva_o_que_ja_estava_no_arquivo(tmp_path):
    (tmp_path / "disnake.log").write_text("ERR-ANTIGO linha anterior\n", encoding="utf-8")

    novo = client.build_file_log_handler(tmp_path)
    novo.emit(logging.LogRecord("t", logging.ERROR, __file__, 1, "ERR-NOVO depois do reinício", None, None))
    novo.close()

    texto = (tmp_path / "disnake.log").read_text(encoding="utf-8")
    assert "ERR-ANTIGO linha anterior" in texto
    assert "ERR-NOVO depois do reinício" in texto


def test_o_formato_tem_data_nivel_nome_e_mensagem(handler):
    registro = logging.LogRecord("modulo", logging.WARNING, __file__, 1, "mensagem", None, None)

    saida = handler.format(registro)

    assert "WARNING modulo mensagem" in saida

"""S-28 (ampliado) — nenhuma saída dos caminhos Lavalink/Spotify/Deezer leva a senha que está nos headers da requisição.

O ``repr`` de um ``aiohttp.ClientResponseError`` (e de ``ContentTypeError``) inclui o ``RequestInfo`` com ``Authorization``. Sessão, node,
bot e provedores são fakes; o ``sleep`` dos backoffs é trocado: nada dorme nem sai da máquina.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.wavelink.node import Node
from tests.support.erros_http import CORPO_SECRETO, SENHA, SessaoComStatus, SessaoQueNaoEntendeJson

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


def saida_visivel(capsys, caplog) -> str:
    """Tudo o que o operador veria: stdout/stderr e os registros de log (a saída do ``check_node`` passou do ``print`` para o log)."""
    saida = capsys.readouterr()
    return saida.out + saida.err + "\n".join(r.getMessage() for r in caplog.records) + caplog.text


def sem_segredo(texto: str) -> None:
    assert SENHA not in texto and CORPO_SECRETO not in texto and "RequestInfo" not in texto, texto


def node_falso(**campos) -> Node:
    node = Node.__new__(Node)
    bot = SimpleNamespace(user="bot", is_closed=lambda: False, pool=SimpleNamespace(playlist_cache={}))
    node.__dict__.update(
        identifier="NODE-X",
        rest_uri="http://127.0.0.1:8090",
        password=SENHA,
        version=4,
        info={},
        max_retries=2,
        _is_connecting=False,
        _client=SimpleNamespace(bot=bot),
        session=SessaoQueNaoEntendeJson(),
        **campos,
    )
    bot.session = node.session
    return node


async def test_node_connect_failure_message_has_no_header(capsys, caplog):
    """(C) ``Node.connect``: a última falha é impressa como causa."""
    caplog.set_level(logging.INFO)
    await node_falso().connect()

    saida = capsys.readouterr()
    visivel = saida.out + saida.err + caplog.text  # a saída passou do print para o log
    sem_segredo(visivel)
    assert "Falha ao conectar no servidor [NODE-X]" in visivel and "HTTP 200" in visivel


# ============================================================================ /v4/info com status de erro: a causa é só "HTTP <status>"


@pytest.mark.parametrize("status", [401, 500])
async def test_check_node_http_status_failure_logs_only_the_status(monkeypatch, capsys, caplog, status):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(client.aiohttp, "ClientSession", lambda: SessaoComStatus(status))
    pool = BotPool.__new__(BotPool)
    pool.get_all_bots = lambda: []
    pool.mongo_database = None

    await pool.check_node({"host": "127.0.0.1", "port": 8090, "password": SENHA, "identifier": "NODE-X", "retries": 1})

    visivel = saida_visivel(capsys, caplog)
    sem_segredo(visivel)
    assert "Todas as tentativas de verificar o servidor [NODE-X] falharam" in visivel and f"HTTP {status}" in visivel

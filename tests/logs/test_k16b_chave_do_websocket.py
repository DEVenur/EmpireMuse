# ruff: noqa: F811
"""Item 7 (P3, K16b, #127) — a falha de conexão do websocket do nó agrega por nó E por motivo (``aggregate_key = "<nó>|<safe_error>"``).

``safe_error`` é ``HTTP <status>`` ou o nome da classe da exceção, nunca o texto. Assim 403 e 503 do mesmo nó não se escondem, o mesmo motivo
repetido agrega, e dois nós com o mesmo motivo saem os dois. A chave nunca aparece no console nem no arquivo. ``configure_logging`` real,
relógio injetado; o ``ws_connect`` é falso e nada dorme.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from empiremuse.wavelink.websocket import WebSocket
from tests.logs.test_k16_chave_de_agregacao import destinos  # noqa: F401  (fixture)

pytestmark = pytest.mark.critical


def erro_http(status: int, classe=aiohttp.ClientResponseError):
    return classe(MagicMock(), (), status=status, message="mensagem-do-servidor")


def websocket_do_no(identificador: str, erro: Exception) -> WebSocket:
    """``WebSocket`` sem rede: o ``ws_connect`` do nó levanta ``erro``."""
    socket = WebSocket.__new__(WebSocket)
    socket._node = SimpleNamespace(
        identifier=identificador,
        version=4,
        password="senha-do-no",
        uid=1,
        resume_key=None,
        session_id="s",
        available=True,
        heartbeat=30,
        session=SimpleNamespace(ws_connect=AsyncMock(side_effect=erro)),
    )
    socket.bot = SimpleNamespace(wait_until_ready=AsyncMock())
    socket.host, socket.port, socket.secure = "no.exemplo.invalido", 2333, False
    socket.user_agent, socket._websocket, socket._task = None, None, None
    socket._node_started, socket._closed, socket._last_exc = False, True, None
    return socket


def completas(texto: str, trecho: str) -> int:
    """Linhas inteiras com ``trecho``, sem contar a de resumo (que repete o texto e traz "repetida")."""
    return sum(1 for linha in texto.splitlines() if trecho in linha and "repetida" not in linha)


async def falhar(identificador: str, erro: Exception) -> None:
    await websocket_do_no(identificador, erro)._connect()


@pytest.mark.asyncio
class TestChaveDoWebsocket:
    @pytest.mark.parametrize(
        "classe", [aiohttp.ClientResponseError, aiohttp.WSServerHandshakeError], ids=lambda c: c.__name__
    )
    async def test_403_then_503_on_the_same_node_are_two_full_lines(self, destinos, classe):
        await falhar("no-1", erro_http(403, classe))
        await falhar("no-1", erro_http(503, classe))

        for texto in destinos.textos():
            assert (
                completas(texto, "Connection Failure:: HTTP 403") == 1
                and completas(texto, "Connection Failure:: HTTP 503") == 1
            )
            assert "repetida" not in texto

    async def test_503_twice_on_the_same_node_is_one_line_and_a_summary(self, destinos):
        await falhar("no-1", erro_http(503))
        await falhar("no-1", erro_http(503))

        for texto in destinos.textos():
            assert completas(texto, "Connection Failure:: HTTP 503") == 1 and "repetida 1×" in texto

    async def test_two_nodes_with_503_are_two_full_lines(self, destinos):
        await falhar("no-1", erro_http(503))
        await falhar("no-2", erro_http(503))

        for texto in destinos.textos():
            assert "WEBSOCKET no-1 |" in texto and "WEBSOCKET no-2 |" in texto and "repetida" not in texto

    async def test_two_exception_classes_without_status_are_two_keys_and_the_same_class_aggregates(self, destinos):
        await falhar("no-1", asyncio.TimeoutError())
        await falhar("no-1", ConnectionRefusedError("recusada"))
        await falhar("no-1", ConnectionRefusedError("recusada"))

        for texto in destinos.textos():
            assert completas(texto, "Connection Failure:: TimeoutError") == 1
            assert completas(texto, "Connection Failure:: ConnectionRefusedError") == 1 and "repetida 1×" in texto

    async def test_the_aggregate_key_never_reaches_the_console_or_the_file(self, destinos):
        await falhar("no-1", erro_http(403))
        await falhar("no-1", erro_http(503))
        await falhar("no-1", erro_http(503))

        for texto in destinos.textos():
            assert "aggregate_key" not in texto and "no-1|HTTP" not in texto

    async def test_the_exception_text_still_never_reaches_the_log(self, destinos):
        await falhar("no-1", erro_http(503))

        for texto in destinos.textos():
            assert "mensagem-do-servidor" not in texto and "senha-do-no" not in texto

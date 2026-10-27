"""S-28 (ampliado) — nenhuma saída dos caminhos Lavalink/Spotify/Deezer leva a senha que está nos headers da requisição.

O ``repr`` de um ``aiohttp.ClientResponseError`` (e de ``ContentTypeError``) inclui o ``RequestInfo`` com ``Authorization``. Sessão, node,
bot e provedores são fakes; o ``sleep`` dos backoffs é trocado: nada dorme nem sai da máquina.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import empiremuse.wavelink as wavelink
from empiremuse.music_cog.nodes import NodesMixin
from empiremuse.music_cog.tracks import TracksMixin
from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.wavelink.node import Node
from tests.support.erros_http import CORPO_SECRETO, SENHA, SessaoComStatus, SessaoQueNaoEntendeJson, erro_response

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


def sem_segredo(texto: str) -> None:
    assert SENHA not in texto and CORPO_SECRETO not in texto and "RequestInfo" not in texto, texto


async def test_check_node_final_failure_message_has_no_header(monkeypatch, capsys):
    """(B) a falha vem do ``r.json()`` (ContentTypeError) e a mensagem final traz a causa."""
    monkeypatch.setattr(client.aiohttp, "ClientSession", lambda: SessaoComoContexto())
    pool = BotPool.__new__(BotPool)
    pool.get_all_bots = lambda: []
    pool.mongo_database = None

    await pool.check_node({"host": "127.0.0.1", "port": 8090, "password": SENHA, "identifier": "NODE-X", "retries": 1})

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert "Todas as tentativas de verificar o servidor [NODE-X] falharam" in saida.out and "HTTP 200" in saida.out


class SessaoComoContexto(SessaoQueNaoEntendeJson):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


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


async def test_node_connect_failure_message_has_no_header(capsys):
    """(C) ``Node.connect``: a última falha é impressa como causa."""
    await node_falso().connect()

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert "Falha ao conectar no servidor [NODE-X]" in saida.out and "HTTP 200" in saida.out


async def test_get_tracks_json_parse_error_has_no_header():
    """(D) ``resp.json()`` levantando ContentTypeError vira ``WavelinkException`` sem o header."""
    with pytest.raises(wavelink.WavelinkException) as erro:
        await node_falso().get_tracks("ytsearch:x")

    sem_segredo(str(erro.value))
    assert "NODE-X" in str(erro.value) and "HTTP 200" in str(erro.value)


async def test_node_reconnect_message_has_no_header(capsys):
    """(E) a reconexão imprime o erro de cada tentativa (node que não é o LOCAL)."""
    node = node_falso(
        players={},
        session_id=None,
        uid=1,
        _retry_dt=datetime.fromtimestamp(0, timezone.utc),
        _retry_count=0,
        _websocket=SimpleNamespace(_connect=AsyncMock(), is_connected=False),
    )
    cog = NodesMixin()
    cog.bot = SimpleNamespace(
        user="bot", session=node.session, config={"LAVALINK_RECONNECT_RETRIES": 2}, wait_until_ready=AsyncMock()
    )

    await cog.node_reconnect(node)

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert "Falha ao reconectar no servidor [NODE-X]" in saida.out and "HTTP 200" in saida.out


def ctx_e_bot(**config):
    bot = SimpleNamespace(
        dispatch=Mock(),
        spotify=object(),
        music=SimpleNamespace(nodes={}),
        pool=SimpleNamespace(config={"FORCE_USE_DEEZER_CLIENT": False, **config}),
    )
    return SimpleNamespace(), bot


@pytest.mark.parametrize("provedor", ["deezer", "spotify"])
async def test_partial_tracks_exceptions_set_has_no_header(provedor):
    """(F) o conjunto de exceções devolvido ao chamador (e mostrado ao usuário) leva só o resumo seguro."""
    ctx, bot = ctx_e_bot(FORCE_USE_DEEZER_CLIENT=provedor == "deezer")
    falha = AsyncMock(side_effect=erro_response(401))
    bot.pool.deezer = SimpleNamespace(get_tracks=falha)
    bot.pool.spotify = SimpleNamespace(get_tracks=falha)
    cog = TracksMixin()
    cog.bot = bot
    user = SimpleNamespace(id=1)

    _, _, excecoes = await cog.get_partial_tracks("busca", ctx, user, bot=bot)

    assert excecoes == {"HTTP 401"}


async def test_lavalink_tracks_exceptions_set_has_no_header():
    """(F) o mesmo para a busca no node: o conjunto devolvido não leva o ``repr`` com o header."""
    node = SimpleNamespace(
        is_available=True,
        available=True,
        players={},
        info={},
        search_providers=["ytsearch"],
        get_tracks=AsyncMock(side_effect=erro_response(401)),
    )
    bot = SimpleNamespace(dispatch=Mock(), music=SimpleNamespace(nodes={"a": node}))
    cog = TracksMixin()
    cog.bot = bot

    _, _, excecoes = await cog.get_lavalink_tracks("busca", SimpleNamespace(), SimpleNamespace(id=1), bot=bot)

    assert excecoes == {"HTTP 401"}


# ============================================================================ /v4/info com status de erro: a causa é só "HTTP <status>"


@pytest.mark.parametrize("status", [401, 500])
async def test_check_node_http_status_failure_logs_only_the_status(monkeypatch, capsys, status):
    monkeypatch.setattr(client.aiohttp, "ClientSession", lambda: SessaoComStatus(status))
    pool = BotPool.__new__(BotPool)
    pool.get_all_bots = lambda: []
    pool.mongo_database = None

    await pool.check_node({"host": "127.0.0.1", "port": 8090, "password": SENHA, "identifier": "NODE-X", "retries": 1})

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert (
        "Todas as tentativas de verificar o servidor [NODE-X] falharam" in saida.out and f"HTTP {status}" in saida.out
    )


@pytest.mark.parametrize("status", [401, 500])
async def test_node_connect_http_status_failure_logs_only_the_status(capsys, status):
    node = node_falso()
    node.session = node._client.bot.session = SessaoComStatus(status)

    await node.connect()

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert "Falha ao conectar no servidor [NODE-X]" in saida.out and f"HTTP {status}" in saida.out


@pytest.mark.parametrize("status", [401, 500])
async def test_node_reconnect_http_status_failure_logs_only_the_status(capsys, status):
    node = node_falso(
        players={},
        session_id=None,
        uid=1,
        _retry_dt=datetime.fromtimestamp(0, timezone.utc),
        _retry_count=0,
        _websocket=SimpleNamespace(_connect=AsyncMock(), is_connected=False),
    )
    sessao = SessaoComStatus(status)
    cog = NodesMixin()
    cog.bot = SimpleNamespace(
        user="bot", session=sessao, config={"LAVALINK_RECONNECT_RETRIES": 2}, wait_until_ready=AsyncMock()
    )

    await cog.node_reconnect(node)

    saida = capsys.readouterr()
    sem_segredo(saida.out + saida.err)
    assert "Falha ao reconectar no servidor [NODE-X]" in saida.out and f"HTTP {status}" in saida.out

"""F3-1 / KI-15 — a tarefa de partida que obtém o token do Spotify captura e registra a falha (sem segredos no log)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError

from empiremuse.utils.client import BotPool
from empiremuse.utils.music.errors import GenericError

SEGREDO_FAKE = "segredo-spotify-fake-123"


def _pool(erro: BaseException | None):
    spotify = SimpleNamespace(get_access_token=AsyncMock(side_effect=erro), client_secret=SEGREDO_FAKE)
    return SimpleNamespace(spotify=spotify)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "erro",
    [
        GenericError("**Não foi possível autenticar no Spotify.**"),
        ClientError("sem rede (simulado)"),
        OSError("disco cheio (simulado)"),
    ],
)
async def test_falha_ao_obter_o_token_e_registrada_e_nao_propaga(erro, caplog):
    pool = _pool(erro)

    with caplog.at_level(logging.ERROR, logger="empiremuse.utils.client"):
        await BotPool.refresh_spotify_token(pool)

    registros = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert registros, "a falha da tarefa de partida não foi registrada"
    assert "Spotify" in registros[0].getMessage()
    assert SEGREDO_FAKE not in caplog.text


@pytest.mark.asyncio
async def test_sucesso_nao_registra_erro(caplog):
    pool = _pool(None)

    with caplog.at_level(logging.ERROR, logger="empiremuse.utils.client"):
        await BotPool.refresh_spotify_token(pool)

    pool.spotify.get_access_token.assert_awaited_once()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_cancelamento_nao_e_engolido():
    pool = _pool(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await BotPool.refresh_spotify_token(pool)

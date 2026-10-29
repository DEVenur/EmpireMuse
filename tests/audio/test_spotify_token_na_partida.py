"""F3-1 / KI-15 — a tarefa de partida que obtém o token do Spotify captura e registra a falha (sem segredos no log)."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.utils.client import BotPool
from empiremuse.utils.music.errors import GenericError

pytestmark = pytest.mark.regression

SEGREDO_FAKE = "segredo-spotify-fake-123"


def _pool(erro: BaseException | None):
    spotify = SimpleNamespace(get_access_token=AsyncMock(side_effect=erro), client_secret=SEGREDO_FAKE)
    return SimpleNamespace(spotify=spotify)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "erro",
    [
        GenericError("**Credenciais recusadas.**"),  # sem a palavra Spotify: o contexto tem de vir do próprio log
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

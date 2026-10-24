"""F3-1 / KI-15 — a tarefa de partida que obtém o token do Spotify captura e registra a falha (sem segredos no log)."""

import ast
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.utils.client import BotPool
from empiremuse.utils.music.errors import GenericError
from tests.support.raiz import RAIZ

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


def _chamadas_de_create_task() -> list[ast.Call]:
    arvore = ast.parse((RAIZ / "empiremuse" / "utils" / "client.py").read_text("utf-8"))
    return [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "create_task" and no.args
    ]


def _nome_chamado(no: ast.AST) -> str | None:
    return no.func.attr if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) else None


def test_a_partida_agenda_a_tarefa_que_captura_a_falha_e_nao_o_get_access_token_solto():
    """Ligação em BotPool.setup: o bug original era um create_task(get_access_token()) sem tratamento de exceção."""
    alvos = [_nome_chamado(no.args[0]) for no in _chamadas_de_create_task()]

    assert "refresh_spotify_token" in alvos, "a partida não agenda refresh_spotify_token()"
    assert "get_access_token" not in alvos, (
        "create_task(get_access_token()) solto: a falha vira 'Task exception never retrieved'"
    )


@pytest.mark.asyncio
async def test_cancelamento_nao_e_engolido():
    pool = _pool(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await BotPool.refresh_spotify_token(pool)

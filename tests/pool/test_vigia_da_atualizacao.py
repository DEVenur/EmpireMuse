"""Item 18 (P2, F3) — o ``BotPool`` só vigia o pool quando há um pendente em disco, chama ``on_pool_ready`` uma vez e para.

Pool falso (``BotPool.__new__``), ``on_pool_ready`` trocado no módulo e intervalo zerado: nada dorme de verdade nem toca a rede.
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater.state import PendingUpdate, write_pending
from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from tests.support.alvo_git import ALVO_GIT

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def pendente(runtime):
    write_pending(
        runtime,
        PendingUpdate(
            flow="git",
            from_version=Version(2, 0, 0),
            to_version=Version(2, 1, 0),
            bot_id=1,
            channel_id=2,
            requested_by=3,
            created_at=time.time(),
            prev_sha="a" * 40,
            target_commit=ALVO_GIT,
        ),
    )


@pytest.fixture
def ao_ficar_pronto(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(client, "on_pool_ready", mock)
    return mock


def pool_que_fica_saudavel_na_checagem(numero: int, checagens: list) -> BotPool:
    """``pool_is_healthy`` devolve False até a checagem ``numero`` e True a partir dela; ``checagens`` registra cada consulta."""
    pool = BotPool.__new__(BotPool)
    pool.loop = asyncio.get_running_loop()

    def saudavel() -> bool:
        checagens.append(True)
        return len(checagens) >= numero

    pool.pool_is_healthy = saudavel
    return pool


async def test_with_a_pending_update_the_watch_calls_on_pool_ready_once_when_the_pool_turns_healthy_and_stops(
    pendente, ao_ficar_pronto, monkeypatch
):
    monkeypatch.setattr(client, "UPDATE_WATCH_INTERVAL", 0)
    checagens: list = []
    pool = pool_que_fica_saudavel_na_checagem(3, checagens)

    pool.start_update_watch()
    await asyncio.wait_for(pool.update_watch_task, timeout=5)

    assert len(checagens) == 3  # reavaliou enquanto doente e parou quando ficou saudável
    ao_ficar_pronto.assert_awaited_once_with(pool)
    await pool.check_pool_ready()  # outro gatilho (start_bot) depois da entrega: nada de segunda chamada
    ao_ficar_pronto.assert_awaited_once()


async def test_a_failing_on_pool_ready_does_not_break_the_watch_and_is_not_retried(
    pendente, ao_ficar_pronto, monkeypatch
):
    monkeypatch.setattr(client, "UPDATE_WATCH_INTERVAL", 0)
    ao_ficar_pronto.side_effect = RuntimeError("discord fora do ar")
    pool = pool_que_fica_saudavel_na_checagem(1, [])

    pool.start_update_watch()
    await asyncio.wait_for(pool.update_watch_task, timeout=5)

    ao_ficar_pronto.assert_awaited_once()
    assert pool.update_watch_task.exception() is None

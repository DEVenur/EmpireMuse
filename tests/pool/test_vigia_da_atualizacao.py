"""Item 18 (P2, F3) — o ``BotPool`` só vigia o pool quando há um pendente em disco, chama ``on_pool_ready`` uma vez e para.

Pool falso (``BotPool.__new__``), ``on_pool_ready`` trocado no módulo e intervalo zerado: nada dorme de verdade nem toca a rede.
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from empiremuse.rules.release import Version
from tests.support.alvo_git import ALVO_GIT
from empiremuse.updater.state import PendingUpdate, write_pending
from empiremuse.utils import client
from empiremuse.utils.client import BotPool

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


async def test_without_a_pending_update_no_watch_is_started(runtime, ao_ficar_pronto):
    pool = pool_que_fica_saudavel_na_checagem(1, [])

    pool.start_update_watch()

    assert pool.update_watch_task is None


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


async def test_the_watch_does_not_call_on_pool_ready_while_the_pool_is_unhealthy(
    pendente, ao_ficar_pronto, monkeypatch
):
    monkeypatch.setattr(client, "UPDATE_WATCH_INTERVAL", 0)
    cinco_checagens = asyncio.Event()

    class Checagens(list):
        def append(self, item):
            super().append(item)
            if len(self) >= 5:
                cinco_checagens.set()

    pool = pool_que_fica_saudavel_na_checagem(10**6, Checagens())

    pool.start_update_watch()
    try:
        await asyncio.wait_for(cinco_checagens.wait(), timeout=5)
    finally:
        pool.update_watch_task.cancel()
        await asyncio.gather(pool.update_watch_task, return_exceptions=True)

    ao_ficar_pronto.assert_not_awaited()
    assert not pool.update_ready_checked


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


async def test_a_pool_that_is_shutting_down_never_calls_on_pool_ready(ao_ficar_pronto):
    """I1: depois do ``shutdown`` (killing_state) um pool saudável não promove nem avisa nada."""
    pool = pool_que_fica_saudavel_na_checagem(1, [])
    pool.killing_state = True

    await pool.check_pool_ready()

    ao_ficar_pronto.assert_not_awaited()


async def test_shutdown_cancels_the_watch(pendente, ao_ficar_pronto):
    pool = pool_que_fica_saudavel_na_checagem(10**6, [])
    pool.heartbeat_task = None
    pool.bots, pool.guild_bots, pool.lavalink_instance = [], {}, None

    pool.start_update_watch()
    tarefa = pool.update_watch_task
    await asyncio.sleep(0)
    await pool.shutdown(0)
    await asyncio.gather(tarefa, return_exceptions=True)

    assert tarefa.cancelled()
    ao_ficar_pronto.assert_not_awaited()

"""S2.3 — o ``BotPool.setup`` escolhe a fábrica do loop pelo sistema: uvloop no posix, asyncio puro no nt.

Sem rede, sem Discord, sem Java e sem o uvloop real: o módulo ``uvloop`` é um dublê injetado em ``sys.modules`` (o import fica
local ao ramo posix, então o dublê só é visto ali) e as duas fábricas devolvem loops asyncio de verdade, distintos entre si,
para o teste saber qual delas foi usada. O ``os.name`` é trocado só dentro do módulo ``client`` (um proxy de ``os``): trocar o
``os.name`` global quebraria o ``pathlib``.
"""

import asyncio
import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.utils import client
from empiremuse.utils.client import BotPool

pytestmark = pytest.mark.regression

TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"  # só o formato; não é um token real


class _OsComNome:
    """Proxy de ``os`` que só muda o ``name``."""

    def __init__(self, name: str):
        self.name = name

    def __getattr__(self, atributo):
        return getattr(os, atributo)


class _Fabricas:
    """Os dois loops de verdade e as chamadas que cada fábrica recebeu."""

    def __init__(self):
        self.loop_uvloop = asyncio.new_event_loop()
        self.loop_asyncio = asyncio.new_event_loop()
        self.chamadas_uvloop = 0
        self.chamadas_asyncio = 0
        self.loops_definidos = []
        self._set_event_loop_real = asyncio.set_event_loop

    def uvloop_new_event_loop(self):
        self.chamadas_uvloop += 1
        return self.loop_uvloop

    def asyncio_new_event_loop(self):
        self.chamadas_asyncio += 1
        return self.loop_asyncio

    def set_event_loop(self, loop):
        self.loops_definidos.append(loop)
        self._set_event_loop_real(loop)

    def fechar(self):
        for loop in (self.loop_uvloop, self.loop_asyncio):
            if not loop.is_closed():
                loop.close()


@pytest.fixture
def fabricas(monkeypatch):
    """Instala as fábricas dubladas depois de criar os loops reais, para não contar a criação deles."""
    dados = _Fabricas()
    uvloop_falso = ModuleType("uvloop")
    uvloop_falso.new_event_loop = dados.uvloop_new_event_loop
    monkeypatch.setitem(sys.modules, "uvloop", uvloop_falso)
    monkeypatch.setattr(asyncio, "new_event_loop", dados.asyncio_new_event_loop)
    monkeypatch.setattr(asyncio, "set_event_loop", dados.set_event_loop)
    yield dados
    monkeypatch.undo()
    asyncio.set_event_loop(None)
    dados.fechar()


@pytest.fixture
def pool(monkeypatch, tmp_path):
    """BotPool real, com BotCore dublado e tudo o que tocaria rede, Java ou o painel neutralizado."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("RUN_LOCAL_LAVALINK", "false")
    monkeypatch.setenv("RUN_RPC_SERVER", "false")
    monkeypatch.setenv("TOKEN", TOKEN_FALSO)

    def bot_falso(**kwargs):
        bot = MagicMock(identifier=kwargs["identifier"])
        bot.loop.create_task.side_effect = lambda corotina: corotina.close()
        return bot

    monkeypatch.setattr(client, "BotCore", bot_falso)
    pool = BotPool()
    for nome in ("run_bots", "setup_pool_extras", "cache_updater", "connect_rpc_ws"):
        setattr(pool, nome, AsyncMock())
    pool.node_check = MagicMock()
    pool.start_lavalink = AsyncMock()
    return pool


def _setup_com_sistema(pool, monkeypatch, nome_do_sistema: str):
    monkeypatch.setattr(client, "os", _OsComNome(nome_do_sistema))
    pool.setup()
    # deixa as tasks dubladas criadas em self.loop terminarem antes de fechar o loop
    pool.loop.run_until_complete(asyncio.sleep(0))


class TestFabricaDeLoopDoBotPool:
    def test_no_posix_o_loop_do_pool_vem_do_uvloop(self, pool, fabricas, monkeypatch):
        _setup_com_sistema(pool, monkeypatch, "posix")

        assert pool.loop is fabricas.loop_uvloop
        assert fabricas.chamadas_uvloop == 1

    def test_no_posix_o_asyncio_puro_nao_cria_o_loop(self, pool, fabricas, monkeypatch):
        _setup_com_sistema(pool, monkeypatch, "posix")

        assert fabricas.chamadas_asyncio == 0

    def test_no_nt_o_loop_do_pool_vem_do_asyncio(self, pool, fabricas, monkeypatch):
        _setup_com_sistema(pool, monkeypatch, "nt")

        assert pool.loop is fabricas.loop_asyncio
        assert fabricas.chamadas_asyncio == 1

    def test_no_nt_o_uvloop_nao_e_usado(self, pool, fabricas, monkeypatch):
        _setup_com_sistema(pool, monkeypatch, "nt")

        assert fabricas.chamadas_uvloop == 0

    @pytest.mark.parametrize("sistema", ["posix", "nt"])
    def test_o_loop_do_pool_vira_o_loop_corrente_da_thread(self, pool, fabricas, monkeypatch, sistema):
        _setup_com_sistema(pool, monkeypatch, sistema)

        assert fabricas.loops_definidos == [pool.loop]

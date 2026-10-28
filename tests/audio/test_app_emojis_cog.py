"""Emojis de aplicação (#130), E7 e TM-E1: a cog ``cogs/app_emojis.py`` dispara o sync uma vez por bot, só nos bots principais por padrão.

Nomes que o Prism confirma: ``setup(bot)`` da cog, ``sync_app_emojis`` importado no módulo da cog, ``bot.app_emojis`` trocado de uma vez
quando o sync termina, e a chave de config ``APP_EMOJIS_GUILD_BOTS`` (propositada pelo Litmus) para ligar o sync nos bots de ``guild_bots.json``.
"""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.cogs import app_emojis as cog_modulo
from tests.support.emojis_app import NOMES

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

MAPA = {nome: f"<:{nome}:{100000000000000000 + i}>" for i, nome in enumerate(NOMES)}


def novo_bot(*, principal: bool = True, opt_in: bool = False, nome: str = "principal"):
    cogs = []
    config = {"APP_EMOJIS_GUILD_BOTS": opt_in}
    bot = SimpleNamespace(
        identifier=nome,
        app_emojis={},
        config=config,
        loop=asyncio.get_running_loop(),
        user=SimpleNamespace(id=7),
        add_cog=cogs.append,
        cogs_adicionadas=cogs,
    )
    bot.pool = SimpleNamespace(
        config=config, bots=[bot] if principal else [], guild_bots={} if principal else {"1": [bot]}
    )
    return bot


def cog_do(bot):
    cog_modulo.setup(bot)
    (cog,) = bot.cogs_adicionadas
    return cog


async def disparar_on_ready(cog, vezes: int = 1) -> None:
    ouvintes = [metodo for nome, metodo in cog.get_listeners() if nome == "on_ready"]
    assert len(ouvintes) == 1, "a cog precisa de exatamente um ouvinte de on_ready"
    for _ in range(vezes):
        await ouvintes[0]()
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.fixture
def sync(monkeypatch) -> AsyncMock:
    falso = AsyncMock(return_value=dict(MAPA))
    monkeypatch.setattr(cog_modulo, "sync_app_emojis", falso)
    return falso


class TestUmaVezPorBot:
    async def test_on_ready_twice_runs_one_sync(self, sync):
        bot = novo_bot()

        await disparar_on_ready(cog_do(bot), vezes=2)

        assert sync.await_count == 1

    async def test_the_bot_map_is_replaced_whole_when_the_sync_finishes(self, sync):
        bot = novo_bot()

        await disparar_on_ready(cog_do(bot))

        assert bot.app_emojis == MAPA

    async def test_while_the_sync_runs_the_map_stays_empty(self, monkeypatch):
        liberar = asyncio.Event()

        async def lento(*a, **k):
            await liberar.wait()
            return dict(MAPA)

        monkeypatch.setattr(cog_modulo, "sync_app_emojis", lento)
        bot = novo_bot()

        await disparar_on_ready(cog_do(bot))

        assert bot.app_emojis == {}
        liberar.set()
        for _ in range(10):
            await asyncio.sleep(0)
        assert bot.app_emojis == MAPA

    async def test_the_sync_receives_this_bot_and_the_emojis_folder(self, sync):
        bot = novo_bot()

        await disparar_on_ready(cog_do(bot))

        args, kwargs = sync.await_args
        assert args[0] is bot and isinstance(kwargs["emojis_dir"], Path) and kwargs["emojis_dir"].name == "emojis"

    async def test_two_bots_each_run_their_own_sync(self, sync):
        a, b = novo_bot(nome="a"), novo_bot(nome="b")

        await disparar_on_ready(cog_do(a))
        await disparar_on_ready(cog_do(b))

        assert sync.await_count == 2 and [c.args[0] for c in sync.await_args_list] == [a, b]


class TestFalhaNaoDerrubaOBot:
    @pytest.mark.parametrize(
        "erro", [RuntimeError("falha"), OSError("disco"), ValueError("x")], ids=lambda e: type(e).__name__
    )
    async def test_a_failing_sync_does_not_raise_and_leaves_the_map_empty(self, monkeypatch, erro):
        monkeypatch.setattr(cog_modulo, "sync_app_emojis", AsyncMock(side_effect=erro))
        bot = novo_bot()

        await disparar_on_ready(cog_do(bot))

        assert bot.app_emojis == {}

    async def test_the_failure_is_logged_without_the_exception_text_in_a_warning_or_error(self, monkeypatch, caplog):
        segredo = "".join(["texto-da-excecao-", "nao-vai-ao-log"])
        monkeypatch.setattr(cog_modulo, "sync_app_emojis", AsyncMock(side_effect=RuntimeError(segredo)))

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await disparar_on_ready(cog_do(novo_bot()))

        niveis = [r for r in caplog.records if r.name.startswith("empiremuse") and r.levelno >= logging.WARNING]
        assert niveis and all(segredo not in r.getMessage() for r in niveis)

    async def test_a_failed_sync_is_not_retried_by_a_second_on_ready(self, monkeypatch):
        falso = AsyncMock(side_effect=RuntimeError("falha"))
        monkeypatch.setattr(cog_modulo, "sync_app_emojis", falso)

        await disparar_on_ready(cog_do(novo_bot()), vezes=2)

        assert falso.await_count == 1


class TestInfoDaSubida:
    async def test_one_info_line_in_the_boot_logger_with_the_result(self, sync, caplog):
        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await disparar_on_ready(cog_do(novo_bot()))

        linhas = [r.getMessage() for r in caplog.records if r.name == "empiremuse.boot" and r.levelno == logging.INFO]
        assert len([linha for linha in linhas if "Emojis de aplicação" in linha]) == 1
        assert any("25" in linha for linha in linhas if "Emojis de aplicação" in linha)


class TestSoBotsPrincipaisPorPadrao:
    async def test_a_main_bot_syncs_by_default(self, sync):
        await disparar_on_ready(cog_do(novo_bot(principal=True)))

        assert sync.await_count == 1

    async def test_a_guild_bot_does_not_sync_by_default(self, sync):
        bot = novo_bot(principal=False)

        await disparar_on_ready(cog_do(bot))

        assert sync.await_count == 0 and bot.app_emojis == {}

    async def test_a_guild_bot_syncs_with_the_explicit_opt_in(self, sync):
        await disparar_on_ready(cog_do(novo_bot(principal=False, opt_in=True)))

        assert sync.await_count == 1

    async def test_the_opt_in_alone_does_not_change_a_main_bot(self, sync):
        await disparar_on_ready(cog_do(novo_bot(principal=True, opt_in=True)))

        assert sync.await_count == 1

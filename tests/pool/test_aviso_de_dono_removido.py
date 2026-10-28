"""2.1.2 (C) — o aviso "o dono não está nos servidores" saiu do ``update_appinfo``.

O bloco só calculava ``guilds`` e fazia ``logger.warning``: não dirigia saída de servidor, DM nem painel. O ``appinfo`` e o
``owner`` continuam preenchidos; a chave ``SILENT_PUBLICBOT_WARNING`` perdeu a razão de existir.
"""

import logging
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse import config_loader
from empiremuse.utils.client import BotCore

pytestmark = pytest.mark.regression

LOGGER_DO_CLIENTE = "empiremuse.utils.client"


def convidado(uid: int) -> SimpleNamespace:
    """Dono ou membro da equipe que NÃO está no servidor (``get_member`` devolve ``None``)."""
    return SimpleNamespace(id=uid)


class Servidor:
    """Servidor sem nenhum dono/equipe (hashable, como o ``disnake.Guild``)."""

    def __init__(self, sid: int) -> None:
        self.id, self.name = sid, f"Servidor {sid}"

    def get_member(self, _uid: int) -> None:
        return None


def bot_com(appinfo: SimpleNamespace, servidores: int, config: dict[str, object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        wait_until_ready=AsyncMock(),
        application_info=AsyncMock(return_value=appinfo),
        guilds=[Servidor(i) for i in range(servidores)],
        user=SimpleNamespace(id=7),
        config=config if config is not None else {},
    )


async def chamar(bot: SimpleNamespace) -> None:
    await BotCore.update_appinfo(bot)


class TestSemAvisoDeDono:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("silenciar", [False, True, None])
    async def test_a_public_bot_in_guilds_without_its_owner_logs_no_warning(
        self, caplog: pytest.LogCaptureFixture, silenciar: bool | None
    ) -> None:
        dono = convidado(5)
        appinfo = SimpleNamespace(bot_public=True, team=None, owner=dono)
        config = {} if silenciar is None else {"SILENT_PUBLICBOT_WARNING": silenciar}
        bot = bot_com(appinfo, servidores=12, config=config)

        with caplog.at_level(logging.DEBUG):
            await chamar(bot)

        avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert avisos == []

    @pytest.mark.asyncio
    async def test_a_team_without_manage_guild_in_the_guilds_logs_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        dono = convidado(5)
        equipe = SimpleNamespace(owner=dono, members=[dono, convidado(6)])
        bot = bot_com(SimpleNamespace(bot_public=True, team=equipe, owner=dono), servidores=3)

        with caplog.at_level(logging.DEBUG):
            await chamar(bot)

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    @pytest.mark.asyncio
    async def test_the_guild_list_is_not_walked_anymore(self) -> None:
        percorridos: list[int] = []

        class Servidores(list[Servidor]):
            def __iter__(self) -> Iterator[Servidor]:
                percorridos.append(1)
                return super().__iter__()

        dono = convidado(5)
        bot = bot_com(SimpleNamespace(bot_public=True, team=None, owner=dono), servidores=0)
        bot.guilds = Servidores([Servidor(1), Servidor(2)])

        await chamar(bot)

        assert percorridos == []


class TestAppinfoEDonoContinuam:
    @pytest.mark.asyncio
    async def test_a_solo_owner_fills_appinfo_and_owner(self) -> None:
        dono = convidado(5)
        appinfo = SimpleNamespace(bot_public=True, team=None, owner=dono)
        bot = bot_com(appinfo, servidores=2)

        await chamar(bot)

        assert bot.appinfo is appinfo and bot.owner is dono

    @pytest.mark.asyncio
    async def test_a_team_fills_owner_with_the_team_owner(self) -> None:
        dono = convidado(5)
        appinfo = SimpleNamespace(bot_public=True, team=SimpleNamespace(owner=dono, members=[dono]), owner=convidado(9))
        bot = bot_com(appinfo, servidores=2)

        await chamar(bot)

        assert bot.appinfo is appinfo and bot.owner is dono

    @pytest.mark.asyncio
    async def test_a_private_bot_also_fills_appinfo_and_owner(self) -> None:
        dono = convidado(5)
        appinfo = SimpleNamespace(bot_public=False, team=None, owner=dono)
        bot = bot_com(appinfo, servidores=2)

        await chamar(bot)

        assert bot.appinfo is appinfo and bot.owner is dono


def test_the_silent_publicbot_warning_key_left_the_default_config() -> None:
    assert "SILENT_PUBLICBOT_WARNING" not in config_loader.DEFAULT_CONFIG

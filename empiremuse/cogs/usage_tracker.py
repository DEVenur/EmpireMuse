# -*- coding: utf-8 -*-
"""Registro de uso: comandos de barra, de menu de contexto e de prefixo, e erros de botão/select do player.

Só escuta os eventos que o disnake já despacha; o ``UsageRecorder`` do pool põe o evento no buffer sem esperar o banco, então nada
aqui atrasa nem quebra um comando. Os botões que rodam um comando do player são registrados em ``process_player_interaction``, o
canal de pedidos em ``song_requests`` e o painel web nos tratadores de POST.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from disnake.ext import commands

from empiremuse.rules.usage import KIND_BUTTON, KIND_PREFIX, KIND_SLASH
from empiremuse.utils.music.errors import PoolException
from empiremuse.utils.usage import component_name, label_for, usage_of

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore


def _app_command_name(inter: object) -> str:
    command = getattr(inter, "application_command", None)
    return getattr(command, "qualified_name", None) or getattr(getattr(inter, "data", None), "name", "") or ""


class UsageTracker(commands.Cog):
    def __init__(self, bot: BotCore):
        self.bot = bot

    def _record(self, kind: str, name: str, source: object, error: BaseException | None = None) -> None:
        if (usage := usage_of(self.bot)) is None or not name:
            return
        bot = getattr(source, "music_bot", None) or self.bot
        usage.record_command(
            kind, name, source, bot=bot, ok=error is None, error=None if error is None else label_for(error)
        )

    @commands.Cog.listener("on_slash_command_completion")
    @commands.Cog.listener("on_user_command_completion")
    @commands.Cog.listener("on_message_command_completion")
    async def app_command_done(self, inter):
        self._record(KIND_SLASH, _app_command_name(inter), inter)

    @commands.Cog.listener("on_slash_command_error")
    @commands.Cog.listener("on_user_command_error")
    @commands.Cog.listener("on_message_command_error")
    async def app_command_failed(self, inter, error: Exception):
        if not isinstance(error, PoolException):
            self._record(KIND_SLASH, _app_command_name(inter), inter, error)

    @commands.Cog.listener("on_command_completion")
    async def prefix_command_done(self, ctx):
        self._record(KIND_PREFIX, getattr(ctx.command, "qualified_name", ""), ctx)

    @commands.Cog.listener("on_command_error")
    async def prefix_command_failed(self, ctx, error: Exception):
        if ctx.command is not None and not isinstance(error, PoolException):
            self._record(KIND_PREFIX, ctx.command.qualified_name, ctx, error)

    @commands.Cog.listener("on_interaction_player_error")
    async def player_component_failed(self, inter, error: Exception):
        if not isinstance(error, PoolException):
            self._record(KIND_BUTTON, component_name(inter), inter, error)


def setup(bot: BotCore):
    bot.add_cog(UsageTracker(bot))

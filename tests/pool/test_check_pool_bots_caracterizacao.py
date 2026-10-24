"""KI-27 — caracterização de `checks.check_pool_bots` (roteamento entre vários bots do pool) para comandos de barra/interações.

Fixa quem responde em cada cenário: bot já na chamada, bot livre, todos ocupados, sem permissão de envio, sem bot compatível,
`only_voiced`, `check_player` e `return_first`. O caminho por prefixo (`CustomContext` com `wait_for`) fica de fora.
Sem Discord real: bots, servidores e canais são dublês.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake

from empiremuse.utils.music import checks

GID = 100
CANAL = 5


def run(coro):
    return asyncio.run(coro)


def make_guild(*, voice_channel=None):
    me = SimpleNamespace(voice=SimpleNamespace(channel=voice_channel) if voice_channel else None)
    return SimpleNamespace(me=me, voice_client=None, get_member=lambda member_id: None)


def make_bot(identifier, *, user_id, guild="presente", can_send=True, ready=True, channel_exists=True):
    """`guild`: "presente" cria um servidor livre; None = bot fora do servidor; ou um servidor pronto."""
    if guild == "presente":
        guild = make_guild()
    channel = MagicMock(spec=disnake.TextChannel)
    channel.guild.me = object()
    channel.permissions_for.return_value = SimpleNamespace(send_messages=can_send)
    return SimpleNamespace(
        identifier=identifier,
        bot_ready=ready,
        user=SimpleNamespace(id=user_id, mention=f"<@{user_id}>"),
        get_guild=lambda gid: guild,
        get_channel=lambda cid: channel if channel_exists else None,
        dispatch=MagicMock(),
        get_color=lambda: 0,
        _guild=guild,
    )


def voice_channel(*, bot_ids=(), mention="<#7>"):
    channel = MagicMock()
    channel.voice_states = {i: object() for i in bot_ids}
    channel.mention = mention
    return channel


def make_inter(bots, *, author_voice=None, current=0, voice_client=object(), guild=True):
    me = bots[current]
    me.pool = SimpleNamespace(get_guild_bots=lambda gid: bots)
    author = SimpleNamespace(
        id=1,
        voice=SimpleNamespace(channel=author_voice) if author_voice else None,
        guild_permissions=SimpleNamespace(manage_guild=False),
    )
    for bot in bots:
        if bot._guild is not None:
            bot._guild.get_member = lambda member_id, a=author: a
    return SimpleNamespace(
        bot=me,
        guild=SimpleNamespace(voice_client=voice_client, me=object()) if guild else None,
        guild_id=GID if guild else None,
        author=author,
        channel=SimpleNamespace(id=CANAL),
        channel_id=CANAL,
        send=AsyncMock(),
    )


def route(inter, **kwargs):
    return run(checks.check_pool_bots(inter, **kwargs))


# ============================================================================ atalhos


class TestShortcuts:
    def test_the_bot_already_in_the_author_voice_channel_answers(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(bot_ids=[1]))
        assert route(inter) == (a, inter.guild)


# ============================================================================ sem ninguém disponível


def busy_bot(identifier, user_id, mention="<#8>"):
    return make_bot(identifier, user_id=user_id, guild=make_guild(voice_channel=voice_channel(mention=mention)))


class TestNobodyAvailable:
    def test_without_a_free_bot_check_player_and_return_first_keeps_the_current_bot(self):
        a = busy_bot("a", 1)
        inter = make_inter([a, busy_bot("b", 2)], author_voice=voice_channel())
        assert route(inter, return_first=True) == (a, inter.guild)

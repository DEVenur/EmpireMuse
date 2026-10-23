"""KI-27 — caracterização de `checks.check_pool_bots` (roteamento entre vários bots do pool) para comandos de barra/interações.

Fixa quem responde em cada cenário: bot já na chamada, bot livre, todos ocupados, sem permissão de envio, sem bot compatível,
`only_voiced`, `check_player` e `return_first`. O caminho por prefixo (`CustomContext` com `wait_for`) fica de fora.
Sem Discord real: bots, servidores e canais são dublês.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils.music import checks
from empiremuse.utils.music.errors import GenericError, NoPlayer, NoVoice, PoolException

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
    def test_music_bot_already_chosen_is_reused(self):
        inter = SimpleNamespace(music_bot="bot", music_guild="guild")
        assert route(inter) == ("bot", "guild")

    def test_bypass_attribute_ignores_the_chosen_bot(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(bot_ids=[2]))
        inter.music_bot, inter.music_guild = "velho", "velho"
        bot, _ = route(inter, bypass_attribute=True)
        assert bot is b

    def test_modal_interactions_keep_the_current_bot(self):
        modal = MagicMock(spec=disnake.ModalInteraction)
        modal.bot, modal.guild = "bot", "guild"
        del modal.music_bot
        assert route(modal) == ("bot", "guild")

    def test_a_single_bot_in_the_guild_answers(self):
        solo = make_bot("a", user_id=1)
        inter = make_inter([solo])
        assert route(inter) == (solo, inter.guild)

    def test_private_messages_with_several_bots_are_refused(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], guild=False)
        with pytest.raises(GenericError, match="mensagens privada"):
            route(inter)

    def test_the_bot_already_in_the_author_voice_channel_answers(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(bot_ids=[1]))
        assert route(inter) == (a, inter.guild)


# ============================================================================ escolha entre bots


class TestPickingABot:
    def test_another_bot_already_with_the_author_answers(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(bot_ids=[2]))
        bot, guild = route(inter)
        assert bot is b and guild is b._guild
        assert inter.music_bot is b

    def test_free_bot_is_chosen_in_identifier_order(self):
        a, b = make_bot("b", user_id=1), make_bot("a", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(), current=0)
        bot, _ = route(inter, check_player=False)
        assert bot is b  # o identificador "a" vem antes de "b"

    def test_bot_with_a_session_elsewhere_is_not_free(self):
        a = make_bot("a", user_id=1, guild=make_guild(voice_channel=voice_channel(mention="<#8>")))
        b = make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(), current=0)
        bot, _ = route(inter, check_player=False)
        assert bot is b

    def test_bot_without_send_permission_is_skipped(self):
        a = make_bot("a", user_id=1, can_send=False)
        b = make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel())
        bot, _ = route(inter, check_player=False)
        assert bot is b

    def test_bot_that_cannot_see_the_channel_is_skipped(self):
        a = make_bot("a", user_id=1, channel_exists=False)
        b = make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel())
        bot, _ = route(inter, check_player=False)
        assert bot is b

    def test_bots_not_ready_are_ignored(self):
        a = make_bot("a", user_id=1, ready=False)
        b = make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel())
        bot, _ = route(inter, check_player=False)
        assert bot is b

    def test_thread_channels_use_the_parent_permission(self):
        a = make_bot("a", user_id=1)
        thread = MagicMock(spec=disnake.Thread)
        thread.guild.me = object()
        thread.parent.permissions_for.return_value = SimpleNamespace(send_messages_in_threads=False)
        a.get_channel = lambda cid: thread
        b = make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel())
        bot, _ = route(inter, check_player=False)
        assert bot is b


# ============================================================================ sem ninguém disponível


def busy_bot(identifier, user_id, mention="<#8>"):
    return make_bot(identifier, user_id=user_id, guild=make_guild(voice_channel=voice_channel(mention=mention)))


class TestNobodyAvailable:
    def test_author_outside_voice_is_asked_to_join(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b])
        with pytest.raises(NoVoice):
            route(inter)
        a.dispatch.assert_called_with("pool_dispatch", inter, None)

    def test_return_first_falls_back_to_the_current_bot_without_a_voice_client(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], voice_client=None)
        bot, _ = route(inter, return_first=True)
        assert bot is a

    def test_only_voiced_without_a_voice_client_raises_no_player(self):
        a, b = make_bot("a", user_id=1), make_bot("b", user_id=2)
        inter = make_inter([a, b], author_voice=voice_channel(), voice_client=None)
        with pytest.raises(NoPlayer):
            route(inter, only_voiced=True)
        a.dispatch.assert_called_with("pool_dispatch", None, None)

    def test_without_a_free_bot_and_check_player_raises_no_player(self):
        inter = make_inter([busy_bot("a", 1), busy_bot("b", 2)], author_voice=voice_channel())
        with pytest.raises(NoPlayer):
            route(inter)

    def test_without_a_free_bot_check_player_and_return_first_keeps_the_current_bot(self):
        a = busy_bot("a", 1)
        inter = make_inter([a, busy_bot("b", 2)], author_voice=voice_channel())
        assert route(inter, return_first=True) == (a, inter.guild)

    def test_all_busy_lists_the_active_sessions_and_raises_pool_exception(self):
        inter = make_inter([busy_bot("a", 1), busy_bot("b", 2)], author_voice=voice_channel())
        with pytest.raises(PoolException):
            route(inter, check_player=False)
        embed = inter.send.await_args.kwargs["embed"]
        assert "Todos os bots estão em uso" in embed.description and "<#8>" in embed.description

    def test_missing_send_permission_is_reported_with_the_bot_mentions(self):
        a, b = make_bot("a", user_id=1, can_send=False), make_bot("b", user_id=2, can_send=False)
        inter = make_inter([a, b], author_voice=voice_channel())
        with pytest.raises(PoolException):
            route(inter, check_player=False)
        description = inter.send.await_args.kwargs["embed"].description
        assert "sem permissão de enviar mensagens" in description and "<@1>" in description and "<@2>" in description

    def test_extra_bots_outside_the_guild_offer_the_invite_button_to_admins(self):
        inter = make_inter([busy_bot("a", 1), make_bot("c", user_id=3, guild=None)], author_voice=voice_channel())
        inter.author.guild_permissions = SimpleNamespace(manage_guild=True)
        with pytest.raises(PoolException):
            route(inter, check_player=False)
        kwargs = inter.send.await_args.kwargs
        assert "adicionar mais bots" in kwargs["embed"].description
        assert kwargs["components"][0].custom_id == "bot_invite"

    def test_extra_bots_ask_members_to_call_an_admin(self):
        inter = make_inter([busy_bot("a", 1), make_bot("c", user_id=3, guild=None)], author_voice=voice_channel())
        with pytest.raises(PoolException):
            route(inter, check_player=False)
        assert "administrador/manager" in inter.send.await_args.kwargs["embed"].description

    def test_no_compatible_bot_in_the_guild_ends_in_no_voice_for_slash_commands(self):
        # `user_vc` só vira True dentro do laço de bots presentes no servidor: sem nenhum, a mensagem "Não há bots de música
        # compatíveis" fica inalcançável por interações e o usuário recebe NoVoice (só o caminho por prefixo marca user_vc antes).
        bots = [make_bot(n, user_id=i, guild=None) for i, n in enumerate("abc", start=1)]
        inter = make_inter(bots, author_voice=voice_channel())
        with pytest.raises(NoVoice):
            route(inter, check_player=False)
        inter.send.assert_not_awaited()

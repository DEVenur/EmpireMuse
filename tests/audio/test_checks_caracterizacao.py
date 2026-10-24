"""KI-27 — caracterização de `empiremuse/utils/music/checks.py` (checks de comandos: player, DJ, voz, canal e cooldowns).

Fixa o comportamento atual, sem mudar produção. Sem Discord real: dublês (SimpleNamespace / MagicMock com spec / AsyncMock).
Os checks do disnake expõem a função original em `.predicate`.
"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils.music import checks
from empiremuse.utils.music.errors import GenericError, NoPlayer

GID = 100


def run(coro):
    return asyncio.run(coro)


def call(check, inter):
    return run(check.predicate(inter))


def perms(**kwargs):
    return SimpleNamespace(**kwargs)


def make_player(**kwargs):
    base = dict(
        current=SimpleNamespace(requester=1, info={"sourceName": "youtube"}),
        locked=False,
        node=SimpleNamespace(is_available=True),
        keep_connected=False,
        restrict_mode=False,
        player_creator=None,
        dj=set(),
        last_channel=None,
        guild_id=GID,
        channel_id=5,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def make_inter(players=None, **kwargs):
    bot = SimpleNamespace(
        music=SimpleNamespace(players=players if players is not None else {}),
        config={"YOUTUBE_TRACK_COOLDOWN": 10},
        is_owner=AsyncMock(return_value=False),
    )
    base = dict(guild_id=GID, bot=bot, author=SimpleNamespace(id=1, mention="<@1>"))
    base.update(kwargs)
    return SimpleNamespace(**base)


# ============================================================================ can_send_message


# ============================================================================ has_player / has_source / is_requester


class TestHasSource:
    def test_without_player(self):
        with pytest.raises(NoPlayer):
            call(checks.has_source(), make_inter())


# ============================================================================ check_voice


# ============================================================================ check_yt_cooldown / check_stage_topic


def started_ago(seconds):
    return disnake.utils.utcnow() - timedelta(seconds=seconds)


class TestCheckStageTopic:
    def stage_player(self, channel_spec, **kwargs):
        channel = MagicMock(spec=channel_spec)
        me = SimpleNamespace(voice=SimpleNamespace(channel=channel))
        return make_player(guild=SimpleNamespace(me=me), stage_title_event=True, start_time=started_ago(5), **kwargs)

    def test_bot_outside_voice(self):
        player = make_player(guild=SimpleNamespace(me=SimpleNamespace(voice=None)))
        with pytest.raises(NoPlayer):
            call(checks.check_stage_topic(), make_inter({GID: player}))


# ============================================================================ canais de voz


def make_voice_channel(
    spec=disnake.VoiceChannel, connect=True, speak=True, user_limit=0, voice_states=None, members=()
):
    channel = MagicMock(spec=spec)
    channel.mention = "<#7>"
    channel.id = 7
    channel.user_limit = user_limit
    channel.voice_states = voice_states if voice_states is not None else {}
    channel.members = list(members)
    channel.permissions_for.return_value = perms(connect=connect, speak=speak)
    return channel


class TestCanConnect:
    def guild(self, voice_client=None):
        return SimpleNamespace(
            me=SimpleNamespace(id=50, guild_permissions=perms(move_members=False)), voice_client=voice_client
        )

    def test_other_bots_in_vc_are_refused_when_requested(self):
        outro = SimpleNamespace(bot=True, id=61)
        channel = make_voice_channel(members=[outro])
        with pytest.raises(GenericError, match="outro bot"):
            checks.can_connect(channel, self.guild(), check_other_bots_in_vc=True)


# ============================================================================ get_available_bots_info / check_player_perm


def make_pool(bots):
    return SimpleNamespace(get_guild_bots=lambda gid: bots)


class TestGetAvailableBotsInfo:
    MEMBER = SimpleNamespace(guild_permissions=perms(manage_guild=False))

    def test_session_in_247_mode_is_not_suggested(self):
        player = make_player(keep_connected=True, last_channel=MagicMock())
        bot = SimpleNamespace(bot_ready=True, music=SimpleNamespace(players={GID: player}))
        assert checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER) == ("", [])

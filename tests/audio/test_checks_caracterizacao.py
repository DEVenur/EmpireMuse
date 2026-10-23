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
from empiremuse.utils.music.errors import (
    DiffVoiceChannel,
    GenericError,
    MissingVoicePerms,
    NoPlayer,
    NotDJorStaff,
    NotRequester,
    NoSource,
    NoVoice,
    PoolException,
)

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


def make_text_channel(send=True, embed=True):
    channel = MagicMock(spec=disnake.TextChannel)
    channel.mention = "<#9>"
    channel.guild.me = MagicMock()
    channel.permissions_for.return_value = perms(send_messages=send, embed_links=embed)
    return channel


class TestCanSendMessage:
    BOT = SimpleNamespace(mention="<@bot>")

    def test_allows_when_it_can_send_and_embed(self):
        assert checks.can_send_message(make_text_channel(), self.BOT) is True

    def test_refuses_without_send_messages(self):
        with pytest.raises(GenericError, match="enviar mensagens"):
            checks.can_send_message(make_text_channel(send=False), self.BOT)

    def test_refuses_without_embed_links(self):
        with pytest.raises(GenericError, match="inserir links"):
            checks.can_send_message(make_text_channel(embed=False), self.BOT)

    def test_thread_uses_the_permission_of_the_parent_channel(self):
        thread = MagicMock(spec=disnake.Thread)
        thread.mention = "<#8>"
        thread.parent.permissions_for.return_value = perms(send_messages_in_threads=False)
        with pytest.raises(GenericError, match="enviar mensagens"):
            checks.can_send_message(thread, self.BOT)


# ============================================================================ has_player / has_source / is_requester


class TestHasPlayer:
    def test_returns_true_with_player_and_available_node(self):
        assert call(checks.has_player(), make_inter({GID: make_player()})) is True

    def test_no_player(self):
        with pytest.raises(NoPlayer):
            call(checks.has_player(), make_inter())

    def test_unavailable_node_raises_zero_connected_nodes(self):
        import empiremuse.wavelink as wavelink

        player = make_player(node=SimpleNamespace(is_available=False))
        with pytest.raises(wavelink.ZeroConnectedNodes):
            call(checks.has_player(), make_inter({GID: player}))

    def test_unavailable_node_is_ignored_with_check_node_false(self):
        player = make_player(node=SimpleNamespace(is_available=False))
        assert call(checks.has_player(check_node=False), make_inter({GID: player})) is True

    def test_uses_music_bot_when_the_interaction_has_one(self):
        other = SimpleNamespace(music=SimpleNamespace(players={GID: make_player()}))
        inter = make_inter(music_bot=other)
        assert call(checks.has_player(), inter) is True


class TestHasSource:
    def test_with_current_track(self):
        assert call(checks.has_source(), make_inter({GID: make_player()})) is True

    def test_without_current_track(self):
        with pytest.raises(NoSource):
            call(checks.has_source(), make_inter({GID: make_player(current=None)}))

    def test_without_player(self):
        with pytest.raises(NoPlayer):
            call(checks.has_source(), make_inter())


class TestCheckQueueLoading:
    def test_free_player(self):
        assert call(checks.check_queue_loading(), make_inter({GID: make_player()})) is True

    def test_locked_player_asks_to_wait(self):
        with pytest.raises(GenericError, match="aguarde"):
            call(checks.check_queue_loading(), make_inter({GID: make_player(locked=True)}))

    def test_without_player(self):
        with pytest.raises(NoPlayer):
            call(checks.check_queue_loading(), make_inter())


class TestIsRequester:
    def test_requester_passes_without_dj_lookup(self):
        inter = make_inter({GID: make_player()})
        assert call(checks.is_requester(), inter) is True

    def test_without_player(self):
        with pytest.raises(NoPlayer):
            call(checks.is_requester(), make_inter())

    def test_without_current_track(self):
        with pytest.raises(NoSource):
            call(checks.is_requester(), make_inter({GID: make_player(current=None)}))

    def test_other_member_with_dj_permission_passes(self, monkeypatch):
        monkeypatch.setattr(checks, "has_perm", AsyncMock(return_value=True))
        inter = make_inter({GID: make_player()}, author=SimpleNamespace(id=2))
        assert call(checks.is_requester(), inter) is True

    def test_other_member_without_dj_is_not_the_requester(self, monkeypatch):
        monkeypatch.setattr(checks, "has_perm", AsyncMock(side_effect=NotDJorStaff()))
        inter = make_inter({GID: make_player()}, author=SimpleNamespace(id=2))
        with pytest.raises(NotRequester):
            call(checks.is_requester(), inter)


class TestIsDj:
    def test_passes_when_has_perm(self, monkeypatch):
        monkeypatch.setattr(checks, "has_perm", AsyncMock(return_value=True))
        assert call(checks.is_dj(), make_inter()) is True

    def test_refuses_when_has_perm_is_falsy(self, monkeypatch):
        monkeypatch.setattr(checks, "has_perm", AsyncMock(return_value=False))
        with pytest.raises(NotDJorStaff):
            call(checks.is_dj(), make_inter())


# ============================================================================ check_voice


def make_member(in_voice=True, connect=True, in_my_channel=True):
    channel = MagicMock()
    channel.permissions_for.return_value = perms(connect=connect)
    author = SimpleNamespace(id=1, voice=SimpleNamespace(channel=channel) if in_voice else None)
    me_channel = SimpleNamespace(voice_states={1: object()} if in_my_channel else {})
    return author, me_channel


class TestCheckVoice:
    def test_author_not_in_voice(self):
        author, _ = make_member(in_voice=False)
        guild = SimpleNamespace(me=SimpleNamespace(voice=None))
        with pytest.raises(NoVoice):
            call(checks.check_voice(), make_inter(author=author, guild=guild))

    def test_bot_not_connected_and_no_connect_permission(self):
        author, _ = make_member(connect=False)
        guild = SimpleNamespace(me=SimpleNamespace(voice=None))
        with pytest.raises(MissingVoicePerms):
            call(checks.check_voice(), make_inter(author=author, guild=guild))

    def test_bot_not_connected_with_permission_passes(self):
        author, _ = make_member()
        guild = SimpleNamespace(me=SimpleNamespace(voice=None))
        assert call(checks.check_voice(), make_inter(author=author, guild=guild)) is True

    def test_author_in_a_different_channel(self):
        author, me_channel = make_member(in_my_channel=False)
        guild = SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=me_channel)))
        with pytest.raises(DiffVoiceChannel):
            call(checks.check_voice(), make_inter(author=author, guild=guild))

    def test_author_in_the_same_channel(self):
        author, me_channel = make_member()
        guild = SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=me_channel)))
        assert call(checks.check_voice(), make_inter(author=author, guild=guild)) is True

    def test_prefers_music_guild_over_guild(self):
        author, me_channel = make_member(in_my_channel=False)
        music_guild = SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=me_channel)))
        wrong = SimpleNamespace(me=SimpleNamespace(voice=None))
        with pytest.raises(DiffVoiceChannel):
            call(checks.check_voice(), make_inter(author=author, guild=wrong, music_guild=music_guild))


# ============================================================================ check_yt_cooldown / check_stage_topic


def started_ago(seconds):
    return disnake.utils.utcnow() - timedelta(seconds=seconds)


class TestCheckYtCooldown:
    def test_without_player_passes(self):
        assert call(checks.check_yt_cooldown(), make_inter()) is True

    def test_youtube_track_inside_the_cooldown_blocks_a_regular_member(self):
        player = make_player(start_time=started_ago(2))
        with pytest.raises(GenericError, match="pular a música atual do youtube"):
            call(checks.check_yt_cooldown(), make_inter({GID: player}))

    def test_owner_is_exempt(self):
        inter = make_inter({GID: make_player(start_time=started_ago(2))})
        inter.bot.is_owner = AsyncMock(return_value=True)
        assert call(checks.check_yt_cooldown(), inter) is True

    def test_after_the_cooldown_passes(self):
        player = make_player(start_time=started_ago(60))
        assert call(checks.check_yt_cooldown(), make_inter({GID: player})) is True

    def test_other_sources_are_never_blocked(self):
        current = SimpleNamespace(requester=1, info={"sourceName": "soundcloud"})
        player = make_player(current=current, start_time=started_ago(1))
        assert call(checks.check_yt_cooldown(), make_inter({GID: player})) is True


class TestCheckStageTopic:
    def stage_player(self, channel_spec, **kwargs):
        channel = MagicMock(spec=channel_spec)
        me = SimpleNamespace(voice=SimpleNamespace(channel=channel))
        return make_player(guild=SimpleNamespace(me=me), stage_title_event=True, start_time=started_ago(5), **kwargs)

    def test_without_player(self):
        with pytest.raises(NoPlayer):
            call(checks.check_stage_topic(), make_inter())

    def test_bot_outside_voice(self):
        player = make_player(guild=SimpleNamespace(me=SimpleNamespace(voice=None)))
        with pytest.raises(NoPlayer):
            call(checks.check_stage_topic(), make_inter({GID: player}))

    def test_active_announcement_makes_a_member_wait(self):
        player = self.stage_player(disnake.VoiceChannel)
        with pytest.raises(GenericError, match="aguardar"):
            call(checks.check_stage_topic(), make_inter({GID: player}))

    def test_stage_channel_uses_the_longer_limit(self):
        player = self.stage_player(disnake.StageChannel)
        player.start_time = started_ago(60)  # além dos 30 s do canal de voz, dentro dos 120 s do palco
        with pytest.raises(GenericError):
            call(checks.check_stage_topic(), make_inter({GID: player}))

    def test_voice_channel_passes_after_its_shorter_limit(self):
        player = self.stage_player(disnake.VoiceChannel)
        player.start_time = started_ago(60)
        assert call(checks.check_stage_topic(), make_inter({GID: player})) is True

    def test_without_announcement_passes(self):
        player = self.stage_player(disnake.VoiceChannel)
        player.stage_title_event = False
        assert call(checks.check_stage_topic(), make_inter({GID: player})) is True

    def test_owner_is_exempt(self):
        player = self.stage_player(disnake.VoiceChannel)
        inter = make_inter({GID: player})
        inter.bot.is_owner = AsyncMock(return_value=True)
        assert call(checks.check_stage_topic(), inter) is True


# ============================================================================ can_send_message_check


class TestCanSendMessageCheck:
    def test_dm_without_guild_id_is_refused(self):
        inter = make_inter(guild=None, guild_id=None)
        with pytest.raises(GenericError, match="servidor"):
            call(checks.can_send_message_check(), inter)

    def test_user_install_with_guild_id_but_no_guild_passes(self):
        assert call(checks.can_send_message_check(), make_inter(guild=None)) is True

    def test_checks_the_channel_permissions(self):
        guild = SimpleNamespace(me=SimpleNamespace(mention="<@bot>"))
        inter = make_inter(guild=guild, channel=make_text_channel())
        assert call(checks.can_send_message_check(), inter) is True

    def test_missing_permission_is_reported(self):
        guild = SimpleNamespace(me=SimpleNamespace(mention="<@bot>"))
        inter = make_inter(guild=guild, channel=make_text_channel(send=False))
        with pytest.raises(GenericError):
            call(checks.can_send_message_check(), inter)

    def test_partial_messageable_is_resolved_and_unarchived(self):
        thread = MagicMock(spec=disnake.Thread)
        thread.locked = False
        thread.archived = True
        thread.owner_id = 77
        thread.edit = AsyncMock()
        thread.mention = "<#8>"
        thread.parent.permissions_for.return_value = perms(send_messages_in_threads=True)
        thread.permissions_for.return_value = perms(embed_links=True)
        guild = SimpleNamespace(me=SimpleNamespace(mention="<@bot>"))
        bot = SimpleNamespace(user=SimpleNamespace(id=77), fetch_channel=AsyncMock(return_value=thread))
        inter = make_inter(
            guild=guild,
            channel=MagicMock(spec=disnake.PartialMessageable),
            channel_id=8,
            response=SimpleNamespace(defer=AsyncMock()),
            bot=bot,
        )

        assert call(checks.can_send_message_check(), inter) is True
        thread.edit.assert_awaited_once_with(archived=False)

    def test_fetch_failure_is_swallowed_before_the_permission_check(self):
        guild = SimpleNamespace(me=SimpleNamespace(mention="<@bot>"))
        inter = make_inter(
            guild=guild,
            channel=MagicMock(spec=disnake.PartialMessageable),
            channel_id=8,
            response=SimpleNamespace(defer=AsyncMock(side_effect=RuntimeError("boom"))),
        )
        # a falha do defer/fetch não vaza; o erro vem da checagem de permissão no canal parcial (sem permissions_for)
        with pytest.raises(AttributeError):
            call(checks.can_send_message_check(), inter)


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


class TestCheckChannelLimit:
    def test_unlimited_channel(self):
        member = SimpleNamespace(id=1, guild_permissions=perms(move_members=False))
        assert checks.check_channel_limit(member, make_voice_channel()) is True

    def test_member_with_move_members_bypasses(self):
        member = SimpleNamespace(id=1, guild_permissions=perms(move_members=True))
        assert checks.check_channel_limit(member, make_voice_channel(user_limit=1, voice_states={2: 0})) is True

    def test_member_already_inside_bypasses(self):
        member = SimpleNamespace(id=1, guild_permissions=perms(move_members=False))
        assert checks.check_channel_limit(member, make_voice_channel(user_limit=1, voice_states={1: 0})) is True

    def test_room_left(self):
        member = SimpleNamespace(id=1, guild_permissions=perms(move_members=False))
        assert checks.check_channel_limit(member, make_voice_channel(user_limit=3, voice_states={2: 0})) is True

    def test_full_channel_returns_none(self):
        member = SimpleNamespace(id=1, guild_permissions=perms(move_members=False))
        assert checks.check_channel_limit(member, make_voice_channel(user_limit=1, voice_states={2: 0})) is None


class TestCanConnect:
    def guild(self, voice_client=None):
        return SimpleNamespace(
            me=SimpleNamespace(id=50, guild_permissions=perms(move_members=False)), voice_client=voice_client
        )

    def test_without_connect_permission(self):
        with pytest.raises(GenericError, match="conectar"):
            checks.can_connect(make_voice_channel(connect=False), self.guild())

    def test_without_speak_permission(self):
        with pytest.raises(GenericError, match="falar"):
            checks.can_connect(make_voice_channel(speak=False), self.guild())

    def test_stage_channel_does_not_need_speak(self):
        assert checks.can_connect(make_voice_channel(disnake.StageChannel, speak=False), self.guild()) is None

    def test_full_channel(self):
        channel = make_voice_channel(user_limit=1, voice_states={2: 0})
        with pytest.raises(GenericError, match="lotado"):
            checks.can_connect(channel, self.guild())

    def test_existing_voice_client_skips_the_limit_check(self):
        channel = make_voice_channel(user_limit=1, voice_states={2: 0})
        assert checks.can_connect(channel, self.guild(voice_client=object())) is None

    def test_another_pool_bot_in_the_channel_raises_pool_exception(self):
        other = SimpleNamespace(bot_ready=True, user=SimpleNamespace(id=60))
        bot = SimpleNamespace()
        bot.pool = SimpleNamespace(get_guild_bots=lambda gid: [bot, other])
        channel = make_voice_channel(voice_states={60: 0})
        channel.guild = SimpleNamespace(id=GID)
        with pytest.raises(PoolException):
            checks.can_connect(channel, self.guild(), bot=bot)

    def test_other_bots_in_vc_are_refused_when_requested(self):
        outro = SimpleNamespace(bot=True, id=61)
        channel = make_voice_channel(members=[outro])
        with pytest.raises(GenericError, match="outro bot"):
            checks.can_connect(channel, self.guild(), check_other_bots_in_vc=True)

    def test_own_bot_in_vc_is_ignored(self):
        eu = SimpleNamespace(bot=True, id=50)
        channel = make_voice_channel(members=[eu])
        assert checks.can_connect(channel, self.guild(), check_other_bots_in_vc=True) is None


class TestCheckDeafen:
    def test_already_deaf(self):
        me = SimpleNamespace(voice=SimpleNamespace(deaf=True))
        assert run(checks.check_deafen(me)) is True

    def test_deafens_when_it_can(self):
        me = SimpleNamespace(
            voice=SimpleNamespace(deaf=False), guild_permissions=perms(deafen_members=True), edit=AsyncMock()
        )
        assert run(checks.check_deafen(me)) is True
        me.edit.assert_awaited_once_with(deafen=True)

    def test_edit_failure_returns_none(self, capsys):
        me = SimpleNamespace(
            voice=SimpleNamespace(deaf=False),
            guild_permissions=perms(deafen_members=True),
            edit=AsyncMock(side_effect=RuntimeError("falhou")),
        )
        assert run(checks.check_deafen(me)) is None

    def test_without_permission_returns_none(self):
        me = SimpleNamespace(voice=SimpleNamespace(deaf=False), guild_permissions=perms(deafen_members=False))
        assert run(checks.check_deafen(me)) is None


# ============================================================================ utilitários


class TestUpdateAttrAndCooldown:
    def test_update_attr_sets_music_bot_and_guild(self):
        inter = SimpleNamespace()
        assert checks.update_attr(inter, "bot", "guild") == ("bot", "guild")
        assert (inter.music_bot, inter.music_guild) == ("bot", "guild")

    def test_update_attr_tolerates_objects_that_reject_attributes(self):
        class Fechado:
            __slots__ = ()

        assert checks.update_attr(Fechado(), "bot", "guild") == ("bot", "guild")

    def test_user_cooldown_builds_the_configured_cooldown(self):
        cooldown = checks.user_cooldown(3, 20)(SimpleNamespace())
        assert (cooldown.rate, cooldown.per) == (3, 20)


class TestCheckForum:
    def test_post_owned_by_the_bot_is_adopted(self):
        bot = SimpleNamespace(user=SimpleNamespace(id=9), check_bot_forum_post=lambda ch, raise_error: False)
        inter = SimpleNamespace(channel=SimpleNamespace(owner_id=9), guild="g")
        assert checks.check_forum(inter, bot) is True
        assert (inter.music_bot, inter.music_guild) == (bot, "g")

    def test_post_owned_by_another_bot_raises_pool_exception(self):
        bot = SimpleNamespace(user=SimpleNamespace(id=9), check_bot_forum_post=lambda ch, raise_error: False)
        inter = SimpleNamespace(channel=SimpleNamespace(owner_id=1), guild="g")
        with pytest.raises(PoolException):
            checks.check_forum(inter, bot)

    def test_valid_forum_post_returns_none(self):
        bot = SimpleNamespace(check_bot_forum_post=lambda ch, raise_error: True)
        assert checks.check_forum(SimpleNamespace(channel=None), bot) is None


# ============================================================================ check_requester_channel


class TestCheckRequesterChannel:
    def ctx(self, controller_channel, channel, other_bots=()):
        async def get_data(guild_id, db_name):
            return {"player_controller": {"channel": controller_channel}}

        bot = SimpleNamespace(
            get_data=get_data,
            pool=SimpleNamespace(get_guild_bots=lambda gid: list(other_bots)),
            user=SimpleNamespace(id=9),
        )
        return SimpleNamespace(bot=bot, guild_id=GID, channel=channel, author=SimpleNamespace())

    def test_channel_that_is_not_a_request_channel_passes(self):
        ctx = self.ctx("1", SimpleNamespace(id=2))
        assert run(checks.check_requester_channel(ctx)) is True

    def test_request_channel_without_parent_refuses_nothing(self):
        ctx = self.ctx("2", SimpleNamespace(id=2))
        assert run(checks.check_requester_channel(ctx)) is True

    def test_request_channel_with_a_text_parent_refuses_prefix_commands(self):
        ctx = self.ctx("2", SimpleNamespace(id=2, parent=MagicMock(spec=disnake.TextChannel)))
        with pytest.raises(GenericError, match="comandos de barra"):
            run(checks.check_requester_channel(ctx))

    def test_request_channel_of_another_pool_bot_also_refuses(self):
        async def other_data(guild_id, db_name):
            return {"player_controller": {"channel": "2"}}

        other = SimpleNamespace(get_data=other_data)
        ctx = self.ctx("1", SimpleNamespace(id=2), other_bots=[other])
        with pytest.raises(GenericError, match="comandos de barra"):
            run(checks.check_requester_channel(ctx))

    def test_forum_post_of_another_owner_raises_pool_exception(self):
        parent = MagicMock(spec=disnake.ForumChannel)
        ctx = self.ctx("2", SimpleNamespace(id=2, parent=parent, owner_id=1))
        with pytest.raises(PoolException):
            run(checks.check_requester_channel(ctx))

    def test_forum_post_of_this_bot_without_voice_raises_pool_exception(self):
        parent = MagicMock(spec=disnake.ForumChannel)
        ctx = self.ctx("2", SimpleNamespace(id=2, parent=parent, owner_id=9))
        with pytest.raises(PoolException):
            run(checks.check_requester_channel(ctx))

    def test_forum_post_of_this_bot_with_the_bot_in_the_author_voice_refuses_prefix_commands(self):
        parent = MagicMock(spec=disnake.ForumChannel)
        ctx = self.ctx("2", SimpleNamespace(id=2, parent=parent, owner_id=9))
        ctx.author.voice = SimpleNamespace(channel=SimpleNamespace(voice_states={9: object()}))
        with pytest.raises(GenericError, match="comandos de barra"):
            run(checks.check_requester_channel(ctx))


# ============================================================================ get_available_bots_info / check_player_perm


def make_pool(bots):
    return SimpleNamespace(get_guild_bots=lambda gid: bots)


class TestGetAvailableBotsInfo:
    MEMBER = SimpleNamespace(guild_permissions=perms(manage_guild=False))

    def test_free_bots_are_suggested(self):
        bot = SimpleNamespace(
            bot_ready=True,
            music=SimpleNamespace(players={}),
            get_guild=lambda gid: object(),
            user=SimpleNamespace(mention="<@2>"),
        )
        text, components = checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER)
        assert "<@2>" in text and components == []

    def test_bots_not_ready_are_ignored(self):
        bot = SimpleNamespace(bot_ready=False)
        assert checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER) == ("", [])

    def test_bot_outside_the_guild_offers_the_invite_button(self):
        bot = SimpleNamespace(bot_ready=True, music=SimpleNamespace(players={}), get_guild=lambda gid: None)
        text, components = checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER)
        assert "administrador" in text and components[0].custom_id == "bot_invite"

    def test_active_session_channel_is_suggested(self):
        last = MagicMock()
        last.mention = "<#3>"
        last.permissions_for.return_value = perms(connect=True)
        player = make_player(last_channel=last)
        bot = SimpleNamespace(bot_ready=True, music=SimpleNamespace(players={GID: player}))
        text, _ = checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER)
        assert "<#3>" in text

    def test_session_in_247_mode_is_not_suggested(self):
        player = make_player(keep_connected=True, last_channel=MagicMock())
        bot = SimpleNamespace(bot_ready=True, music=SimpleNamespace(players={GID: player}))
        assert checks.get_available_bots_info(make_pool([bot]), GID, self.MEMBER) == ("", [])


class TestCheckPlayerPerm:
    def setup_inter(self, player):
        author = SimpleNamespace(
            id=1, mention="<@1>", guild_permissions=perms(manage_channels=False), roles=[], voice=None
        )
        player.guild = SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=None)))
        inter = SimpleNamespace(guild_id=GID, guild=MagicMock(spec=disnake.Guild), author=author)
        bot = SimpleNamespace(
            music=SimpleNamespace(players={GID: player}),
            pool=make_pool([]),
            get_data=AsyncMock(return_value={"djroles": []}),
        )
        return inter, bot

    def test_without_player_returns_true(self):
        inter = SimpleNamespace(guild_id=GID)
        bot = SimpleNamespace(music=SimpleNamespace(players={}))
        assert run(checks.check_player_perm(inter, bot, None)) is True

    def test_manage_channels_always_passes(self):
        player = make_player()
        inter, bot = self.setup_inter(player)
        inter.author.guild_permissions = perms(manage_channels=True)
        assert run(checks.check_player_perm(inter, bot, None)) is True

    def test_247_mode_is_reserved_for_managers(self):
        player = make_player(keep_connected=True)
        inter, bot = self.setup_inter(player)
        with pytest.raises(GenericError, match="modo 24/7"):
            run(checks.check_player_perm(inter, bot, None))

    def test_creator_passes(self):
        player = make_player(player_creator=1)
        inter, bot = self.setup_inter(player)
        assert run(checks.check_player_perm(inter, bot, None)) is True

    def test_listed_dj_passes(self):
        player = make_player(dj={1})
        inter, bot = self.setup_inter(player)
        assert run(checks.check_player_perm(inter, bot, None)) is True

    def test_member_with_a_dj_role_passes(self):
        player = make_player()
        inter, bot = self.setup_inter(player)
        inter.author.roles = [SimpleNamespace(id=5)]
        assert run(checks.check_player_perm(inter, bot, None, guild_data={"djroles": ["5"]})) is True

    def test_move_members_in_the_voice_channel_passes(self):
        player = make_player()
        inter, bot = self.setup_inter(player)
        vc = MagicMock()
        vc.permissions_for.return_value = perms(move_members=True)
        player.guild.me.voice.channel = vc
        assert run(checks.check_player_perm(inter, bot, None)) is True

    def test_restrict_mode_refuses_everyone_else(self):
        player = make_player(restrict_mode=True)
        inter, bot = self.setup_inter(player)
        with pytest.raises(GenericError, match="modo restrito"):
            run(checks.check_player_perm(inter, bot, None))

    def test_member_in_voice_without_a_session_channel_becomes_dj(self):
        player = make_player()
        inter, bot = self.setup_inter(player)
        inter.author.voice = object()
        assert run(checks.check_player_perm(inter, bot, None)) is True
        assert 1 in player.dj

    def test_channel_without_any_dj_promotes_the_author(self):
        player = make_player()
        player.bot = SimpleNamespace(get_color=lambda: 0)
        inter, bot = self.setup_inter(player)
        vc = MagicMock()
        vc.id = 3
        vc.permissions_for.return_value = perms(move_members=False)
        vc.members = [SimpleNamespace(id=9, bot=False)]
        player.guild.me.voice.channel = vc
        channel = SimpleNamespace(send=AsyncMock())

        assert run(checks.check_player_perm(inter, bot, channel)) is True

        assert 1 in player.dj
        channel.send.assert_awaited_once()


class TestHasPerm:
    def test_delegates_to_check_player_perm_with_the_interaction_channel(self, monkeypatch):
        spy = AsyncMock(return_value=True)
        monkeypatch.setattr(checks, "check_player_perm", spy)
        inter = make_inter(channel="canal")
        assert run(checks.has_perm(inter)) is True
        assert spy.await_args.kwargs["channel"] == "canal"

"""KI-27 — caracterização de `empiremuse/wavelink/player.py` e `meta.py` (cliente Lavalink v3/v4).

Fixa o que o `Player` envia ao nó em cada versão do protocolo (payloads de play/stop/pause/volume/seek/destroy/voz), o cálculo de
posição, a máquina de estados de voz e a troca de nó. Sem rede: o nó é um dublê que registra as chamadas.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse import wavelink
from empiremuse.wavelink.errors import InvalidIDProvided, WavelinkException
from empiremuse.wavelink.eqs import Equalizer
from empiremuse.wavelink.events import TrackEnd
from empiremuse.wavelink.meta import WavelinkMixin
from empiremuse.wavelink.player import Player, Track, TrackPlaylist, WavelinkVoiceClient

GID = 100


def run(coro):
    return asyncio.run(coro)


def make_node(version=4, session_id="sess"):
    return SimpleNamespace(
        version=version,
        session_id=session_id,
        _send=AsyncMock(),
        update_player=AsyncMock(),
        players={},
        rest_uri="http://lavalink:2333",
        headers={"Authorization": "x"},
        session=MagicMock(),
        region=None,
        shard_id=None,
        close=MagicMock(),
        open=MagicMock(),
        _client=MagicMock(),
    )


def make_player(version=4, **kwargs):
    node = kwargs.pop("node", None) or make_node(version)
    bot = kwargs.pop("bot", None) or MagicMock()
    player = Player(bot, GID, node)
    player.filters = {}
    for key, value in kwargs.items():
        setattr(player, key, value)
    return player


def make_track(duration=200000, id_="ENC"):
    return Track(id_, {"title": "Música", "identifier": "dQw4w9WgXcQ", "length": duration, "author": "A", "uri": "u"})


# ============================================================================ Track / TrackPlaylist


class TestTrack:
    def test_basic_fields(self):
        track = make_track()
        assert (track.id, track.title, track.length, track.duration, str(track)) == (
            "ENC",
            "Música",
            200000,
            200000,
            "Música",
        )
        assert track.uri == "u" and track.is_dead is False

    def test_youtube_identifier_builds_the_thumbnail(self):
        track = make_track()
        assert track.ytid == "dQw4w9WgXcQ"
        assert track.thumb == "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"

    def test_non_youtube_identifier_uses_the_plugin_artwork(self):
        track = Track(
            "E", {"title": "t", "identifier": "outra-coisa-longa"}, pluginInfo={"artworkUrl": "https://x/capa"}
        )
        assert track.ytid is None and track.thumb == "https://x/capa"

    def test_missing_artwork_becomes_an_empty_string(self):
        assert Track("E", {"title": "t", "identifier": "x"}).thumb == ""

    def test_existing_artwork_is_kept(self):
        assert Track("E", {"title": "t", "identifier": "x", "artworkUrl": "https://x/a"}).thumb == "https://x/a"

    def test_title_and_author_are_truncated(self):
        track = Track("E", {"title": "t" * 200, "author": "a" * 200, "identifier": "x"})
        assert len(track.title) == 97 and len(track.author) == 97

    def test_uri_defaults_to_empty(self):
        assert Track("E", {"title": "t", "identifier": "x"}).uri == ""


class TestTrackPlaylist:
    DATA = {
        "tracks": [
            {"track": "A", "info": {"title": "1", "identifier": "x"}},
            {"track": "B", "info": {"title": "2", "identifier": "y"}},
        ]
    }

    def test_tracks_are_built_from_the_payload(self):
        playlist = TrackPlaylist(self.DATA)
        assert [t.id for t in playlist.tracks] == ["A", "B"] and playlist.data is self.DATA

    def test_custom_encoded_name_and_track_class(self):
        data = {"tracks": [{"encoded": "Z", "info": {"title": "1", "identifier": "x"}}]}

        class MinhaFaixa(Track):
            pass

        playlist = TrackPlaylist(data, encoded_name="encoded", track_cls=MinhaFaixa)
        assert isinstance(playlist.tracks[0], MinhaFaixa) and playlist.tracks[0].id == "Z"


# ============================================================================ propriedades e posição


class TestStateProperties:
    def test_defaults(self):
        player = make_player()
        assert (player.is_connected, player.is_playing, player.is_paused, player.volume) == (False, False, False, 100)
        assert player.equalizer is player.eq and player.position == 0

    def test_playing_requires_a_channel_and_a_track(self):
        player = make_player(channel_id=5, current=make_track())
        assert player.is_playing is True

    def test_position_advances_with_time(self):
        player = make_player(
            channel_id=5, current=make_track(), last_position=1000, last_update=time.time() * 1000 - 500
        )
        assert 1400 < player.position < 1700

    def test_position_when_paused_is_frozen_and_capped(self):
        player = make_player(channel_id=5, current=make_track(duration=2000), last_position=5000, paused=True)
        assert player.position == 2000

    def test_position_beyond_the_duration_resets_to_zero(self):
        player = make_player(channel_id=5, current=make_track(duration=100), last_position=0, last_update=0)
        assert player.position == 0

    def test_update_state_reads_position_time_and_ping(self):
        player = make_player()
        run(player.update_state({"state": {"position": 42, "time": 7, "ping": 12}}))
        assert (player.last_position, player.position_timestamp, player.ping) == (42, 7, 12)

    def test_update_state_defaults(self):
        player = make_player()
        run(player.update_state({"state": {}}))
        assert (player.last_position, player.position_timestamp, player.ping) == (0, 0, None)

    def test_hook_clears_the_track_when_it_finishes(self):
        for reason in ("STOPPED", "FINISHED"):
            player = make_player(current=make_track(), current_encoded="ENC")
            event = TrackEnd.__new__(TrackEnd)
            event.reason = reason
            run(player.hook(event))
            assert player.current is None and player.current_encoded is None

    def test_hook_keeps_the_track_on_replace(self):
        player = make_player(current=make_track(), current_encoded="ENC")
        event = TrackEnd.__new__(TrackEnd)
        event.reason = "REPLACED"
        run(player.hook(event))
        assert player.current is not None


# ============================================================================ voz


class TestVoiceUpdates:
    def test_v4_sends_the_voice_update_once_it_is_complete(self):
        player = make_player(4)
        run(player._voice_server_update({"token": "tk", "endpoint": "ep"}))
        player.node.update_player.assert_not_awaited()  # ainda sem sessionId nem canal
        run(player._voice_state_update({"session_id": "S", "channel_id": "55"}))
        player.node.update_player.assert_awaited_once_with(
            GID, data={"voice": {"sessionId": "S", "token": "tk", "endpoint": "ep", "channelId": "55"}}
        )
        assert player.channel_id == 55

    def test_v4_incomplete_state_sends_nothing(self):
        player = make_player(4)
        run(player._voice_state_update({"session_id": "S", "channel_id": "55"}))
        player.node.update_player.assert_not_awaited()

    def test_v3_sends_voice_update_only_with_session_and_event(self):
        player = make_player(3)
        run(player._voice_server_update({"token": "tk"}))
        player.node._send.assert_not_awaited()
        run(player._voice_state_update({"session_id": "S", "channel_id": "9"}))
        player.node._send.assert_awaited_once_with(
            op="voiceUpdate", guildId=str(GID), sessionId="S", event={"token": "tk"}
        )

    def test_disconnect_event_clears_the_channel_and_state(self):
        player = make_player(4, channel_id=5, _voice_state={"event": {}})
        run(player._voice_state_update({"session_id": "S", "channel_id": None}))
        assert player.channel_id is None and player._voice_state == {}

    def test_same_channel_does_not_resend(self):
        player = make_player(4, channel_id=5)
        run(player._voice_state_update({"session_id": "S", "channel_id": "5"}))
        player.node.update_player.assert_not_awaited()

    def test_v4_without_channel_does_not_send(self):
        player = make_player(4)
        run(player._dispatch_voice_update())
        player.node.update_player.assert_not_awaited()


class TestConnect:
    def bot(self, *, voice_client="none", me_voice=True, with_player=True):
        guild = MagicMock()
        guild.voice_client = None if voice_client == "none" else voice_client
        guild.me.voice = object() if me_voice else None
        bot = MagicMock()
        bot.get_guild.return_value = guild
        channel = MagicMock()
        channel.connect = AsyncMock()
        bot.get_channel.return_value = channel
        bot.music.players = {GID: object()} if with_player else {}
        return bot, guild, channel

    def test_unknown_guild_raises(self):
        bot = MagicMock()
        bot.get_guild.return_value = None
        with pytest.raises(InvalidIDProvided):
            run(make_player(bot=bot).connect(5))

    def test_without_a_registered_player_nothing_happens(self):
        bot, _, channel = self.bot(with_player=False)
        player = make_player(bot=bot)
        run(player.connect(5))
        channel.connect.assert_not_awaited()
        assert player.channel_id is None

    def test_first_connection_uses_the_wavelink_voice_client(self):
        bot, _, channel = self.bot()
        player = make_player(bot=bot)
        run(player.connect(5))
        channel.connect.assert_awaited_once_with(cls=WavelinkVoiceClient, reconnect=True)
        assert player.channel_id == 5

    def test_stale_voice_client_is_cleaned_and_reconnected(self):
        stale = MagicMock()
        bot, _, channel = self.bot(voice_client=stale, me_voice=False)
        run(make_player(bot=bot).connect(5))
        stale.cleanup.assert_called_once()
        channel.connect.assert_awaited_once_with(cls=WavelinkVoiceClient, reconnect=False)

    def test_reconnect_failure_is_swallowed(self, capsys):
        stale = MagicMock()
        bot, _, channel = self.bot(voice_client=stale, me_voice=False)
        channel.connect.side_effect = RuntimeError("falhou")
        run(make_player(bot=bot).connect(5))
        assert "falhou" in capsys.readouterr().err

    def test_other_channel_moves_the_voice_client(self):
        client = MagicMock()
        client.channel.id = 1
        client.move_to = AsyncMock()
        bot, _, channel = self.bot(voice_client=client)
        run(make_player(bot=bot).connect(5))
        client.move_to.assert_awaited_once_with(channel)

    def test_same_channel_resends_the_voice_state(self):
        client = MagicMock()
        client.channel.id = 5
        bot, _, _ = self.bot(voice_client=client)
        registered = make_player(4, _voice_state={"sessionId": "S"})
        registered._dispatch_voice_update = AsyncMock()
        bot.music.players = {GID: registered}
        registered.bot = bot
        run(registered.connect(5))
        registered._dispatch_voice_update.assert_awaited_once()


class TestDisconnect:
    def test_unknown_guild_with_force_just_clears_the_channel(self):
        bot = MagicMock()
        bot.get_guild.return_value = None
        player = make_player(bot=bot, channel_id=5)
        run(player.disconnect(force=True))
        assert player.channel_id is None

    def test_unknown_guild_without_force_raises(self):
        bot = MagicMock()
        bot.get_guild.return_value = None
        with pytest.raises(InvalidIDProvided):
            run(make_player(bot=bot).disconnect())

    def test_leaves_through_the_shard_socket(self):
        import disnake
        from disnake.ext import commands

        bot = MagicMock(spec=commands.Bot)
        bot.shard_id = None
        bot.ws = MagicMock()
        bot.ws.voice_state = AsyncMock()
        guild = MagicMock(spec=disnake.Guild)
        guild.shard_id = 0
        bot.get_guild.return_value = guild
        player = make_player(bot=bot, channel_id=5)
        run(player.disconnect())
        bot.ws.voice_state.assert_awaited_once_with(GID, None)
        assert player.channel_id is None

    def test_shard_socket_is_none_for_another_shard(self):
        from disnake.ext import commands

        bot = MagicMock(spec=commands.Bot)
        bot.shard_id = 3
        assert make_player(bot=bot)._get_shard_socket(1) is None


# ============================================================================ comandos ao nó


class TestPlay:
    def test_v4_payload_and_state(self):
        player = make_player(4, volume=80)
        run(player.play(make_track(), start=1500, end=9000))
        player.node.update_player.assert_awaited_once_with(
            GID,
            {"encodedTrack": "ENC", "volume": 80, "position": 1500, "paused": False, "filters": {}, "endTime": "9000"},
            True,
        )
        assert player.current.id == "ENC" and player.current_encoded == "ENC"

    def test_v4_overrides_volume_and_pause_from_kwargs(self):
        player = make_player(4)
        run(player.play(make_track(), volume=30, paused=True, temp_id="TMP"))
        payload = player.node.update_player.await_args.args[1]
        assert (payload["volume"], payload["paused"], payload["encodedTrack"]) == (30, True, "TMP")
        assert player.volume == 30

    def test_v3_payload(self):
        player = make_player(3)
        run(player.play(make_track(), start=1500, end=9000))
        kwargs = player.node._send.await_args.kwargs
        assert kwargs == {
            "op": "play",
            "guildId": str(GID),
            "track": "ENC",
            "noReplace": False,
            "startTime": 1500,
            "endTime": "9000",
        }

    def test_replace_false_keeps_the_playing_track(self):
        player = make_player(4, channel_id=5, current=make_track(id_="ATUAL"))
        run(player.play(make_track(id_="NOVA"), replace=False))
        player.node.update_player.assert_not_awaited()
        assert player.current.id == "ATUAL"

    def test_replace_false_plays_when_idle(self):
        player = make_player(4)
        run(player.play(make_track(), replace=False))
        player.node.update_player.assert_awaited_once()
        assert player.node.update_player.await_args.args[2] is False

    def test_play_resets_the_clock_and_unpauses(self):
        player = make_player(4, paused=True, last_position=99)
        run(player.play(make_track()))
        assert (player.paused, player.last_position, player.position_timestamp, player.last_update) == (False, 0, 0, 0)


class TestSimpleCommands:
    def test_stop_v4(self):
        player = make_player(4, current=make_track(), current_encoded="ENC")
        run(player.stop())
        player.node.update_player.assert_awaited_once_with(GID, {"encodedTrack": None}, replace=True)
        assert player.current is None and player.current_encoded is None

    def test_stop_v3(self):
        player = make_player(3, current=make_track())
        run(player.stop())
        player.node._send.assert_awaited_once_with(op="stop", guildId=str(GID))

    @pytest.mark.parametrize("version", [3, 4])
    def test_pause(self, version):
        player = make_player(version)
        run(player.set_pause(True))
        assert player.paused is True
        if version == 3:
            player.node._send.assert_awaited_once_with(op="pause", guildId=str(GID), pause=True)
        else:
            player.node.update_player.assert_awaited_once_with(guild_id=GID, data={"paused": True})

    def test_volume_is_clamped_in_the_state(self):
        player = make_player(3)
        run(player.set_volume(5000))
        assert player.volume == 1000
        player.node._send.assert_awaited_once_with(op="volume", guildId=str(GID), volume=1000)
        run(player.set_volume(-5))
        assert player.volume == 0

    def test_volume_v4_sends_the_requested_value(self):
        player = make_player(4)
        run(player.set_volume(150))
        player.node.update_player.assert_awaited_once_with(guild_id=GID, data={"volume": 150})

    @pytest.mark.parametrize("version", [3, 4])
    def test_seek(self, version):
        player = make_player(version)
        run(player.seek(2500.7))
        if version == 3:
            player.node._send.assert_awaited_once_with(op="seek", guildId=str(GID), position=2500.7)
        else:
            player.node.update_player.assert_awaited_once_with(GID, data={"position": 2500})

    def test_equalizer_v3(self):
        player = make_player(3)
        eq = Equalizer.flat()
        run(player.set_equalizer(eq))
        assert player.equalizer is eq
        assert player.node._send.await_args.kwargs["op"] == "equalizer"

    def test_equalizer_v4_is_not_implemented(self):
        player = make_player(4)
        with pytest.raises(Exception, match="Não implementado"):
            run(player.set_eq(Equalizer.flat()))


class TestDestroy:
    def delete_response(self, status, body=None):
        response = MagicMock()
        response.status = status
        response.json = AsyncMock(return_value=body or {})
        response.text = AsyncMock(return_value="texto")
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    def test_v4_deletes_the_session_player_and_forgets_it(self):
        player = make_player(4)
        player.node.players[GID] = player
        player.node.session.delete.return_value = self.delete_response(204)
        run(player.destroy(guild=MagicMock()))
        assert (
            player.node.session.delete.call_args.kwargs["url"] == f"http://lavalink:2333/v4/sessions/sess/players/{GID}"
        )
        assert GID not in player.node.players

    def test_v4_error_status_raises_with_the_payload(self):
        player = make_player(4)
        player.node.session.delete.return_value = self.delete_response(500, {"erro": "x"})
        with pytest.raises(WavelinkException, match="500"):
            run(player.destroy(guild=MagicMock()))

    def test_v4_error_with_unreadable_json_falls_back_to_text(self):
        player = make_player(4)
        context = self.delete_response(502)
        context.__aenter__.return_value.json = AsyncMock(side_effect=ValueError)
        player.node.session.delete.return_value = context
        with pytest.raises(WavelinkException, match="texto"):
            run(player.destroy(guild=MagicMock()))

    def test_v4_without_a_session_does_not_call_the_node(self):
        player = make_player(4, node=make_node(4, session_id=None))
        run(player.destroy(guild=MagicMock()))
        player.node.session.delete.assert_not_called()

    def test_v3_stops_then_destroys(self):
        player = make_player(3)
        run(player.destroy(guild=MagicMock()))
        ops = [call.kwargs["op"] for call in player.node._send.await_args_list]
        assert ops == ["stop", "destroy"]

    def test_guild_defaults_to_the_bots_guild_and_errors_are_swallowed(self):
        bot = MagicMock()
        bot.get_guild.return_value = None
        player = make_player(3, bot=bot)
        run(player.destroy())
        bot.get_guild.assert_called_once_with(GID)


class TestChangeNode:
    def other(self, version=4):
        node = make_node(version)
        node.is_available = True
        return node

    def test_unknown_identifier(self):
        player = make_player()
        player.node._client.get_node.return_value = None
        with pytest.raises(WavelinkException, match="No Nodes matching"):
            run(player.change_node("x"))

    def test_unavailable_identifier(self):
        player = make_player()
        target = self.other()
        target.is_available = False
        player.node._client.get_node.return_value = target
        with pytest.raises(WavelinkException, match="unavailable"):
            run(player.change_node("x"))

    def test_without_any_candidate_the_old_node_is_reopened(self):
        player = make_player()
        player.node._client.get_best_node.return_value = None
        player.node._client.get_node_by_region.return_value = None
        player.node._client.get_node_by_shard.return_value = None
        with pytest.raises(WavelinkException, match="changeover"):
            run(player.change_node())
        player.node.open.assert_called_once()

    def test_moves_a_playing_v4_player_with_its_position_and_volume(self):
        old = make_node(4)
        player = make_player(node=old, current=make_track(), current_encoded="ENC", volume=70, channel_id=5)
        old.players[GID] = player
        new = self.other(4)
        old._client.get_node.return_value = new
        old.session.delete.return_value = TestDestroy().delete_response(204)

        run(player.change_node("novo"))

        assert player.node is new and new.players[GID] is player and GID not in old.players
        payload = new.update_player.await_args.args[1]
        assert payload["encodedTrack"] == "ENC" and payload["volume"] == 70 and payload["paused"] is False
        assert new.update_player.await_args.kwargs == {"replace": True}

    def test_moves_a_v3_player_and_restores_pause_and_volume(self):
        old = make_node(3)
        player = make_player(
            node=old, current=make_track(), current_encoded="ENC", volume=70, paused=True, channel_id=5
        )
        old.players[GID] = player
        new = self.other(3)
        old._client.get_node.return_value = new

        run(player.change_node("novo"))

        old._send.assert_awaited_once_with(op="destroy", guildId=str(GID))
        ops = [call.kwargs["op"] for call in new._send.await_args_list]
        assert ops == ["play", "pause", "volume"]

    def test_auto_paused_player_does_not_replay_on_the_new_node(self):
        old = make_node(4)
        player = make_player(node=old, current=make_track(), current_encoded="ENC", auto_pause=True)
        old.players[GID] = player
        new = self.other(4)
        old._client.get_node.return_value = new
        old.session.delete.return_value = TestDestroy().delete_response(204)
        run(player.change_node("novo"))
        new.update_player.assert_not_awaited()

    def test_pending_voice_state_is_resent(self):
        old = make_node(4)
        player = make_player(node=old, _voice_state={"sessionId": "S"})
        old.players[GID] = player
        new = self.other(4)
        old._client.get_node.return_value = new
        old.session.delete.return_value = TestDestroy().delete_response(204)
        player._dispatch_voice_update = AsyncMock()
        run(player.change_node("novo"))
        player._dispatch_voice_update.assert_awaited_once()


# ============================================================================ WavelinkVoiceClient / WavelinkMixin


class TestWavelinkVoiceClient:
    def make(self):
        client = WavelinkVoiceClient.__new__(WavelinkVoiceClient)
        WavelinkVoiceClient.__init__(client, MagicMock(), MagicMock())
        client.client.music.update_handler = AsyncMock()
        return client

    def test_voice_events_are_forwarded_to_the_music_client(self):
        client = self.make()
        run(client.on_voice_server_update({"token": "t"}))
        run(client.on_voice_state_update({"session_id": "s"}))
        calls = [c.args[0] for c in client.client.music.update_handler.await_args_list]
        assert calls == [
            {"t": "VOICE_SERVER_UPDATE", "d": {"token": "t"}},
            {"t": "VOICE_STATE_UPDATE", "d": {"session_id": "s"}},
        ]


class TestWavelinkMixin:
    def test_listener_requires_a_coroutine(self):
        with pytest.raises(TypeError, match="coroutines"):

            @WavelinkMixin.listener()
            def nao_assincrona():
                pass

    def test_listener_registers_the_event_name_and_stacks(self):
        @WavelinkMixin.listener(event="on_node_ready")
        @WavelinkMixin.listener()
        async def meu_evento():
            pass

        assert meu_evento.__wavelink_listeners__ == ["meu_evento", "on_node_ready"]

    def test_new_collects_the_listeners_of_the_subclass(self):
        class Cog(WavelinkMixin):
            @WavelinkMixin.listener("on_track_end")
            async def terminou(self, node, payload):
                pass

        instancia = Cog()
        assert Cog.__wavelink_listeners__ == {"on_track_end": ["terminou"]}
        assert instancia is not None

    def test_default_error_hook_prints_the_traceback(self, capsys):
        try:
            raise ValueError("ruim")
        except ValueError as exc:
            run(WavelinkMixin().on_wavelink_error("on_x", exc))
        err = capsys.readouterr().err
        assert "on_x" in err and "ruim" in err

    def test_default_event_hooks_are_noops(self):
        mixin = WavelinkMixin()
        for name in (
            "on_node_ready",
            "on_track_start",
            "on_track_end",
            "on_track_stuck",
            "on_track_exception",
            "on_websocket_closed",
        ):
            args = (None,) if name == "on_node_ready" else (None, None)
            assert run(getattr(mixin, name)(*args)) is None


def test_package_exposes_the_public_names():
    for name in ("Node", "Player", "Track", "TrackPlaylist", "WavelinkException", "TrackNotFound", "MissingSessionID"):
        assert hasattr(wavelink, name), name

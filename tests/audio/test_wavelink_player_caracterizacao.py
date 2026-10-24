"""KI-27 — caracterização de `empiremuse/wavelink/player.py` e `meta.py` (cliente Lavalink v3/v4).

Fixa o que o `Player` envia ao nó em cada versão do protocolo (payloads de play/stop/pause/volume/seek/destroy/voz), o cálculo de
posição, a máquina de estados de voz e a troca de nó. Sem rede: o nó é um dublê que registra as chamadas.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

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


class TestTrackPlaylist:
    DATA = {
        "tracks": [
            {"track": "A", "info": {"title": "1", "identifier": "x"}},
            {"track": "B", "info": {"title": "2", "identifier": "y"}},
        ]
    }

    def test_custom_encoded_name_and_track_class(self):
        data = {"tracks": [{"encoded": "Z", "info": {"title": "1", "identifier": "x"}}]}

        class MinhaFaixa(Track):
            pass

        playlist = TrackPlaylist(data, encoded_name="encoded", track_cls=MinhaFaixa)
        assert isinstance(playlist.tracks[0], MinhaFaixa) and playlist.tracks[0].id == "Z"


# ============================================================================ voz


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

    def test_first_connection_uses_the_wavelink_voice_client(self):
        bot, _, channel = self.bot()
        player = make_player(bot=bot)
        run(player.connect(5))
        channel.connect.assert_awaited_once_with(cls=WavelinkVoiceClient, reconnect=True)
        assert player.channel_id == 5


# ============================================================================ comandos ao nó


class TestSimpleCommands:
    @pytest.mark.parametrize("version", [3, 4])
    def test_pause(self, version):
        player = make_player(version)
        run(player.set_pause(True))
        assert player.paused is True
        if version == 3:
            player.node._send.assert_awaited_once_with(op="pause", guildId=str(GID), pause=True)
        else:
            player.node.update_player.assert_awaited_once_with(guild_id=GID, data={"paused": True})


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


class TestChangeNode:
    def other(self, version=4):
        node = make_node(version)
        node.is_available = True
        return node

    def test_auto_paused_player_does_not_replay_on_the_new_node(self):
        old = make_node(4)
        player = make_player(node=old, current=make_track(), current_encoded="ENC", auto_pause=True)
        old.players[GID] = player
        new = self.other(4)
        old._client.get_node.return_value = new
        old.session.delete.return_value = TestDestroy().delete_response(204)
        run(player.change_node("novo"))
        new.update_player.assert_not_awaited()

"""Fase 2, Trilha A (itens 1, 4, 5, 6 e 7 do contrato do bot) — busca padrão, mensagens de falha, aviso de novo servidor,
decodetrack na rota v4 e voz sem canal. O item 3 (local_lavalink) está em test_lavalink_download_sha256.py; o item 2 (constantes) em
test_branding.py; o item 8 (cabeçalhos de `/`) em tests/panel/test_status_page.py.

Contrato: BRIEFING-FASE2.md ("Trilha A — contrato do item 3"). Interpretações: .qa-fase2a-interp.txt.
Sem rede e sem Discord reais: dublês simples (SimpleNamespace / AsyncMock).
"""

import asyncio
import re
from types import SimpleNamespace

import disnake
import pytest
from tests.support.raiz import RAIZ

ROOT = RAIZ


def run(coro):
    return asyncio.run(coro)


# ============================================================================ (1) SEARCH_PROVIDERS padrão


class TestDefaultSearchProviders:
    EXPECTED = ["ytsearch", "ytmsearch", "scsearch"]

    def test_both_defaults_agree(self):
        import empiremuse.config_loader as config_loader

        text = (ROOT / ".example.env").read_text(encoding="utf-8")
        env = re.search(r'^SEARCH_PROVIDERS=["\']?([^"\'\n]*)', text, re.MULTILINE).group(1).split()
        assert env == config_loader.DEFAULT_CONFIG["SEARCH_PROVIDERS"].split()


def make_node(source_managers, search_providers, original=None):
    return SimpleNamespace(
        _websocket=SimpleNamespace(is_connected=True),
        stats=SimpleNamespace(uptime=10**9),
        info={"sourceManagers": list(source_managers)},
        identifier="no-1",
        version=4,
        search_providers=list(search_providers),
        partial_providers=[],
        native_sources=set(),
        original_providers=set(original if original is not None else search_providers),
        only_use_native_search_providers=True,
        open=lambda: None,
    )


def call_node_ready(node):
    from empiremuse.cogs.music import Music

    cog = SimpleNamespace(bot=SimpleNamespace(user="bot"))
    cog.add_provider = lambda *a: Music.add_provider(cog, *a)
    cog.remove_provider = lambda *a: Music.remove_provider(cog, *a)
    run(Music.node_ready(cog, node))
    return node


class TestNodeReadyDoesNotAddBandcamp:
    SOURCES = ("youtube", "soundcloud", "bandcamp", "http")

    def test_bcsearch_is_dropped_when_the_node_has_no_bandcamp(self):
        node = call_node_ready(make_node(("youtube", "soundcloud"), ["ytsearch", "bcsearch"]))
        assert "bcsearch" not in node.search_providers


# ============================================================================ (4) falha de busca sem repr(e)


def search_cog(exceptions):
    async def lavalink_tracks(**kwargs):
        return [], None, set(exceptions)

    async def partial_tracks(**kwargs):
        return [], None, set(exceptions)

    return SimpleNamespace(
        bot=SimpleNamespace(pool=SimpleNamespace(last_fm=None)),
        get_lavalink_tracks=lavalink_tracks,
        get_partial_tracks=partial_tracks,
    )


def failing_search(exceptions):
    from empiremuse.cogs.music import Music
    from empiremuse.utils.music.errors import GenericError

    with pytest.raises(GenericError) as info:
        run(
            Music.get_tracks(
                search_cog(exceptions), "teste", ctx=None, user=SimpleNamespace(id=1), bot=SimpleNamespace()
            )
        )
    return info.value


class TestSearchFailureMessage:
    LEAK = "FriendlyException('segredo-interno-123', cause=java.io.IOException: /srv/lavalink)"

    def test_region_message_is_kept(self):
        error = failing_search({"x: This track is not readable. Available countries: BR"})
        assert "região" in error.text and "Available countries" not in error.text and "BR" not in error.text


# ============================================================================ (5) misc.py: aviso de novo servidor


def perms(**kw):
    return SimpleNamespace(**{"send_messages": True, "embed_links": True, **kw})


def make_guild(channel):
    me = SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False))
    return SimpleNamespace(
        id=1,
        name="Servidor",
        members=[],
        me=me,
        system_channel=channel,
        rules_channel=None,
        public_updates_channel=None,
    )


def make_channel(permissions, send_error=None):
    sent = []

    async def send(*args, **kwargs):
        sent.append(kwargs)
        if send_error:
            raise send_error

    channel = SimpleNamespace(id=55, send=send, permissions_for=lambda member: permissions)
    channel.sent = sent
    return channel


def welcome(channel):
    from empiremuse.cogs.misc import Misc

    bot = SimpleNamespace(
        pool=SimpleNamespace(bots=[]),
        get_command=lambda name: None,
        default_prefix="!",
        user=SimpleNamespace(id=9),
        config={"SUPPORT_SERVER": "", "INTERACTION_COMMAND_ONLY": True, "MULTIVOICE_VIDEO_DEMO_URL": ""},
        get_color=lambda: 0x8B5CF6,
    )
    run(Misc.guild_add(SimpleNamespace(bot=bot), make_guild(channel)))


def forbidden():
    return disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")


class TestWelcomeMessagePermissions:
    def test_forbidden_does_not_raise(self):
        welcome(make_channel(perms(), send_error=forbidden()))

    @pytest.mark.parametrize("where", ["public_updates_channel", "rules_channel"])
    def test_fallback_channels_also_need_embed_links(self, where):
        from empiremuse.cogs.misc import Misc

        bad, good = make_channel(perms(embed_links=False)), make_channel(perms())
        guild = make_guild(None)
        setattr(guild, where, bad)
        bot = SimpleNamespace(
            pool=SimpleNamespace(bots=[]),
            get_command=lambda name: None,
            default_prefix="!",
            user=SimpleNamespace(id=9),
            config={"SUPPORT_SERVER": "", "INTERACTION_COMMAND_ONLY": True, "MULTIVOICE_VIDEO_DEMO_URL": ""},
            get_color=lambda: 0x8B5CF6,
        )
        run(Misc.guild_add(SimpleNamespace(bot=bot), guild))
        assert bad.sent == [] and good.sent == []


# ============================================================================ (6) wavelink: decodetrack na rota v4


class FakeResponse:
    def __init__(self, status, payload):
        self.status, self._payload = status, payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_decode_node(version, payload, status=200):
    from empiremuse.wavelink.node import Node

    node = object.__new__(Node)
    node.rest_uri, node.password, node.version = "http://127.0.0.1:2333", "senha", version
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(status, payload)

    node.session = SimpleNamespace(get=get)
    return node, calls


INFO = {"identifier": "dQw4w9WgXcQ", "title": "Faixa de teste", "author": "Artista", "length": 1000, "uri": "https://x"}


class TestDecodeTrack:
    def test_v3_keeps_the_old_route(self):
        node, calls = make_decode_node(3, dict(INFO))
        track = run(node.build_track("QUJD"))
        ((url, kwargs),) = calls
        assert "/v4/" not in url and "decodetrack" in url
        assert "track" in (kwargs.get("params") or {}) or "track=" in url
        assert track.title == "Faixa de teste"


# ============================================================================ (7) wavelink: voz


def make_player(version, channel_id, voice_state):
    from empiremuse.wavelink.player import Player

    player = object.__new__(Player)
    player.guild_id = 1
    player.channel_id = channel_id
    player._voice_state = dict(voice_state)
    calls = []

    async def update_player(guild_id, data=None, **kwargs):
        calls.append(data)

    player.node = SimpleNamespace(version=version, update_player=update_player)
    player.calls = calls
    return player


FULL_VOICE = {"sessionId": "abc", "event": {"token": "TOKEN-SECRETO-XYZ", "endpoint": "e.discord.media"}}


class TestVoiceUpdate:
    def test_v3_still_dispatches_without_a_channel_id(self):
        player = make_player(3, None, FULL_VOICE)
        sent = []

        async def send(**kwargs):
            sent.append(kwargs)

        player.node._send = send
        run(player._dispatch_voice_update())
        assert len(sent) == 1 and sent[0]["op"] == "voiceUpdate", "a regra de channel_id é só da rota v4"

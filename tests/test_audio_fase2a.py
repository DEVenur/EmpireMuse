"""Fase 2, Trilha A (itens 1, 4, 5, 6 e 7 do contrato do bot) — busca padrão, mensagens de falha, aviso de novo servidor,
decodetrack na rota v4 e voz sem canal. O item 3 (local_lavalink) está em test_local_lavalink.py; o item 2 (constantes) em
test_branding.py; o item 8 (cabeçalhos de `/`) em tests/panel/test_status_page.py.

Contrato: BRIEFING-FASE2.md ("Trilha A — contrato do item 3"). Interpretações: .qa-fase2a-interp.txt.
Sem rede e sem Discord reais: dublês simples (SimpleNamespace / AsyncMock).
"""

import ast
import asyncio
import re
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import disnake
import pytest

ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


# ============================================================================ (1) SEARCH_PROVIDERS padrão


class TestDefaultSearchProviders:
    EXPECTED = ["ytsearch", "ytmsearch", "scsearch"]

    def test_config_loader_default(self):
        import config_loader

        assert config_loader.DEFAULT_CONFIG["SEARCH_PROVIDERS"].split() == self.EXPECTED

    def test_example_env_default(self):
        text = (ROOT / ".example.env").read_text(encoding="utf-8")
        match = re.search(r'^SEARCH_PROVIDERS=["\']?([^"\'\n]*)["\']?\s*$', text, re.MULTILINE)
        assert match, "SEARCH_PROVIDERS ausente do .example.env"
        assert match.group(1).split() == self.EXPECTED

    def test_both_defaults_agree(self):
        import config_loader

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
    from modules.music import Music

    cog = SimpleNamespace(bot=SimpleNamespace(user="bot"))
    cog.add_provider = lambda *a: Music.add_provider(cog, *a)
    cog.remove_provider = lambda *a: Music.remove_provider(cog, *a)
    run(Music.node_ready(cog, node))
    return node


class TestNodeReadyDoesNotAddBandcamp:
    SOURCES = ("youtube", "soundcloud", "bandcamp", "http")

    def test_bcsearch_is_not_added_automatically_even_if_the_node_supports_bandcamp(self):
        node = call_node_ready(make_node(self.SOURCES, ["ytsearch", "ytmsearch", "scsearch"]))
        assert "bcsearch" not in node.search_providers
        assert not [p for p in node.partial_providers if p.startswith("bcsearch")]

    def test_configured_providers_are_kept(self):
        node = call_node_ready(make_node(self.SOURCES, ["ytsearch", "ytmsearch", "scsearch"]))
        assert node.search_providers == ["ytsearch", "ytmsearch", "scsearch"]

    def test_bcsearch_chosen_by_the_owner_is_kept_when_bandcamp_is_supported(self):
        node = call_node_ready(make_node(self.SOURCES, ["ytsearch", "bcsearch"]))
        assert "bcsearch" in node.search_providers

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
    from modules.music import Music
    from utils.music.errors import GenericError

    with pytest.raises(GenericError) as info:
        run(
            Music.get_tracks(
                search_cog(exceptions), "teste", ctx=None, user=SimpleNamespace(id=1), bot=SimpleNamespace()
            )
        )
    return info.value


class TestSearchFailureMessage:
    LEAK = "FriendlyException('segredo-interno-123', cause=java.io.IOException: /srv/lavalink)"

    def test_final_message_has_no_exception_text(self):
        error = failing_search({self.LEAK})
        for fragment in ("segredo-interno-123", "FriendlyException", "IOException", "/srv/lavalink", "Traceback"):
            assert fragment not in error.text, f"vazamento de detalhe interno na mensagem ao usuário: {fragment}"
        assert error.text.strip() and "```" not in error.text

    def test_message_is_portuguese_and_generic(self):
        text = failing_search({self.LEAK}).text.lower()
        assert "busca" in text and ("erro" in text or "não foi possível" in text or "falha" in text)

    def test_detail_stays_available_for_the_log(self):
        assert "segredo-interno-123" in (failing_search({self.LEAK}).error or ""), (
            "o detalhe técnico vai em GenericError.error (log), não no texto"
        )

    def test_region_message_is_kept(self):
        error = failing_search({"x: This track is not readable. Available countries: BR"})
        assert "região" in error.text and "Available countries" not in error.text and "BR" not in error.text

    def test_without_exceptions_the_message_is_still_no_results(self):
        assert "Não houve resultados" in failing_search(set()).text

    def test_lastfm_mix_failure_has_no_repr(self):
        from modules.music import Music
        from utils.music.errors import GenericError

        class Boom:
            async def get_similar_tracks(self, **kw):
                raise RuntimeError("detalhe-secreto-lastfm")

            async def get_artist_toptracks(self, artist):
                raise RuntimeError("detalhe-secreto-lastfm")

        cog = SimpleNamespace(bot=SimpleNamespace(pool=SimpleNamespace(last_fm=Boom())))
        with pytest.raises(GenericError) as info:
            run(Music.get_tracks(cog, "artista - faixa", ctx=None, user=SimpleNamespace(id=1), mix=True))
        assert "detalhe-secreto-lastfm" not in info.value.text and "RuntimeError" not in info.value.text


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
    from modules.misc import Misc

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
    def test_forbidden_does_not_print_a_traceback(self, capsys):
        welcome(make_channel(perms(), send_error=forbidden()))
        out = capsys.readouterr()
        assert "Traceback" not in out.out + out.err, "Forbidden é esperado: uma linha de log, sem traceback"

    def test_forbidden_does_not_raise(self):
        welcome(make_channel(perms(), send_error=forbidden()))

    def test_channel_without_embed_links_is_not_used(self):
        channel = make_channel(perms(embed_links=False))
        welcome(channel)
        assert channel.sent == [], "sem embed_links o envio de embeds falharia: nem tenta"

    def test_channel_without_send_messages_is_not_used(self):
        channel = make_channel(perms(send_messages=False))
        welcome(channel)
        assert channel.sent == []

    def test_channel_with_both_permissions_receives_the_embeds(self):
        channel = make_channel(perms())
        welcome(channel)
        assert len(channel.sent) == 1 and channel.sent[0].get("embeds")

    @pytest.mark.parametrize("where", ["public_updates_channel", "rules_channel"])
    def test_fallback_channels_also_need_embed_links(self, where):
        from modules.misc import Misc

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

    def test_no_bare_except_in_guild_add(self):
        tree = ast.parse((ROOT / "modules" / "misc.py").read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "guild_add")
        bare = [h.lineno for h in ast.walk(func) if isinstance(h, ast.ExceptHandler) and h.type is None]
        assert not bare, f"except: nu em guild_add nas linhas {bare}"


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
    from wavelink.node import Node

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
    def test_v4_uses_the_v4_route_and_the_encoded_track_parameter(self):
        node, calls = make_decode_node(4, {"encoded": "QUJD", "info": dict(INFO), "pluginInfo": {}})
        track = run(node.build_track("QUJD"))
        ((url, kwargs),) = calls
        assert "/v4/decodetrack" in url
        query = url.partition("?")[2] + "&" + "&".join(f"{k}={v}" for k, v in (kwargs.get("params") or {}).items())
        assert "encodedTrack=QUJD" in query
        assert kwargs["headers"]["Authorization"] == "senha"
        assert track.title == "Faixa de teste" and track.id == "QUJD"

    def test_v4_error_raises_build_track_error(self):
        from wavelink.errors import BuildTrackError

        node, _ = make_decode_node(4, {"status": 400, "error": "Bad Request", "message": "x"}, status=400)
        with pytest.raises(BuildTrackError):
            run(node.build_track("lixo"))

    def test_v3_keeps_the_old_route(self):
        node, calls = make_decode_node(3, dict(INFO))
        track = run(node.build_track("QUJD"))
        ((url, kwargs),) = calls
        assert "/v4/" not in url and "decodetrack" in url
        assert "track" in (kwargs.get("params") or {}) or "track=" in url
        assert track.title == "Faixa de teste"


# ============================================================================ (7) wavelink: voz


def make_player(version, channel_id, voice_state):
    from wavelink.player import Player

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
    def test_v4_does_not_dispatch_without_a_channel_id(self):
        player = make_player(4, None, FULL_VOICE)
        run(player._dispatch_voice_update())
        assert player.calls == [], "channelId nulo derruba/ignora a conexão de voz no Lavalink 4.2+"

    def test_v4_dispatches_with_a_channel_id(self):
        player = make_player(4, 777, FULL_VOICE)
        run(player._dispatch_voice_update())
        (data,) = player.calls
        assert data["voice"]["channelId"] == "777" and data["voice"]["sessionId"] == "abc"

    def test_missing_session_id_logs_at_debug_without_pprint_or_traceback(self, capsys, caplog):
        player = make_player(4, 777, {"event": {"token": "TOKEN-SECRETO-XYZ", "endpoint": "e"}})
        with caplog.at_level("DEBUG"):
            run(player._dispatch_voice_update())
        out = capsys.readouterr()
        assert player.calls == []
        assert out.out == "" and "Traceback" not in out.err, "sem pprint do estado de voz (tem token) nem traceback"
        assert "TOKEN-SECRETO-XYZ" not in out.out + out.err + caplog.text, "o token de voz não vai ao log"

    def test_v3_still_dispatches_without_a_channel_id(self):
        player = make_player(3, None, FULL_VOICE)
        sent = []

        async def send(**kwargs):
            sent.append(kwargs)

        player.node._send = send
        run(player._dispatch_voice_update())
        assert len(sent) == 1 and sent[0]["op"] == "voiceUpdate", "a regra de channel_id é só da rota v4"

    def test_player_module_does_not_use_pprint(self):
        source = (ROOT / "wavelink" / "player.py").read_text(encoding="utf-8")
        assert "pprint" not in source

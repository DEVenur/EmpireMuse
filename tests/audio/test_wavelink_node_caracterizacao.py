"""KI-27 — caracterização de `empiremuse/wavelink/node.py` (nó Lavalink v3/v4: busca de faixas, REST e ciclo de vida) e `backoff.py`.

Sem rede: a sessão HTTP é um dublê que devolve respostas prontas e registra as URLs pedidas. As esperas (`asyncio.sleep`) são
trocadas por um espião para o teste não demorar.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.wavelink import node as node_module
from empiremuse.wavelink.backoff import ExponentialBackoff
from empiremuse.wavelink.errors import (
    BuildTrackError,
    MissingSessionID,
    TrackLoadError,
    TrackNotFound,
    WavelinkException,
)
from empiremuse.wavelink.node import Node
from empiremuse.wavelink.player import Track, TrackPlaylist


def run(coro):
    return asyncio.run(coro)


class Resposta:
    def __init__(self, status=200, data=None, text="corpo", json_error=None):
        self.status, self.data, self._text, self.json_error = status, data, text, json_error

    async def json(self):
        if self.json_error:
            raise self.json_error
        return self.data

    async def text(self):
        return self._text

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class Contexto:
    def __init__(self, resposta):
        self.resposta = resposta

    async def __aenter__(self):
        return self.resposta

    async def __aexit__(self, *exc):
        return False


class Sessao:
    """Devolve as respostas na ordem; guarda (método, url, kwargs) de cada chamada."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def _next(self, metodo, url, kwargs):
        self.chamadas.append((metodo, url, kwargs))
        return Contexto(self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0])

    def get(self, url, **kwargs):
        return self._next("get", url, kwargs)

    def patch(self, url, **kwargs):
        return self._next("patch", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("post", url, kwargs)

    def delete(self, url, **kwargs):
        return self._next("delete", url, kwargs)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = AsyncMock()
    monkeypatch.setattr(node_module.asyncio, "sleep", sleeps)
    return sleeps


def make_node(*respostas, version=4, session_id="sess", cache=None):
    pool = SimpleNamespace(playlist_cache=cache if cache is not None else {})
    client = MagicMock()
    client.bot.pool = pool
    client.nodes = {}
    node = Node(
        "host",
        2333,
        1,
        99,
        client=client,
        session=Sessao(*respostas),
        rest_uri="http://lavalink:2333",
        password="senha",
        region="br",
        identifier="no-1",
    )
    node.version = version
    node.session_id = session_id if version == 4 else None
    client.nodes[node.identifier] = node
    return node


def info(title="Música", identifier="dQw4w9WgXcQ", source="youtube", author="Autor"):
    return {
        "title": title,
        "identifier": identifier,
        "author": author,
        "length": 1000,
        "isStream": False,
        "sourceName": source,
        "uri": "https://x",
    }


def v4_search(*titles, source="youtube"):
    return {
        "loadType": "search",
        "data": [
            {"encoded": f"E{n}", "info": info(t, identifier=f"id{n:09}", source=source)} for n, t in enumerate(titles)
        ],
    }


# ============================================================================ estado e propriedades


class TestNodeState:
    def test_defaults_and_repr(self):
        node = make_node()
        assert node.info == {"sourceManagers": [], "plugins": {}} and node.players == {}
        assert repr(node) == "no-1 | br | (Shard: None)"
        assert len(node.resume_key) == 16

    def test_update_info_v4_converts_plugins_to_a_name_version_map(self):
        node = make_node()
        node.update_info({"check_version": 4, "plugins": [{"name": "lyrics", "version": "1.0"}], "sourceManagers": []})
        assert node.version == 4 and node.info["plugins"] == {"lyrics": "1.0"}

    def test_update_info_v3_keeps_plugins_untouched(self):
        node = make_node()
        node.update_info({"check_version": 3, "plugins": [{"name": "x"}]})
        assert node.version == 3 and node.info["plugins"] == [{"name": "x"}]

    def test_headers(self):
        assert make_node().headers == {"Authorization": "senha", "User-Id": "99", "Client-Name": "Wavelink/custom"}

    def test_close_and_open_toggle_availability(self):
        node = make_node()
        node.close()
        assert node.available is False
        node.open()
        assert node.available is True

    def test_penalty(self):
        node = make_node()
        assert node.penalty == 9e30
        node.stats = SimpleNamespace(penalty=SimpleNamespace(total=12.5))
        assert node.penalty == 12.5
        node.close()
        assert node.penalty == 9e30

    def test_is_available_rules(self):
        node = make_node()
        assert node.is_available is False  # sem websocket
        node._websocket = SimpleNamespace(is_connected=True)
        assert node.is_available is True
        node._closing = True
        assert node.is_available is False
        node._closing, node._is_connecting = False, True
        assert node.is_available is False
        node._is_connecting = False
        node.session_id = None
        assert node.is_available is False  # v4 exige sessão

    def test_lyric_support(self):
        node = make_node(version=3)
        assert node.lyric_support is None
        node = make_node()
        node.info["plugins"] = {}
        assert node.lyric_support is False
        node.info["plugins"] = {"lyrics": "1"}
        assert node.lyric_support is True
        node.info["plugins"] = {"java-lyrics-plugin": "1"}
        assert node.lyric_support is True

    def test_get_player(self):
        node = make_node()
        node.players[1] = "p"
        assert node.get_player(1) == "p" and node.get_player(2) is None


# ============================================================================ busca de faixas


class TestGetTracksV4:
    def test_search_result_becomes_a_list_of_tracks(self):
        node = make_node(Resposta(data=v4_search("Um", "Dois")))
        tracks = run(node.get_tracks("ytsearch:teste"))
        assert [t.title for t in tracks] == ["Um", "Dois"] and all(isinstance(t, Track) for t in tracks)
        assert node.session.chamadas[0][1] == "http://lavalink:2333/v4/loadtracks?identifier=ytsearch%3Ateste"

    def test_single_track_load(self):
        data = {"loadType": "track", "data": {"encoded": "E", "info": info("Solo")}}
        tracks = run(make_node(Resposta(data=data)).get_tracks("https://youtu.be/x"))
        assert [t.id for t in tracks] == ["E"]

    def test_empty_result_raises_track_not_found(self):
        node = make_node(Resposta(data={"loadType": "empty", "data": {}}))
        with pytest.raises(TrackNotFound):
            run(node.get_tracks("ytsearch:nada"))

    def test_missing_load_type_raises(self):
        with pytest.raises(WavelinkException, match="error while trying to load"):
            run(make_node(Resposta(data={})).get_tracks("x"))

    def test_error_load_raises_track_load_error_with_the_message(self):
        data = {"loadType": "error", "data": {"message": "Vídeo indisponível", "severity": "common", "cause": "c"}}
        with pytest.raises(TrackLoadError) as erro:
            run(make_node(Resposta(data=data)).get_tracks("https://youtu.be/x"))
        assert "Vídeo indisponível" in str(erro.value) and erro.value.severity == "common"

    def test_non_200_without_retry_returns_none(self):
        node = make_node(Resposta(status=500))
        assert run(node.get_tracks("x")) is None

    def test_non_200_with_retry_waits_with_backoff_and_tries_again(self, no_sleep):
        node = make_node(Resposta(status=500), Resposta(data=v4_search("Ok")))
        tracks = run(node.get_tracks("x", retry_on_failure=True))
        assert [t.title for t in tracks] == ["Ok"] and no_sleep.await_count == 1

    def test_invalid_json_raises(self):
        node = make_node(Resposta(json_error=ValueError("lixo")))
        with pytest.raises(WavelinkException, match="Failed to parse json"):
            run(node.get_tracks("x"))

    def test_list_payload_is_returned_untouched(self):
        assert run(make_node(Resposta(data=[1, 2])).get_tracks("x")) == [1, 2]

    def test_custom_track_class_and_extra_keywords(self):
        class Minha(Track):
            pass

        node = make_node(Resposta(data=v4_search("Um")))
        assert isinstance(run(node.get_tracks("x", track_cls=Minha))[0], Minha)


V3_BUG = (
    "defeito conhecido: `get_tracks` lê `data.get('data')`, que no payload v3 (sem a chave 'data') é None; a busca v3 vira "
    "TrackNotFound e LOAD_FAILED estoura TypeError. Quando corrigido, remova o xfail."
)


class TestGetTracksV3:
    @pytest.mark.xfail(strict=True, reason=V3_BUG)
    def test_url_has_no_v4_prefix_and_uses_the_track_key(self):
        data = {"loadType": "SEARCH_RESULT", "tracks": [{"track": "T3", "info": info("V3")}]}
        node = make_node(Resposta(data=data), version=3)
        tracks = run(node.get_tracks("ytsearch:x"))
        assert tracks[0].id == "T3"

    def test_url_has_no_v4_prefix(self):
        node = make_node(Resposta(data={"loadType": "SEARCH_RESULT", "tracks": []}), version=3)
        with pytest.raises(TrackNotFound):
            run(node.get_tracks("ytsearch:x"))
        assert node.session.chamadas[0][1] == "http://lavalink:2333/loadtracks?identifier=ytsearch%3Ax"

    def test_no_matches_is_an_empty_list(self):
        assert run(make_node(Resposta(data={"loadType": "NO_MATCHES"}), version=3).get_tracks("x")) == []

    @pytest.mark.xfail(strict=True, reason=V3_BUG)
    def test_load_failed_raises_with_severity_and_message(self):
        data = {"loadType": "LOAD_FAILED", "exception": {"severity": "COMMON", "message": "falhou"}}
        with pytest.raises(TrackLoadError, match="falhou"):
            run(make_node(Resposta(data=data), version=3).get_tracks("x"))


class TestPlaylists:
    def playlist(self, ids=("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")):
        return {
            "loadType": "playlist",
            "data": {
                "info": {"name": "Minha lista"},
                "pluginInfo": {},
                "tracks": [{"encoded": f"E{i}", "info": info(f"T{i}", identifier=i)} for i in ids],
            },
        }

    def test_playlist_becomes_a_track_playlist(self):
        result = run(make_node(Resposta(data=self.playlist())).get_tracks("https://exemplo.test/lista"))
        assert isinstance(result, TrackPlaylist) and len(result.tracks) == 3
        assert result.data["playlistInfo"] == {"name": "Minha lista"}

    def test_spotify_playlist_is_cached_and_served_from_the_cache(self):
        cache = {}
        node = make_node(Resposta(data=self.playlist()), cache=cache)
        run(node.get_tracks("https://open.spotify.com/playlist/37i9dQZF1DX"))
        assert "spotify:playlist:37i9dQZF1DX" in cache

        outro = make_node(Resposta(status=500), cache=cache)
        again = run(outro.get_tracks("https://open.spotify.com/playlist/37i9dQZF1DX"))
        assert isinstance(again, TrackPlaylist) and outro.session.chamadas == []

    def test_deezer_and_soundcloud_playlists_have_their_own_cache_keys(self):
        cache = {}
        run(make_node(Resposta(data=self.playlist()), cache=cache).get_tracks("https://www.deezer.com/br/playlist/123"))
        run(
            make_node(Resposta(data=self.playlist()), cache=cache).get_tracks(
                "https://soundcloud.com/usuario/sets/lista"
            )
        )
        assert {"deezer:playlist:123", "soundcloud:usuario:lista"} <= set(cache)

    def test_youtube_playlist_with_a_video_starts_at_that_video(self):
        cache = {}
        node = make_node(Resposta(data=self.playlist()), cache=cache)
        url = "https://www.youtube.com/watch?v=bbbbbbbbbbb&list=PLabc"
        result = run(node.get_tracks(url))
        assert [t.id for t in result.tracks] == ["Ebbbbbbbbbbb", "Eccccccccccc", "Eaaaaaaaaaaa"]
        assert "youtube:PLabc" in cache

    def test_youtube_mix_playlists_are_never_cached(self):
        cache = {}
        run(
            make_node(Resposta(data=self.playlist()), cache=cache).get_tracks(
                "https://www.youtube.com/playlist?list=RDabc"
            )
        )
        assert cache == {}

    def test_missing_video_refetches_the_whole_playlist(self):
        cache = {"youtube:PLabc": self.playlist()}
        node = make_node(Resposta(data=self.playlist(("xxxxxxxxxxx",))), cache=cache)
        url = "https://www.youtube.com/watch?v=zzzzzzzzzzz&list=PLabc"
        result = run(node.get_tracks(url))
        assert isinstance(result, TrackPlaylist)
        assert (
            node.session.chamadas[-1][1].endswith(
                "identifier=https%3A//www.youtube.com/playlist%3Flist%3DPLabc".replace("%3A//", "%3A//")
            )
            or "playlist%3Flist%3DPLabc" in node.session.chamadas[-1][1]
        )

    def test_youtube_music_album_playlist_is_renamed(self):
        data = self.playlist()
        data["data"]["info"]["name"] = "Album - Disco"
        data["data"]["pluginInfo"] = {}
        result = run(make_node(Resposta(data=data)).get_tracks("https://music.youtube.com/playlist?list=OLAK5uy"))
        assert result.data["playlistInfo"]["name"] == "Disco"

    def test_playlist_that_does_not_exist_falls_back_to_the_video(self):
        erro = {"loadType": "error", "data": {"message": "The playlist does not exist.", "severity": "common"}}
        node = make_node(Resposta(data=erro), Resposta(data=v4_search("Video")))
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc"
        tracks = run(node.get_tracks(url))
        assert [t.title for t in tracks] == ["Video"]
        assert "watch%3Fv%3DdQw4w9WgXcQ" in node.session.chamadas[-1][1]

    def test_video_that_cannot_be_loaded_inside_a_playlist_falls_back_to_the_video(self):
        erro = {"loadType": "error", "data": {"message": "This video cannot be loaded.", "severity": "common"}}
        node = make_node(Resposta(data=erro), Resposta(data=v4_search("Video")))
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc"
        assert [t.title for t in run(node.get_tracks(url))] == ["Video"]


class TestCheckTitle:
    def test_titles_far_from_the_search_are_dropped(self):
        node = make_node(Resposta(data=v4_search("Imagine Dragons - Believer", "Outra Coisa Totalmente Diferente")))
        tracks = run(node.get_tracks("ytsearch:imagine dragons believer", check_title=70))
        assert [t.title for t in tracks] == ["Imagine Dragons - Believer"]

    def test_remix_is_dropped_unless_the_search_asks_for_it(self):
        node = make_node(Resposta(data=v4_search("Believer", "Believer remix")))
        assert [t.title for t in run(node.get_tracks("ytsearch:believer", check_title=10))] == ["Believer"]
        node = make_node(Resposta(data=v4_search("Believer", "Believer remix")))
        assert len(run(node.get_tracks("ytsearch:believer remix", check_title=10))) == 2

    def test_non_youtube_sources_compare_author_and_title(self):
        node = make_node(Resposta(data=v4_search("Believer", "Zzzz", source="spotify")))
        tracks = run(node.get_tracks("spsearch:autor believer", check_title=30))
        assert [t.title for t in tracks] == ["Believer"]

    def test_topic_channels_are_compared_with_the_artist_in_front(self):
        data = v4_search("Believer", "Believer", source="youtube")
        for item in data["data"]:
            item["info"]["author"] = "Imagine Dragons - topic"
        tracks = run(make_node(Resposta(data=data)).get_tracks("ytsearch:imagine dragons believer", check_title=50))
        assert len(tracks) == 2


# ============================================================================ REST


class TestUpdatePlayer:
    def make(self, *respostas):
        node = make_node(*respostas)
        node._websocket = SimpleNamespace(headers={"Authorization": "x"})
        return node

    def test_patches_the_session_player(self):
        node = self.make(Resposta(data={"ok": True}))
        assert run(node.update_player(7, {"volume": 50}, replace=True)) == {"ok": True}
        metodo, url, kwargs = node.session.chamadas[0]
        assert metodo == "patch" and url.endswith("/v4/sessions/sess/players/7?noReplace=False")
        assert kwargs["json"] == {"volume": 50}

    def test_no_replace_flag_is_inverted(self):
        node = self.make(Resposta(data={}))
        run(node.update_player(7, {}))
        assert node.session.chamadas[0][1].endswith("noReplace=True")

    def test_without_a_session_it_waits_for_a_new_node_when_the_player_exists(self):
        node = self.make()
        node.session_id = None
        player = MagicMock()
        player.bot.loop.create_task = MagicMock(return_value="tarefa")
        node._client.bot.music.players = {7: player}
        assert run(node.update_player(7, {})) is None
        assert player._new_node_task == "tarefa"

    def test_without_a_session_and_without_a_player_raises(self):
        node = self.make()
        node.session_id = None
        node._client.bot.music.players = {}
        with pytest.raises(MissingSessionID):
            run(node.update_player(7, {}))

    def test_after_three_failures_it_hands_the_player_to_another_node(self, no_sleep):
        node = self.make(Resposta(status=500, data={"e": 1}))
        outro = SimpleNamespace(identifier="no-2")
        node._client.get_best_node.return_value = outro
        player = MagicMock()
        player.change_node = AsyncMock()
        node.players[7] = player
        assert run(node.update_player(7, {})) is None
        player.change_node.assert_awaited_once_with("no-2")
        assert len(node.session.chamadas) == 3 and no_sleep.await_count == 3

    def test_after_three_failures_without_another_node_it_raises(self):
        node = self.make(Resposta(status=502, data={"e": 1}))
        node._client.get_best_node.return_value = None
        with pytest.raises(WavelinkException, match="UpdatePlayer Failed = 502"):
            run(node.update_player(7, {}))

    def test_non_json_failure_body_is_read_as_text(self):
        node = self.make(Resposta(status=500, json_error=ValueError, text="texto cru"))
        node._client.get_best_node.return_value = None
        with pytest.raises(WavelinkException, match="texto cru"):
            run(node.update_player(7, {}))


class TestBuildTrack:
    def test_v4_decodes_through_the_v4_endpoint(self):
        node = make_node(Resposta(data={"info": info("Decodificada")}))
        track = run(node.build_track("ENC"))
        assert track.title == "Decodificada" and track.id == "ENC"
        metodo, url, kwargs = node.session.chamadas[0]
        assert url.endswith("/v4/decodetrack") and kwargs["params"] == {"encodedTrack": "ENC"}

    def test_v3_decodes_through_the_legacy_endpoint(self):
        node = make_node(Resposta(data=info("Antiga")), version=3)
        assert run(node.build_track("ENC")).title == "Antiga"
        assert node.session.chamadas[0][2]["params"] == {"track": "ENC"}

    def test_error_status_raises_build_track_error(self):
        node = make_node(Resposta(status=400, data={"status": 400, "error": "Bad Request"}))
        with pytest.raises(BuildTrackError, match="Bad Request"):
            run(node.build_track("ENC"))


class TestLyricsAndPotoken:
    def test_lyrics_require_the_plugin(self):
        node = make_node()
        node.info["plugins"] = {}
        with pytest.raises(Exception, match="Lyrics plugin not available"):
            run(node.fetch_ytm_lyrics("abc"))

    def test_lyrics_are_fetched_with_the_node_headers(self):
        node = make_node(Resposta(data={"lines": []}))
        node.info["plugins"] = {"lyrics": "1"}
        assert run(node.fetch_ytm_lyrics("abc")) == {"lines": []}
        assert node.session.chamadas[0][1].endswith("/v4/lyrics/abc")
        assert node.session.chamadas[0][2]["headers"] == node.headers

    def test_lyrics_missing_is_not_an_error(self):
        node = make_node(Resposta(status=404, data={}))
        node.info["plugins"] = {"lyrics": "1"}
        assert run(node.fetch_ytm_lyrics("abc")) == {}

    def test_lyrics_server_error_raises(self):
        node = make_node(Resposta(status=500, data={}))
        node.info["plugins"] = {"lyrics": "1"}
        with pytest.raises(RuntimeError):
            run(node.fetch_ytm_lyrics("abc"))

    def test_refresh_potoken_posts_the_generated_tokens(self, monkeypatch):
        class Navegador:
            def __init__(self):
                self.data = {"po_token": "PO", "visitor_data": "VD"}

            async def start(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.setattr(node_module, "Browser", Navegador)
        node = make_node(Resposta(status=204, text="feito"))
        node._websocket = SimpleNamespace(headers={"H": "1"})
        node._client.bot.config = {"POTOKEN_YTID": "abcdefghijk"}
        assert run(node.refresh_potoken()) == "204: feito"
        assert node.session.chamadas[0][2]["json"] == {"poToken": "PO", "visitorData": "VD"}

    def test_refresh_potoken_reraises_when_the_browser_produced_nothing(self, monkeypatch):
        class Navegador:
            data = None

            async def start(self, **kwargs):
                raise RuntimeError("sem navegador")

        monkeypatch.setattr(node_module, "Browser", Navegador)
        node = make_node()
        with pytest.raises(RuntimeError, match="sem navegador"):
            run(node.refresh_potoken())


# ============================================================================ eventos e ciclo de vida


class TestEventsAndLifecycle:
    def event(self):
        return SimpleNamespace(player=SimpleNamespace(hook=AsyncMock()))

    def test_event_reaches_the_player_hook_and_the_sync_node_hook(self):
        node = make_node()
        node.set_hook(received := MagicMock())
        event = self.event()
        run(node.on_event(event))
        event.player.hook.assert_awaited_once_with(event)
        received.assert_called_once_with(event)

    def test_async_hook_is_awaited(self):
        node = make_node()
        node.set_hook(hook := AsyncMock())
        run(node.on_event(self.event()))
        hook.assert_awaited_once()

    def test_without_a_hook_only_the_player_is_notified(self):
        event = self.event()
        run(make_node().on_event(event))
        event.player.hook.assert_awaited_once()

    def test_hook_must_be_callable(self):
        with pytest.raises(WavelinkException, match="callable"):
            make_node().set_hook("não chamável")

    def test_destroy_destroys_players_and_removes_the_node(self):
        node = make_node()
        player = SimpleNamespace(destroy=AsyncMock())
        node.players[1] = player
        node._websocket = SimpleNamespace(_task=MagicMock())
        run(node.destroy(force=True))
        player.destroy.assert_awaited_once_with(force=True)
        node._websocket._task.cancel.assert_called_once()
        assert node._closing is True and "no-1" not in node._client.nodes

    def test_send_forwards_to_the_websocket(self):
        node = make_node()
        node._websocket = SimpleNamespace(_send=AsyncMock())
        run(node._send(op="play", x=1))
        node._websocket._send.assert_awaited_once_with(op="play", x=1)


class TestConnect:
    def bot_session(self, status=200, data=None, text="", raises=None):
        resposta = Resposta(status=status, data=data or {"sourceManagers": ["youtube"], "plugins": []}, text=text)

        class Sessao2:
            def __init__(self):
                self.chamadas = 0

            def get(self, url, **kwargs):
                self.chamadas += 1
                if raises:
                    raise raises
                return Contexto(resposta)

        return Sessao2()

    def prepared(self, session):
        node = make_node()
        node.version = 0
        node._client.bot.session = session
        node._client.bot.is_closed.return_value = False
        node._websocket = SimpleNamespace(is_connected=False, _connect=AsyncMock())
        return node

    def test_already_connecting_returns_immediately(self):
        node = make_node()
        node._is_connecting = True
        run(node.connect())
        assert node._is_connecting is True

    def test_info_in_kwargs_skips_discovery_and_connects_the_websocket(self):
        node = self.prepared(self.bot_session())
        run(node.connect(info={"check_version": 4, "plugins": [], "sourceManagers": []}))
        node._websocket._connect.assert_awaited_once()
        assert node.version == 4 and node.available is True and node._is_connecting is False

    def test_v4_discovery(self, capsys):
        node = self.prepared(self.bot_session())
        run(node.connect())
        assert node.version == 4 and node.info["sourceManagers"] == ["youtube"]
        node._websocket._connect.assert_awaited_once()

    def test_404_means_lavalink_v3_and_skips_the_websocket(self, capsys):
        node = self.prepared(self.bot_session(status=404))
        run(node.connect())
        assert node.version == 3 and node.info["sourceManagers"] == ["youtube", "soundcloud", "http"]
        node._websocket._connect.assert_not_awaited()

    def test_persistent_failure_gives_up_after_the_retries(self, capsys):
        node = self.prepared(self.bot_session(raises=OSError("recusado")))
        node.max_retries = 1
        run(node.connect())
        assert node._is_connecting is False and node.version == 0
        assert "Falha ao conectar" in capsys.readouterr().out

    def test_retries_then_succeeds(self, capsys, no_sleep):
        session = self.bot_session()
        original = session.get
        estado = {"n": 0}

        def instavel(url, **kwargs):
            estado["n"] += 1
            if estado["n"] == 1:
                raise OSError("primeira falha")
            return original(url, **kwargs)

        session.get = instavel
        node = self.prepared(session)
        node.max_retries = 3
        run(node.connect())
        assert node.version == 4 and no_sleep.await_count == 1
        assert "nova tentativa" in capsys.readouterr().out

    def test_unexpected_status_is_retried_as_an_error(self, capsys):
        node = self.prepared(self.bot_session(status=500, text="erro interno"))
        node.max_retries = 1
        run(node.connect())
        assert node.version == 0 and "Falha ao conectar" in capsys.readouterr().out

    def test_websocket_is_created_when_missing(self, monkeypatch):
        criado = {}

        class SocketFalso:
            is_connected = False

            def __init__(self, **kwargs):
                criado.update(kwargs)

            async def _connect(self):
                criado["conectou"] = True

        monkeypatch.setattr(node_module, "WebSocket", SocketFalso)
        node = self.prepared(self.bot_session())
        node._websocket = None
        run(node.connect(info={"check_version": 4, "plugins": [], "sourceManagers": []}))
        assert criado["host"] == "host" and criado["password"] == "senha" and criado["conectou"] is True


# ============================================================================ backoff


class TestExponentialBackoff:
    def test_delay_is_bounded_by_the_growing_ceiling(self):
        backoff = ExponentialBackoff(base=1)
        for exp in range(1, 5):
            assert 0 <= backoff.delay() <= 2**exp

    def test_ceiling_stops_growing_at_the_maximum_exponent(self):
        backoff = ExponentialBackoff(base=1)
        for _ in range(30):
            valor = backoff.delay()
        assert backoff._exp == 10 and 0 <= valor <= 2**10

    def test_integral_mode_returns_whole_numbers(self):
        backoff = ExponentialBackoff(base=1, integral=True)
        assert all(isinstance(backoff.delay(), int) for _ in range(5))

    def test_exponent_resets_after_a_long_quiet_period(self, monkeypatch):
        backoff = ExponentialBackoff(base=1)
        for _ in range(5):
            backoff.delay()
        assert backoff._exp == 5
        backoff._last_invocation -= backoff._reset_time + 1
        backoff.delay()
        assert backoff._exp == 1

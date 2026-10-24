"""KI-27 — caracterização de `empiremuse/wavelink/node.py` (nó Lavalink v3/v4: busca de faixas, REST e ciclo de vida) e `backoff.py`.

Sem rede: a sessão HTTP é um dublê que devolve respostas prontas e registra as URLs pedidas. As esperas (`asyncio.sleep`) são
trocadas por um espião para o teste não demorar.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.wavelink import node as node_module
from empiremuse.wavelink.node import Node


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


# ============================================================================ estado e propriedades


class TestNodeState:
    def test_get_player(self):
        node = make_node()
        node.players[1] = "p"
        assert node.get_player(1) == "p" and node.get_player(2) is None


# ============================================================================ busca de faixas


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

    def test_youtube_playlist_with_a_video_starts_at_that_video(self):
        cache = {}
        node = make_node(Resposta(data=self.playlist()), cache=cache)
        url = "https://www.youtube.com/watch?v=bbbbbbbbbbb&list=PLabc"
        result = run(node.get_tracks(url))
        assert [t.id for t in result.tracks] == ["Ebbbbbbbbbbb", "Eccccccccccc", "Eaaaaaaaaaaa"]
        assert "youtube:PLabc" in cache


# ============================================================================ REST


class TestBuildTrack:
    def test_v4_decodes_through_the_v4_endpoint(self):
        node = make_node(Resposta(data={"info": info("Decodificada")}))
        track = run(node.build_track("ENC"))
        assert track.title == "Decodificada" and track.id == "ENC"
        metodo, url, kwargs = node.session.chamadas[0]
        assert url.endswith("/v4/decodetrack") and kwargs["params"] == {"encodedTrack": "ENC"}


# ============================================================================ eventos e ciclo de vida


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

    def test_404_means_lavalink_v3_and_skips_the_websocket(self, capsys):
        node = self.prepared(self.bot_session(status=404))
        run(node.connect())
        assert node.version == 3 and node.info["sourceManagers"] == ["youtube", "soundcloud", "http"]
        node._websocket._connect.assert_not_awaited()

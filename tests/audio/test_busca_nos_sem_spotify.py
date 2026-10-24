"""PR #31 (7ad9366c) — `Music.get_lavalink_tracks` ignora nós sem o source manager do Spotify quando a consulta é um link do Spotify.

Sem rede e sem Discord reais: nós e cog são dublês simples (SimpleNamespace / AsyncMock).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.regression

SPOTIFY_TRACK = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
SPOTIFY_SHORT = "https://spotify.link/AbC123xYz"


def run(coro):
    return asyncio.run(coro)


def make_node(identifier, source_managers, players=0, tracks=("faixa",)):
    return SimpleNamespace(
        identifier=identifier,
        is_available=True,
        available=True,
        players=[None] * players,
        info={"sourceManagers": list(source_managers)},
        search_providers=["ytsearch"],
        get_tracks=AsyncMock(return_value=list(tracks)),
    )


def search(nodes, query, node=None):
    from empiremuse.cogs.music import Music

    cog = SimpleNamespace(
        bot=SimpleNamespace(music=SimpleNamespace(nodes={n.identifier: n for n in nodes}), pool=SimpleNamespace())
    )
    return run(Music.get_lavalink_tracks(cog, query, ctx=None, user=SimpleNamespace(id=1), node=node, source=False))


@pytest.mark.parametrize("query", [SPOTIFY_TRACK, SPOTIFY_SHORT])
class TestSpotifyUrlSkipsNodesWithoutSpotify:
    def test_requested_node_without_spotify_is_skipped_and_the_resolving_node_is_returned(self, query):
        pedido = make_node("pedido", ["youtube"])
        outro = make_node("outro", ["youtube", "spotify"], players=3)

        tracks, node, _ = search([pedido, outro], query, node=pedido)

        pedido.get_tracks.assert_not_awaited()
        outro.get_tracks.assert_awaited_once()
        assert tracks == ["faixa"]
        assert node is outro

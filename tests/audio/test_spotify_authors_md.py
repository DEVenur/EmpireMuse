"""V-AS-1 / S-31 — nome de artista vindo do Spotify (ou do Deezer) nunca cria um link mascarado a mais em ``authors_md``.

``authors_md`` monta ``[`nome`](url)`` com o nome do artista dentro de crases. Um nome com crase, colchetes ou texto de link mascarado fecharia o
link e abriria outro (``[x](https://mal.exemplo)``). O ``fix_characters`` troca crase por apóstrofo e ``[ ]`` por ``【 】``: a estrutura do
Markdown tem de ser SEMPRE a esperada, um ``[`…`](…)`` por artista. Cobre os construtores de ``audio_sources/spotify.py`` (busca, link de faixa,
álbum de uma faixa e playlist) e os de ``_aq_source_tracks`` (Spotify e Deezer). Sem rede: ``track_search`` e as ``get_*_info`` são dublês.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.utils.music.audio_sources.spotify import SpotifyClient
from empiremuse.utils.music.models import autoqueue_steps
from tests.audio.test_autoplay_spotify import contexto, pedido

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

NOMES_HOSTIS = [
    "Mau`](https://mal.exemplo) [clique](https://mal2.exemplo) `x",
    "[phishing](https://mal.exemplo)",
    "`codigo` e [colchetes]",
    "fecha ](https://mal.exemplo)(",
    "```bloco```",
    "[`dentro`](<https://mal.exemplo>)",
]


def artista(nome: str, n: int) -> dict:
    return {"id": f"ar{n}", "name": nome, "external_urls": {"spotify": f"https://open.spotify.com/artist/ar{n}"}}


def faixa(nomes: list[str]) -> dict:
    return {
        "id": "t1",
        "name": "Musica",
        "duration_ms": 200_000,
        "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
        "external_ids": {"isrc": "BR0000000001"},
        "artists": [artista(nome, n) for n, nome in enumerate(nomes)],
        "album": {
            "name": "Album",
            "total_tracks": 1,
            "images": [{"url": "https://i.scdn.co/image/1"}],
            "external_urls": {"spotify": "https://open.spotify.com/album/al1"},
        },
    }


def estrutura_intacta(authors_md: str, artistas: int) -> None:
    """Um ``[`nome`](destino)`` por artista e nenhum colchete, parêntese de fechamento ou crase solto a mais."""
    assert authors_md.count("[") == artistas and authors_md.count("]") == artistas, authors_md
    assert authors_md.count("](") == artistas, authors_md
    assert authors_md.count("`") == 2 * artistas, authors_md
    assert authors_md.count("[`") == artistas and authors_md.count("`]") == artistas, authors_md


def cliente() -> SpotifyClient:
    c = SpotifyClient.__new__(SpotifyClient)
    c.clock, c._paused_until = time.monotonic, 0.0
    return c


def bot_falso():
    return SimpleNamespace(
        session=MagicMock(),
        pool=SimpleNamespace(playlist_cache={}),
        music=SimpleNamespace(nodes={}),
        user=SimpleNamespace(id=1),
    )


@pytest.mark.parametrize("nome", NOMES_HOSTIS, ids=lambda n: n[:20])
class TestConstrutoresDoSpotify:
    async def test_the_search_result_builder(self, nome):
        c = cliente()
        c.track_search = AsyncMock(return_value={"tracks": {"items": [faixa(["Normal", nome])]}})

        (t,) = await c.get_tracks(bot_falso(), 7, "Normal Musica")

        estrutura_intacta(t.info["extra"]["authors_md"], 2)

    async def test_the_track_link_builder(self, nome):
        c = cliente()
        c.get_track_info = AsyncMock(return_value=faixa([nome, "Normal"]))

        (t,) = await c.get_tracks(bot_falso(), 7, "https://open.spotify.com/track/t1")

        estrutura_intacta(t.info["extra"]["authors_md"], 2)

    async def test_the_single_track_album_builder(self, nome):
        c = cliente()
        unica = faixa([nome])
        c.get_album_info = AsyncMock(
            return_value={
                "name": "Album",
                "total_tracks": 1,
                "external_urls": {"spotify": "https://open.spotify.com/album/al1"},
                "images": [{"url": "https://i.scdn.co/image/1"}],
                "tracks": [unica],
            }
        )

        (t,) = await c.get_tracks(bot_falso(), 7, "https://open.spotify.com/album/al1")

        estrutura_intacta(t.info["extra"]["authors_md"], 1)

    async def test_the_playlist_builder(self, nome):
        c = cliente()
        c.get_playlist_info = AsyncMock(
            return_value={
                "name": "Lista",
                "images": [],
                "tracks": {"items": [{"track": faixa([nome, "Normal"])}]},
            }
        )

        playlist = await c.get_tracks(bot_falso(), 7, "https://open.spotify.com/playlist/pl1")

        faixas = getattr(playlist, "tracks", playlist)
        assert faixas
        for t in faixas:
            estrutura_intacta(t.info["extra"]["authors_md"], 2)


@pytest.mark.parametrize("nome", NOMES_HOSTIS, ids=lambda n: n[:20])
class TestConstrutoresDoAutoplay:
    async def test_the_spotify_autoplay_builder(self, nome):
        cli = SimpleNamespace()
        cli.track_search = AsyncMock(return_value={"tracks": {"items": [faixa(["Normal", nome])]}})
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cli), req)

        assert req.tracks
        estrutura_intacta(req.tracks[0].info["extra"]["authors_md"], 2)

    async def test_the_deezer_autoplay_builder(self, nome):
        radio = [
            {
                "id": 11,
                "title": "Musica",
                "duration": 200,
                "isrc": "BR0000000001",
                "artist": {"id": 5, "name": "Normal"},
                "album": {
                    "title": "Album",
                    "cover_big": "https://cdn.exemplo/c.jpg",
                    "tracklist": "https://api.deezer.com/album/1/tracks",
                },
                "contributors": [{"id": 5, "name": "Normal"}, {"id": 6, "name": nome}],
            }
        ]
        ctx = contexto(None)
        ctx.bot.deezer = SimpleNamespace(get_artist_radio_info=AsyncMock(return_value=radio))
        ctx.bot.pool.config = {"FORCE_USE_DEEZER_CLIENT": True}
        req = pedido()
        req.track_data.info = {"sourceName": "deezer", "extra": {"artist_id": 5}}

        await autoqueue_steps._aq_source_tracks(ctx, req)

        assert req.tracks
        estrutura_intacta(req.tracks[0].info["extra"]["authors_md"], 2)


class TestGuardaDoProprioHelper:
    def test_the_structure_check_catches_an_extra_masked_link(self):
        with pytest.raises(AssertionError):
            estrutura_intacta("[`A`](u), [`B`](v), [clique](https://mal.exemplo)", 2)
        with pytest.raises(AssertionError):
            estrutura_intacta("[`Mau`](https://mal.exemplo) [x](y) `z`](u)", 1)

    def test_a_normal_value_passes(self):
        estrutura_intacta("[`A`](u), [`B`](<v>)", 2)

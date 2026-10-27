"""Bug de produção (2.1.0): o autoplay com a fila vazia e uma faixa do Spotify num nó sem o gerenciador do Spotify quebrava.

``autoqueue_steps._aq_source_tracks`` chamava ``SpotifyClient.track_search(autor, limit=100)``, mas o método não tinha ``limit``: ``TypeError``,
repetido 3× com ``sleep(5)`` (15 s de atraso e 3 tracebacks toda vez que a fila acabava). Além disso o laço lia ``result["tracks"]`` quando a
busca devolve ``{"tracks": {"items": [...]}}``. Aqui: (a) o ``limit`` chega à busca, preso ao intervalo que a API aceita; (b) o caminho completo
devolve ``PartialTrack`` sem exceção e sem ``sleep``; (c) erro não transitório não é repetido, transitório repete até 3×; (d) ``TrackNotFound`` de
um provedor segue para o próximo sem traceback e sem WARNING+.

Limite da API de busca do Spotify: documentação oficial (developer.spotify.com, "Search for Item"), ``limit`` de 0 a 10, padrão 5; o bot sempre
manda o valor, então o intervalo efetivo aqui é 1..10 (0 não busca nada).

Sem rede e sem ``sleep`` real: o ``request`` do cliente e o ``asyncio.sleep`` do módulo são dublês.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.audio_sources.spotify import SpotifyClient
from empiremuse.utils.music.models import autoqueue_steps
from empiremuse.utils.music.models.tracks import PartialTrack

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

MAX_LIMIT_DA_API = 10


def item(n: int) -> dict:
    return {
        "id": f"id{n}",
        "name": f"Faixa {n}",
        "duration_ms": 200_000 + n,
        "external_urls": {"spotify": f"https://open.spotify.com/track/id{n}"},
        "artists": [
            {"name": "Artista", "external_urls": {"spotify": "https://open.spotify.com/artist/a1"}},
            {"name": f"Convidado {n}", "external_urls": {"spotify": f"https://open.spotify.com/artist/c{n}"}},
        ],
        "album": {
            "name": f"Álbum {n}",
            "images": [{"url": f"https://i.scdn.co/image/{n}", "height": 640, "width": 640}],
            "external_urls": {"spotify": f"https://open.spotify.com/album/al{n}"},
        },
    }


def resposta_da_busca(quantos: int = 3) -> dict:
    """Formato real de ``GET /v1/search?type=track``: ``{"tracks": {"items": [...]}}``, não uma lista na raiz."""
    return {
        "tracks": {
            "href": "https://api.spotify.com/v1/search",
            "limit": 10,
            "offset": 0,
            "total": 500,
            "items": [item(n) for n in range(quantos)],
        }
    }


def cliente_spotify(resposta=None, erro=None):
    cliente = SpotifyClient.__new__(SpotifyClient)
    cliente.request = AsyncMock(return_value=resposta, side_effect=erro)
    return cliente


# ============================================================================ (a) track_search encaminha o limit


class TestTrackSearchLimit:
    async def test_the_default_limit_is_ten_and_the_query_and_type_are_sent(self):
        cliente = cliente_spotify(resposta_da_busca())

        await cliente.track_search("Artista")

        params = cliente.request.await_args.kwargs["params"]
        assert cliente.request.await_args.kwargs["path"] == "search"
        assert params == {"q": "Artista", "type": "track", "limit": 10}

    @pytest.mark.parametrize(
        ("pedido", "enviado"), [(1, 1), (3, 3), (10, 10), (11, 10), (50, 10), (100, 10), (0, 1), (-5, 1)]
    )
    async def test_the_limit_is_forwarded_clamped_to_the_range_the_api_accepts(self, pedido, enviado):
        cliente = cliente_spotify(resposta_da_busca())

        await cliente.track_search("Artista", limit=pedido)

        assert cliente.request.await_args.kwargs["params"]["limit"] == enviado

    async def test_the_limit_never_exceeds_the_documented_maximum(self):
        cliente = cliente_spotify(resposta_da_busca())

        await cliente.track_search("Artista", limit=10**6)

        assert cliente.request.await_args.kwargs["params"]["limit"] <= MAX_LIMIT_DA_API

    async def test_the_limit_is_a_keyword_that_the_autoplay_call_accepts(self):
        cliente = cliente_spotify(resposta_da_busca())

        assert await cliente.track_search("Artista", limit=100) == resposta_da_busca()  # não levanta TypeError


# ============================================================================ o passo do autoplay


def contexto(spotify, *, gerenciadores=("youtube", "soundcloud")):
    return SimpleNamespace(
        bot=SimpleNamespace(
            spotify=spotify,
            user=SimpleNamespace(id=999),
            pool=SimpleNamespace(config={"FORCE_USE_DEEZER_CLIENT": False}),
        ),
        node=SimpleNamespace(info={"sourceManagers": list(gerenciadores)}, search_providers=["ytsearch", "scsearch"]),
        set_command_log=MagicMock(),
        update=False,
    )


def pedido(artista="Artista"):
    faixa = SimpleNamespace(
        author=artista,
        title="Musica",
        uri="https://open.spotify.com/track/semente",
        ytid=None,
        info={"sourceName": "spotify", "extra": {}},
    )
    return SimpleNamespace(
        exception=None, t=None, track_data=faixa, tracks=[], tracks_search=[faixa], tracks_ytsearch=[]
    )


@pytest.fixture
def sem_espera(monkeypatch):
    dormir = AsyncMock()
    monkeypatch.setattr(autoqueue_steps.asyncio, "sleep", dormir)
    return dormir


class TestFonteSpotify:
    async def test_a_node_without_the_spotify_source_manager_gets_partial_tracks_from_the_search(
        self, sem_espera, capsys
    ):
        cliente = cliente_spotify(resposta_da_busca(3))
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        assert req.exception is None and len(req.tracks) == 3
        assert all(isinstance(t, PartialTrack) for t in req.tracks)
        primeira = req.tracks[0]
        assert primeira.info["uri"] == "https://open.spotify.com/track/id0"
        assert primeira.info["author"] == "Artista" and primeira.info["title"] == "Faixa 0"
        assert primeira.info["length"] == 200_000
        assert primeira.info["sourceName"] == "spotify" and primeira.info["extra"]["autoplay"] is True
        assert primeira.info["extra"]["requester"] == 999
        sem_espera.assert_not_awaited()
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err

    async def test_the_search_is_asked_for_the_seed_artist_with_a_limit_the_api_accepts(self, sem_espera):
        cliente = cliente_spotify(resposta_da_busca(1))

        await autoqueue_steps._aq_source_tracks(contexto(cliente), pedido("Banda X"))

        params = cliente.request.await_args.kwargs["params"]
        assert params["q"] == "Banda X" and 1 <= params["limit"] <= MAX_LIMIT_DA_API

    async def test_extra_fields_of_the_tracks_are_filled_from_the_real_payload(self, sem_espera):
        cliente = cliente_spotify(resposta_da_busca(1))
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        extra = req.tracks[0].info["extra"]
        assert extra["thumb"] == "https://i.scdn.co/image/0"
        assert "Artista" in extra["authors"] and "Convidado 0" in extra["authors"]
        assert "open.spotify.com/artist/a1" in extra["authors_md"]
        assert extra["album"] == {"name": "Álbum 0", "url": "https://open.spotify.com/album/al0"}

    async def test_an_empty_search_result_gives_no_tracks_and_no_error(self, sem_espera):
        cliente = cliente_spotify({"tracks": {"items": []}})
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        assert req.tracks == [] and req.exception is None
        sem_espera.assert_not_awaited()

    async def test_a_node_with_the_spotify_source_manager_does_not_use_the_client(self, sem_espera):
        cliente = cliente_spotify(resposta_da_busca())
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente, gerenciadores=("youtube", "spotify")), req)

        cliente.request.assert_not_awaited()
        assert req.tracks == []


# ============================================================================ (c) o que se repete e o que não se repete


class TestRepeticao:
    @pytest.mark.parametrize(
        "erro",
        [TypeError("limit"), KeyError("tracks"), ValueError("x"), AttributeError("y")],
        ids=lambda e: type(e).__name__,
    )
    async def test_a_non_transient_error_is_not_retried_and_does_not_sleep(self, sem_espera, capsys, erro):
        cliente = cliente_spotify(erro=erro)
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        assert cliente.request.await_count == 1
        sem_espera.assert_not_awaited()
        assert req.exception is erro and req.tracks == []
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err

    @pytest.mark.parametrize(
        "erro",
        [aiohttp.ClientConnectionError("caiu"), aiohttp.ServerDisconnectedError(), asyncio.TimeoutError()],
        ids=lambda e: type(e).__name__,
    )
    async def test_a_transient_error_is_retried_up_to_three_times(self, sem_espera, capsys, erro):
        cliente = cliente_spotify(erro=erro)
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        assert cliente.request.await_count == 3
        assert 1 <= sem_espera.await_count <= 3 and all(c.args == (5,) for c in sem_espera.await_args_list)
        assert req.exception is erro and req.tracks == []
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err

    async def test_a_transient_error_followed_by_success_returns_the_tracks(self, sem_espera):
        cliente = cliente_spotify()
        cliente.request = AsyncMock(side_effect=[aiohttp.ClientConnectionError("caiu"), resposta_da_busca(2)])
        req = pedido()

        await autoqueue_steps._aq_source_tracks(contexto(cliente), req)

        assert cliente.request.await_count == 2 and len(req.tracks) == 2

    async def test_the_user_is_told_about_each_transient_retry(self, sem_espera):
        cliente = cliente_spotify(erro=asyncio.TimeoutError())
        ctx = contexto(cliente)

        await autoqueue_steps._aq_source_tracks(ctx, pedido())

        assert ctx.set_command_log.call_count == 3

    async def test_a_non_transient_error_does_not_tell_the_user_to_wait_for_a_retry(self, sem_espera):
        cliente = cliente_spotify(erro=TypeError("limit"))
        ctx = contexto(cliente)

        await autoqueue_steps._aq_source_tracks(ctx, pedido())

        assert not any("tentativa" in str(c) for c in ctx.set_command_log.call_args_list)


# ============================================================================ (d) TrackNotFound de um provedor segue para o próximo


def contexto_lastfm(get_tracks):
    return SimpleNamespace(
        bot=SimpleNamespace(last_fm=None, user=SimpleNamespace(id=999)),
        lastfm_artists=[],
        native_yt=False,
        node=SimpleNamespace(
            search_providers=["ytsearch", "scsearch"], get_tracks=get_tracks, info={"sourceManagers": []}
        ),
    )


def pedido_lastfm():
    faixa = SimpleNamespace(
        author="Artista",
        title="Musica",
        uri="https://open.spotify.com/track/semente",
        ytid=None,
        info={"sourceName": "spotify", "extra": {}},
    )
    return SimpleNamespace(
        exception=None, t=None, track_data=faixa, tracks=[], tracks_search=[faixa], tracks_ytsearch=[]
    )


class TestProvedorSemResultado:
    async def test_track_not_found_from_one_provider_moves_on_to_the_next_without_noise(
        self, sem_espera, caplog, capsys
    ):
        achada = SimpleNamespace(title="Outra", uri="https://youtube.com/watch?v=z")
        consultas = []

        async def get_tracks(consulta, **kwargs):
            consultas.append(consulta)
            if consulta.startswith("spsearch"):
                raise wavelink.TrackNotFound("Artista: Track not found...")
            return [achada]

        req = pedido_lastfm()
        caplog.set_level(logging.DEBUG)

        await autoqueue_steps._aq_lastfm_tracks(contexto_lastfm(get_tracks), req)

        assert req.tracks == [achada]
        assert consultas[0].startswith("spsearch") and len(consultas) == 2
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        sem_espera.assert_not_awaited()

    async def test_when_every_provider_finds_nothing_the_step_ends_quietly_with_no_tracks(
        self, sem_espera, caplog, capsys
    ):
        get_tracks = AsyncMock(side_effect=wavelink.TrackNotFound("nada"))
        req = pedido_lastfm()
        caplog.set_level(logging.DEBUG)

        await autoqueue_steps._aq_lastfm_tracks(contexto_lastfm(get_tracks), req)

        assert req.tracks == [] and get_tracks.await_count == 3
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        sem_espera.assert_not_awaited()

    async def test_the_not_found_detail_is_kept_at_debug_level(self, sem_espera, caplog):
        get_tracks = AsyncMock(
            side_effect=[wavelink.TrackNotFound("sem resultado aqui"), [SimpleNamespace(title="Z", uri="u")]]
        )
        caplog.set_level(logging.DEBUG)

        await autoqueue_steps._aq_lastfm_tracks(contexto_lastfm(get_tracks), pedido_lastfm())

        assert [r for r in caplog.records if r.levelno == logging.DEBUG and "sem resultado aqui" in r.getMessage()]

    async def test_a_different_error_from_a_provider_still_moves_on_to_the_next(self, sem_espera, capsys):
        achada = SimpleNamespace(title="Outra", uri="https://youtube.com/watch?v=z")
        get_tracks = AsyncMock(side_effect=[RuntimeError("falha de verdade"), [achada]])
        req = pedido_lastfm()

        await autoqueue_steps._aq_lastfm_tracks(contexto_lastfm(get_tracks), req)

        assert req.tracks == [achada]

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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.utils.music.audio_sources.spotify import SpotifyClient
from empiremuse.utils.music.models import autoqueue_steps
from empiremuse.utils.music.models.tracks import PartialTrack

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


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
    @pytest.mark.parametrize(
        ("pedido", "enviado"), [(1, 1), (3, 3), (10, 10), (11, 10), (50, 10), (100, 10), (0, 1), (-5, 1)]
    )
    async def test_the_limit_is_forwarded_clamped_to_the_range_the_api_accepts(self, pedido, enviado):
        cliente = cliente_spotify(resposta_da_busca())

        await cliente.track_search("Artista", limit=pedido)

        assert cliente.request.await_args.kwargs["params"]["limit"] == enviado


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


# ============================================================================ guardas: HTTP, sleep só entre tentativas, payload com campos nulos


class TestPayloadComCamposNulos:
    def sem(self, n, **campos):
        faixa = item(n)
        faixa.update(campos)
        return faixa

    async def rodar(self, itens, sem_espera):
        cliente = cliente_spotify({"tracks": {"items": itens}})
        req = pedido()
        ctx = contexto(cliente)
        ctx.locked = True
        await autoqueue_steps._aq_source_tracks(
            ctx, req
        )  # não pode levantar (senão o autoplay fica travado com locked=True)
        return req

    @pytest.mark.parametrize("campo", ["id", "external_urls"])
    async def test_an_item_without_id_or_uri_is_skipped_and_the_others_are_kept(self, sem_espera, campo):
        itens = [item(0), self.sem(1), item(2)]
        del itens[1][campo]

        req = await self.rodar(itens, sem_espera)

        assert [t.info["identifier"] for t in req.tracks] == ["id0", "id2"]

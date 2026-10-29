"""S-31, S2/S3/S3b/S5/S6 — escape de markdown por FONTE de nome externo, por renderizador alcançável, nos placeholders de skin e nas menções.

* S2: ``authors_md`` das faixas (``LavalinkTrack``/``PartialTrack``) e dos construtores do Spotify com nome E URL "com marcas".
* S3: embeds de ``event_steps`` (falha de faixa e faixa sem resultado). Os demais renderizadores têm o teste-guarda de AST (S4).
* S3b: ``skin_utils.replaces`` (placeholders de texto passam por ``fix_characters``, os de URL por ``md_url``).
* S5 saiu daqui: o teste de ``allowed_mentions`` do ``BotCore`` mora em ``feat/logs-erros`` (``client.py`` é do P4).
* S6: a INGESTÃO não escapa nada (o texto cru continua indo para busca e scrobble); o escape é só na exibição.
"""

import pytest

from empiremuse.utils.music.models.tracks import LavalinkTrack
from tests.support.marcas_md import (
    NOME_COM_CRASES,
    NOME_COM_MARCAS,
    links_alheios,
    marcas_soltas,
)

pytestmark = pytest.mark.critical


def faixa_lavalink(plugin=None, **info):
    """``LavalinkTrack`` como o Lavalink a entrega: o ``pluginInfo`` vai à parte do ``info`` (kwarg), não dentro dele."""
    return LavalinkTrack(id_="x", info=info_lavalink(**info), requester=1, pluginInfo=plugin or {})


def info_lavalink(**mais):
    base = {
        "title": "Titulo",
        "author": "Artista",
        "uri": "https://ok.exemplo/faixa",
        "length": 200_000,
        "identifier": "id1",
        "isStream": False,
        "sourceName": "soundcloud",
        "position": 0,
        "artworkUrl": "https://ok.exemplo/capa.png",
    }
    base.update(mais)
    return base


# ============================================================================ S2 — authors_md das faixas


class TestAutoresDasFaixas:
    @pytest.mark.parametrize(
        "autor", [NOME_COM_MARCAS, NOME_COM_CRASES, "Nome [x](u)"], ids=["marcas", "crases", "link"]
    )
    def test_a_lavalink_track_author_with_marks_cannot_make_an_extra_link(self, autor):
        faixa = faixa_lavalink({"artistUrl": "https://ok.exemplo/artista"}, author=autor)

        md = faixa.authors_md

        assert links_alheios(md) == [] and marcas_soltas(md) == 0
        assert md.count("](") == 1 and md.count("[`") == 1 and md.count("`") == 2

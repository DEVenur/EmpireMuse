"""S-31, S3 — cada skin do player (10 normais e 5 estáticas) escapa markdown nos nomes e nas URLs externos.

Reaproveita o harness de ``test_skins_caracterizacao`` (player e faixa falsos). A faixa tocando, a da fila e a da fila automática levam nome e
URL "com marcas" (``tests/support/marcas_md.py``); a saída de cada skin (``content`` e todos os textos dos embeds) não pode ter NENHUM link cujo
destino seja o domínio alheio, nem ``](`` solto. O controle benigno garante que o conferidor não acusa o que é legítimo.
"""

import pytest

from tests.audio.test_skins_caracterizacao import NORMAL, STATIC, STATES, make_player, make_track
from tests.support.marcas_md import (
    NOME_COM_COLCHETES,
    NOME_COM_MARCAS,
    URL_COM_MAIOR,
    URL_COM_PARENTESE,
    marcas_soltas,
    sem_link_alheio,
    textos_da_saida,
)

pytestmark = pytest.mark.critical

ESTADOS = {
    nome: estado
    for nome, estado in STATES.items()
    if nome in ("tocando", "pausado", "recomendada", "so_fila_automatica")
}


def faixa_hostil(**mais):
    base = dict(
        title=NOME_COM_MARCAS,
        single_title=NOME_COM_MARCAS,
        author=NOME_COM_MARCAS,
        uri=URL_COM_PARENTESE,
        search_uri=URL_COM_MAIOR,
        playlist_name=NOME_COM_MARCAS,
        playlist_url=URL_COM_PARENTESE,
        album_name=NOME_COM_COLCHETES,
        album_url=URL_COM_MAIOR,
        info={"sourceName": "youtube", "extra": {"related": {"uri": URL_COM_PARENTESE}}},
    )
    base.update(mais)
    return make_track(**base)


def jogador_hostil(**estado):
    """Player falso no estado pedido, com as MESMAS marcas na faixa atual e nas duas filas (o que o estado ajusta, como stream e autoplay, fica)."""
    parametros = {
        "current": faixa_hostil(),
        "queue": [faixa_hostil(), faixa_hostil(title=NOME_COM_COLCHETES, uri=URL_COM_MAIOR)],
        "queue_autoplay": [faixa_hostil()],
    }
    atual = estado.pop("current", None)
    if atual is not None:
        parametros["current"] = faixa_hostil(
            is_stream=atual.is_stream, duration=atual.duration, autoplay=atual.autoplay
        )
    for fila in ("queue", "queue_autoplay"):
        if fila in estado:
            parametros[fila] = [faixa_hostil() for _ in estado.pop(fila)]
    return make_player(**parametros, **estado)


@pytest.mark.parametrize("estado", ESTADOS.values(), ids=ESTADOS.keys())
@pytest.mark.parametrize("skin_cls", NORMAL + STATIC)
class TestSkinsComNomesExternos:
    def test_no_link_points_to_the_alien_domain(self, skin_cls, estado):
        dados = skin_cls().load(jogador_hostil(**estado))

        assert sem_link_alheio(textos_da_saida(dados)) == []

    def test_there_is_no_loose_link_opener_either(self, skin_cls, estado):
        dados = skin_cls().load(jogador_hostil(**estado))

        assert [marcas_soltas(texto) for texto in textos_da_saida(dados) if marcas_soltas(texto)] == []


@pytest.mark.parametrize("skin_cls", NORMAL + STATIC)
class TestControleBenigno:
    def test_ordinary_names_and_urls_still_render_and_link_normally(self, skin_cls):
        dados = skin_cls().load(make_player())

        assert sem_link_alheio(textos_da_saida(dados)) == []
        assert [marcas_soltas(t) for t in textos_da_saida(dados) if marcas_soltas(t)] == []

    def test_the_intended_title_link_is_still_there(self, skin_cls):
        dados = skin_cls().load(make_player(current=make_track(title="Titulo Normal", single_title="Titulo Normal")))

        texto = "\n".join(textos_da_saida(dados))
        assert "Titulo Normal" in texto

"""F3-6b, etapa 0 — caracterização da sessão do player no formato ATUAL (round-trip e legado, sem produção alterada).

Roda o ``PlayerSession.save_info`` REAL com faixas das classes reais (``LavalinkTrack``, ``PartialTrack``) e lê de volta
pelo ``get_player_sessions_local``/``get_player_sessions_mongo`` REAIS, no disco (``tmp_path``) e em um Mongo em memória.

Dois grupos:

* o que continua valendo depois da migração para JSON (``TestRoundTripDoDisco``, ``TestRoundTripDoMongo``,
  ``TestTiposDaSessao``): os mesmos dados e os mesmos tipos (``datetime`` UTC, ``set``, lista de log) voltam iguais;
* o que descrevia o formato antigo (pickle, protocolos, opcodes, ``voice_state``) saiu na etapa 5: o formato novo está em
  ``tests/test_f3_6b_etapa5_*.py`` e a migração do legado em ``test_f3_6b_etapa5_migracao_*.py``.
"""

import disnake
import pytest

from tests.support.formatos_reais import (
    INSTANTE,
    faixa_com_playlist,
    faixa_deezer,
    faixa_parcial,
    faixa_youtube,
    jogador_falso,
    letras_sincronizadas,
)


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def jogador_completo(**campos):
    """Jogador com uma faixa atual (com letras), fila (Deezer, parcial, de playlist), tocadas, autoplay e falhas."""
    return jogador_falso(
        atual=faixa_youtube(0, letras=letras_sincronizadas()),
        fila=[faixa_deezer(1), faixa_parcial(2), faixa_com_playlist(3)],
        tocadas=[faixa_youtube(4)],
        autoplay=[faixa_youtube(5)],
        falhas=[faixa_youtube(6)],
        **campos,
    )


async def gravar(cog, jogador) -> dict:
    """Roda o ``save_info`` real e devolve o ``data`` que ele montou (sem gravar em lugar nenhum)."""
    capturado = {}

    async def capturar(player, data):
        capturado.update(data)

    cog.save_session = capturar
    await cog.save_info(jogador)
    return capturado

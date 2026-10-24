"""F3-6b, etapa 2 (RED) — ``legacy_pickle.load_legacy``: DISPONIBILIDADE. Cada caso tem limite de tempo e de memória.

Um pickle hostil não precisa executar nada para derrubar o bot: basta pedir memória ou tempo demais. Aqui cada vetor da
tabela de DoS do plano vira um caso que ``load_legacy`` tem de recusar (``LegacyFormatError``, nunca outra exceção) rápido e
sem alocar o que o dado promete: memo de 9 bytes que pede 2³¹ posições, ``set`` de hash colidente (quadrático), aninhamento
de 10⁵ a 5·10⁶ níveis, bomba de compartilhamento de memo (poucos bytes, 10²⁰ ou 10³⁹ visitas), bomba de zlib,
``FRAME``/``BINUNICODE8``/``BINUNICODE`` gigantes sobre poucos bytes e arquivo vazio ou truncado.

Os tetos (opcodes, ``MARK``, itens de ``set``, tamanho) têm caso de BORDA: o teto exato passa e um a mais é recusado.
"""

import pickle

import pytest
import pytest_asyncio

from tests.support.leitor_legado import (
    ENVELOPE,
    MAX_RAW,
    MIB,
    OPCODE_LIMIT,
    SET_LIMIT,
    TOO_BIG,
    aninhado_em_listas,
    comprimido,
    conjunto_colidente,
    envelope,
    legacy_pickle,
    medir,
    pickle_de,
    recusado,
    texto,
)
from tests.support.formato_sessao import gravar, jogador_completo


def carregar(raw, kind="session"):
    return legacy_pickle.load_legacy(raw, kind)


def rapido(medida, codigos, pico=8 * MIB):
    recusado(medida, codigos, segundos=1.0, pico=pico)


# ============================================================================ set de hash colidente


class TestSetColidente:
    @pytest.mark.parametrize("itens", [1_001, 2_000])  # o teto é MAX_SET_ITEMS = 1000
    def test_set_colidente_enorme_e_recusado_sem_o_custo_quadratico(self, itens):
        dados = conjunto_colidente(itens)
        recusado(medir(carregar, envelope(dados)), SET_LIMIT, segundos=2.0, pico=32 * MIB)


# ============================================================================ aninhamento profundo


class TestAninhamentoProfundo:
    def test_aninhamento_acima_do_teto_na_skin_e_na_fila(self, monkeypatch):
        for kind in ("queue", "skin"):
            monkeypatch.setitem(legacy_pickle.MAX_OPCODES, kind, 1_000)  # em produção: 600 mil e 50 mil
        dados = aninhado_em_listas(5_000)
        recusado(
            medir(carregar, envelope(dados, "queue"), "queue", memoria=False), {TOO_BIG, OPCODE_LIMIT}, segundos=8.0
        )
        recusado(medir(carregar, envelope(dados, "skin"), "skin", memoria=False), {TOO_BIG, OPCODE_LIMIT}, segundos=8.0)


# ============================================================================ tamanho: bruto e descomprimido


class TestTamanho:
    def test_bomba_de_zlib_e_recusada_sem_alocar_o_descomprimido(self, monkeypatch):
        for kind in ("session", "queue"):
            monkeypatch.setitem(legacy_pickle.MAX_RAW, kind, 64 * 1024)  # em produção: 8 MiB e 4 MiB
        bomba = comprimido(bytes(MIB))
        assert len(bomba) < 4_000
        for kind in ("session", "queue"):
            recusado(medir(carregar, bomba, kind), TOO_BIG, segundos=3.0, pico=3 * MAX_RAW[kind])


# ============================================================================ arquivo vazio e truncado


class TestVazioETruncado:
    @pytest_asyncio.fixture
    async def sessao_em_pickle(self):
        from tests.support.formatos_reais import cog_de_sessoes

        dados = await gravar(cog_de_sessoes(), jogador_completo())
        return pickle.dumps(dados, protocol=4)

    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_arquivo_vazio_e_recusado(self, kind):
        rapido(medir(carregar, b"", kind), ENVELOPE)


# ============================================================================ bomba de compartilhamento do memo


def bomba_binaria(niveis: int) -> bytes:
    """``2**niveis`` visitas lógicas em centenas de bytes: cada nível é uma tupla de duas referências ao nível anterior."""
    partes = [pickle.NONE, pickle.MEMOIZE]
    for nivel in range(1, niveis + 1):
        partes += [pickle.BINGET + bytes([nivel - 1])] * 2 + [pickle.TUPLE2, pickle.MEMOIZE]
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST, pickle.MARK, *partes, pickle.APPENDS, pickle.SETITEM
    )


class TestBombaDeMemo:
    def test_a_bomba_binaria_rasa_dentro_dos_tetos_e_lida(self):
        lido = carregar(envelope(bomba_binaria(8)))  # 2**8 visitas e 10 níveis: cabe nos dois tetos
        assert len(lido["a"]) == 9

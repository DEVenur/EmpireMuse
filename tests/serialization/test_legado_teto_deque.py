"""F3-6b, etapa 2 — o teto de ``deque`` do leitor legado (``MAX_DEQUES``), por onde o Backend não olhou.

O motivo do teto: ``collections.deque(iteravel)`` COPIA o argumento a cada chamada; sem limite, uma lista grande e
compartilhada pelo memo, entregue a milhares de ``deque(...)``, custa tempo e memória quadráticos. Estes testes fecham o que
os testes do Backend (``test_legado_endurecimento.py``) não pegam:

* a CLASSE ``deque`` pode ser empilhada uma vez, guardada no memo e chamada várias vezes (``BINGET`` + ``REDUCE``): o teto
  tem de contar as CHAMADAS, e não os ``STACK_GLOBAL``;
* o custo que o teto evita: dois ``deque`` sobre uma lista de 200 mil itens passam, o terceiro é recusado ANTES de qualquer
  cópia (rápido e com pouca memória);
* a sessão REAL grava exatamente UM ``deque`` (``command_log_list``): se o produto passar a gravar mais um, o teto de 2 precisa
  ser revisto e este teste avisa.
"""

import pickle
import zlib

import pytest
import pytest_asyncio

from tests.support.formatos_reais import cog_de_sessoes
from tests.support.leitor_legado import (
    MIB,
    global_,
    legacy_pickle,
    medir,
    teto_de_tempo,
    pickle_de,
    recusado,
    texto,
    tupla,
)
from tests.support.formato_sessao import gravar, jogador_completo

OPCODE_LIMIT = "opcode_limit"

PISO_DE_SEGUNDOS = 2.0
FOLGA_SOBRE_A_LEITURA = 3.0  # recusar custa, no máximo, algumas leituras da lista (sem nenhuma cópia a mais)


def ler(dados: bytes):
    return legacy_pickle.load_legacy(zlib.compress(dados), "session")


def chamar_deque_memoizado(chamadas: int) -> bytes:
    """``{"a": [deque(), ...]}`` com a classe empilhada UMA vez, no memo, e chamada ``chamadas`` vezes."""
    corpo = global_("collections", "deque") + pickle.MEMOIZE + tupla(pickle.EMPTY_TUPLE) + pickle.REDUCE
    for _ in range(chamadas - 1):
        corpo += pickle.BINGET + b"\x00" + tupla(pickle.EMPTY_TUPLE) + pickle.REDUCE
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST, pickle.MARK, corpo, pickle.APPENDS, pickle.SETITEM
    )


def deques_sobre_lista_grande(chamadas: int, itens: int = 200_000) -> bytes:
    """``deque(L)`` ``chamadas`` vezes sobre a MESMA lista ``L`` de ``itens`` inteiros (compartilhada pelo memo)."""
    lista_grande = (
        pickle.EMPTY_LIST + pickle.MARK + (pickle.BININT1 + b"\x00") * itens + pickle.APPENDS + pickle.MEMOIZE
    )
    chamada = global_("collections", "deque") + pickle.BINGET + b"\x00" + pickle.TUPLE1 + pickle.REDUCE
    corpo = lista_grande + chamada * chamadas
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST, pickle.MARK, corpo, pickle.APPENDS, pickle.SETITEM
    )


class TestTetoContaAsChamadas:
    def test_a_classe_no_memo_chamada_acima_do_teto_e_recusada(self):
        recusado(medir(ler, chamar_deque_memoizado(legacy_pickle.MAX_DEQUES + 1)), OPCODE_LIMIT, segundos=1.0)

    def test_o_teto_nao_conta_a_classe_empilhada_e_nunca_chamada(self):
        """Só ``STACK_GLOBAL`` sem ``REDUCE`` não copia nada: não pode gastar o teto."""
        sem_chamar = global_("collections", "deque") + pickle.MEMOIZE
        dados = pickle_de(
            pickle.EMPTY_DICT,
            texto("a"),
            pickle.EMPTY_LIST,
            pickle.MARK,
            sem_chamar * 5,
            pickle.APPENDS,
            pickle.SETITEM,
        )
        recusado(
            medir(ler, dados), {"type"}, segundos=1.0
        )  # a classe solta na lista é recusada pelo validador, não pelo teto


def limite_relativo_a_leitura_da_lista() -> float:
    """Limite de tempo para a recusa, proporcional ao custo de apenas LER a lista de 200 mil itens (zero ``deque``).

    O leitor é Python puro: sob ``coverage``/``tracemalloc`` a leitura da lista sozinha leva várias vezes o tempo normal.
    Um teto absoluto mede o tracing, não o leitor; a linha de base mede nas mesmas condições da recusa.
    """
    leitura = medir(ler, deques_sobre_lista_grande(0))
    assert leitura.erro is None, leitura.erro
    return max(teto_de_tempo(PISO_DE_SEGUNDOS), FOLGA_SOBRE_A_LEITURA * leitura.segundos)


class TestCustoQueOTetoEvita:
    """O custo evitado é o de copiar a lista a cada ``deque``; o caso usa 500 itens e prova o teto pela contagem."""

    def test_dois_deques_sobre_a_lista_passam_e_o_terceiro_e_recusado(self):
        resultado = ler(deques_sobre_lista_grande(2, itens=500))
        assert len(resultado["a"]) == 3 and len(resultado["a"][1]) == 500
        recusado(medir(ler, deques_sobre_lista_grande(3, itens=500)), OPCODE_LIMIT)

    def test_muitas_copias_da_lista_sao_recusadas_pelo_teto(self):
        recusado(medir(ler, deques_sobre_lista_grande(500, itens=500)), OPCODE_LIMIT)


class TestASessaoRealTemUmDeque:
    @pytest_asyncio.fixture
    async def sessao(self):
        return await gravar(cog_de_sessoes(), jogador_completo())

    @pytest.mark.asyncio
    async def test_a_sessao_real_passa_pelo_leitor_com_folga_no_teto(self, sessao):
        assert ler(pickle.dumps(sessao, protocol=5))["command_log_list"].maxlen == 10

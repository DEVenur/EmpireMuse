"""F3-6b, etapa 1 (RED) — validação ESTRUTURAL iterativa: ``Any_JSON`` (campo livre) e ``check_structure`` (documento).

Dois tetos de profundidade (DE-4), ambos com caso de borda:

* ``Any_JSON(max_depth=8, max_nodes=5000)``: campo livre (``lyrics``, ``pluginInfo``, ``extra``); a profundidade conta A
  PARTIR DO VALOR DO CAMPO (``[[0]]`` tem 2 níveis), em qualquer ponto do documento. Só tipos do JSON (``None``, ``bool``,
  ``int``, ``float`` finito, ``str``, ``list``, ``dict`` de chaves ``str``); o erro aponta o CAMPO, nunca algo de dentro dele;
* ``check_structure(valor, *, max_depth=12, max_nodes=2_000_000)``: o validador genérico do documento legado inteiro; conta DA
  RAIZ e devolve o próprio ``valor``. Além do JSON aceita ``tuple``, ``set``, ``deque`` e ``datetime`` (o que o leitor
  legado entrega), e nada mais (``bytes``, ``frozenset``, subclasses, objetos quaisquer). O erro tem sempre ``path == ""``.

Nos dois: pilha explícita (sem ``RecursionError``), CONTAGEM DE VISITAS (uma referência compartilhada conta a cada vez que é
visitada) e nenhuma chamada a ``repr``, ``==``, ``hash``, ``len`` ou ``iter`` de objeto de fora dos tipos permitidos.
Nós = contêineres + escalares (chaves de dicionário não contam), como em ``tests/serialization/test_profundidade_campos_livres.py``.
"""

import time
import tracemalloc
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.support.serializacao_nucleo import (
    DEPTH,
    FIELD_DEPTH,
    KEY_NOT_TEXT,
    LIMITE_DE_TEMPO,
    NODES,
    NOT_FINITE,
    STRUCTURE_NODES,
    TYPE,
    aninhado,
    aninhado_em_dicionarios,
    bomba_de_compartilhamento,
    falha,
    schema,
)
from tests.serialization.test_profundidade_campos_livres import nos

pytestmark = pytest.mark.critical

UTC = timezone.utc


def livre(valor, **limites):
    return schema.validate(schema.Any_JSON(**limites), valor)


def estrutura(valor, **limites):
    return schema.check_structure(valor, **limites)


def cronometrar(funcao, *args, **kwargs):
    return funcao(*args, **kwargs)


def pico_de_memoria(funcao, *args, **kwargs) -> int:
    """Maior alocação (bytes) durante a chamada, que pode terminar em ``SchemaError``."""
    tracemalloc.start()
    try:
        try:
            funcao(*args, **kwargs)
        except schema.SchemaError:
            pass
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# ============================================================================ Any_JSON: o que passa


# ============================================================================ Any_JSON: bordas de profundidade e de nós


class TestAnyJsonLimites:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_8_niveis_passam_e_9_nao(self, construir):
        assert livre(construir(FIELD_DEPTH)) == construir(FIELD_DEPTH)
        erro = falha(livre, construir(FIELD_DEPTH + 1))
        assert erro.code == DEPTH and erro.path == ""

    def test_em_lista_de_dicionarios_a_contagem_tambem_parte_do_campo(self):
        esquema = schema.Dict({"queue": schema.List(schema.Dict({"extra": schema.Any_JSON()}), 5)})
        schema.validate(esquema, {"queue": [{"extra": aninhado(FIELD_DEPTH)}]})
        erro = falha(schema.validate, esquema, {"queue": [{"extra": 1}, {"extra": aninhado(FIELD_DEPTH + 1)}]})
        assert erro.code == DEPTH and erro.path == "queue[1].extra"

    def test_lista_gigante_e_recusada_pelo_tamanho_sem_alocar_uma_pilha_do_tamanho_dela(self):
        """Um contêiner com milhões de itens é recusado antes de empilhar os filhos (memória proporcional ao TETO)."""
        gigante = [0] * 5_000
        assert cronometrar(falha, livre, gigante, max_nodes=1000).code == NODES
        assert pico_de_memoria(livre, gigante, max_nodes=1000) < 4 * 1024 * 1024
        assert pico_de_memoria(livre, {str(i): 0 for i in range(5_000)}, max_nodes=1000) < 4 * 1024 * 1024


# ============================================================================ Any_JSON: hostil


class TestAnyJsonHostil:
    @pytest.mark.parametrize(
        "valor",
        [
            (1, 2),
            {1, 2},
            frozenset({1}),
            b"x",
            bytearray(b"x"),
            datetime(2026, 1, 1, tzinfo=UTC),
            object(),
            1j,
            Decimal(1),
        ]
        + [deque([1]), OrderedDict(a=1), defaultdict(int), range(2), timedelta(1)],
        ids=lambda v: type(v).__name__,
    )
    def test_so_tipos_do_json(self, valor):
        for embrulho in (lambda v: v, lambda v: [v], lambda v: {"a": v}, lambda v: {"a": [{"b": v}]}):
            assert falha(livre, embrulho(valor)).code == TYPE

    @pytest.mark.parametrize("valor", [float("nan"), float("-inf")], ids=["nan", "-inf"])
    def test_numero_nao_finito_e_recusado(self, valor):
        assert falha(livre, valor).code == NOT_FINITE
        assert falha(livre, {"a": [valor]}).code == NOT_FINITE

    def test_subclasse_de_str_com_metodos_espiados_nao_e_consultada(self):
        chamadas = []

        class Texto(str):
            def __len__(self):
                chamadas.append("len")
                return 1

            def __eq__(self, outro):
                chamadas.append("eq")
                return False

            __hash__ = str.__hash__

        chamadas.clear()
        assert falha(livre, ["a", Texto("b")]).code == TYPE
        assert chamadas == []


# ============================================================================ check_structure: o que passa


class TestCheckStructureAceita:
    def test_fila_salva_real_passa(self):
        conteudo = {
            "tracks": [{"title": "x", "extra": {"requester": 1}}] * 3,
            "created_at": datetime.now(UTC),
            "guild_id": 1,
        }
        assert estrutura(conteudo) is conteudo


# ============================================================================ check_structure: bordas


class TestCheckStructureLimites:
    def test_o_teto_de_nos_passa_no_limite_e_recusa_um_a_mais(self):
        """O teto em produção é STRUCTURE_NODES (2 milhões); o limite é reduzido pelo parâmetro ``max_nodes``."""
        teto = 1000
        assert estrutura([0] * (teto - 1), max_nodes=teto) is not None
        erro = falha(estrutura, [0] * teto, max_nodes=teto)
        assert erro.code == NODES and erro.path == ""

    def test_nos_de_set_deque_tuple_e_dicionario_contam_os_elementos_e_nao_as_chaves(self):
        assert estrutura({1, 2, 3}, max_nodes=4) is not None and falha(estrutura, {1, 2, 3}, max_nodes=3).code == NODES
        assert (
            estrutura(deque([1, 2]), max_nodes=3) is not None
            and falha(estrutura, deque([1, 2]), max_nodes=2).code == NODES
        )
        assert estrutura((1, 2), max_nodes=3) is not None and falha(estrutura, (1, 2), max_nodes=2).code == NODES
        assert estrutura({"a": 1, "b": 2}, max_nodes=3) is not None
        assert falha(estrutura, {"a": 1, "b": 2}, max_nodes=2).code == NODES


# ============================================================================ check_structure: hostil


class TestCheckStructureHostil:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_aninhamento_enorme_e_recusado_sem_recursionerror(self, construir):
        profundo = construir(5_000)
        assert cronometrar(falha, estrutura, profundo).code == DEPTH
        assert pico_de_memoria(estrutura, profundo) < 32 * 1024 * 1024

    @pytest.mark.parametrize(
        "valor",
        [
            b"x",
            int,
        ],
        ids=lambda v: type(v).__name__,
    )
    def test_so_os_tipos_do_legado(self, valor):
        for embrulho in (lambda v: v, lambda v: [v], lambda v: {"a": v}, lambda v: ({1, 2}, [v]), lambda v: deque([v])):
            assert falha(estrutura, embrulho(valor)).code == TYPE

    @pytest.mark.parametrize("valor", [float("nan"), float("-inf")], ids=["nan", "-inf"])
    def test_numero_nao_finito_e_recusado(self, valor):
        for embrulho in (lambda v: v, lambda v: [v], lambda v: {"a": (v,)}, lambda v: {v}):
            assert falha(estrutura, embrulho(valor)).code == NOT_FINITE

    def test_subclasse_de_str_espiada_nao_e_consultada(self):
        chamadas = []

        class Texto(str):
            def __len__(self):
                chamadas.append("len")
                return 1

            def __eq__(self, outro):
                chamadas.append("eq")
                return False

            __hash__ = str.__hash__

        chamadas.clear()
        assert falha(estrutura, [Texto("x")]).code == TYPE
        assert falha(estrutura, [{Texto("x"): 1}]).code == KEY_NOT_TEXT
        assert chamadas == []

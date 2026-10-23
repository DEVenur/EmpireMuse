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

from tests.support.formatos_reais import (
    cog_de_sessoes,
    faixa_youtube,
    letras_com_plugin_por_linha,
    letras_em_texto,
    letras_sincronizadas,
    plugin_info_de_faixa,
    plugin_info_de_playlist,
    profundidade,
)
from tests.support.serializacao_nucleo import (
    DEPTH,
    FIELD_DEPTH,
    FIELD_NODES,
    KEY_NOT_TEXT,
    LIMITE_DE_TEMPO,
    NODES,
    NOT_FINITE,
    PAR_DE_SURROGATES,
    STRUCTURE_DEPTH,
    STRUCTURE_NODES,
    SURROGATE,
    TYPE,
    aninhado,
    aninhado_em_dicionarios,
    bomba_de_compartilhamento,
    falha,
    schema,
)
from tests.persistence.test_formato_sessao import gravar, jogador_completo
from tests.serialization.test_profundidade_campos_livres import letras_palavra_a_palavra, nos

UTC = timezone.utc


def livre(valor, **limites):
    return schema.validate(schema.Any_JSON(**limites), valor)


def estrutura(valor, **limites):
    return schema.check_structure(valor, **limites)


def cronometrar(funcao, *args, **kwargs):
    inicio = time.perf_counter()
    try:
        return funcao(*args, **kwargs)
    finally:
        assert time.perf_counter() - inicio < LIMITE_DE_TEMPO, "caso hostil lento demais"


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


class TestOsCasosDeTesteMedemOQueDizem:
    """Os construtores de casos usam a mesma contagem que o resto da etapa (independe da implementação)."""

    @pytest.mark.parametrize("niveis", [1, 8, 9, 12, 13])
    def test_profundidade_dos_aninhados(self, niveis):
        assert profundidade(aninhado(niveis)) == niveis == profundidade(aninhado_em_dicionarios(niveis))

    def test_nos_do_compartilhamento(self):
        assert nos([[0]] * 3) == 1 + 3 * 2
        assert nos(bomba_de_compartilhamento(3, 10)) == 1 + 10 * (1 + 10 * 2)


def test_os_limites_padrao_sao_os_do_de4():
    assert (schema.FIELD_MAX_DEPTH, schema.FIELD_MAX_NODES) == (FIELD_DEPTH, FIELD_NODES) == (8, 5000)
    assert (
        (schema.STRUCTURE_MAX_DEPTH, schema.STRUCTURE_MAX_NODES)
        == (STRUCTURE_DEPTH, STRUCTURE_NODES)
        == (12, 2_000_000)
    )


# ============================================================================ Any_JSON: o que passa


class TestAnyJsonAceita:
    @pytest.mark.parametrize("valor", [None, True, False, 0, -7, 2**70, 1.5, -0.0, "", "texto", [], {}], ids=repr)
    def test_escalares_e_contêineres_vazios(self, valor):
        assert livre(valor) == valor

    def test_as_formas_reais_de_letras_e_plugin_info_passam_com_os_limites_padrao(self):
        for valor in (
            letras_sincronizadas(),
            letras_sincronizadas(300),
            letras_em_texto(),
            letras_com_plugin_por_linha(),
            letras_palavra_a_palavra(),
            plugin_info_de_faixa(),
            plugin_info_de_playlist(),
        ):
            assert livre(valor) == valor

    def test_texto_livre_pode_ter_quebra_de_linha_e_formatacao(self):
        """Letras têm ``\\n`` e emojis com ZWJ: o campo livre só recusa surrogate, não ``Cc``/``Cf`` (isso é do ``Str``)."""
        valor = {"text": "linha 1\nlinha 2\t\u200d👨\u200d👩\u200d👧\u202e"}
        assert livre(valor) == valor

    def test_devolve_copia_independente_da_entrada(self):
        entrada = {"a": [1, {"b": [2]}], "c": {"d": "x"}}
        saida = livre(entrada)
        assert saida == entrada and saida is not entrada
        assert (
            saida["a"] is not entrada["a"] and saida["a"][1] is not entrada["a"][1] and saida["c"] is not entrada["c"]
        )
        entrada["a"][1]["b"].append(99)
        assert saida["a"][1]["b"] == [2]

    def test_o_extra_de_uma_faixa_real_passa(self):
        extra = faixa_youtube(0, letras=letras_sincronizadas()).info["extra"]
        assert livre(extra) == extra


# ============================================================================ Any_JSON: bordas de profundidade e de nós


class TestAnyJsonLimites:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_8_niveis_passam_e_9_nao(self, construir):
        assert livre(construir(FIELD_DEPTH)) == construir(FIELD_DEPTH)
        erro = falha(livre, construir(FIELD_DEPTH + 1))
        assert erro.code == DEPTH and erro.path == ""

    def test_a_profundidade_mista_conta_todos_os_contêineres(self):
        valor = {"a": [{"b": [{"c": [{"d": [0]}]}]}]}  # 8 níveis
        assert profundidade(valor) == 8 and livre(valor) == valor
        assert falha(livre, {"z": valor}).code == DEPTH

    def test_a_contagem_parte_do_valor_do_campo_e_nao_da_raiz_do_documento(self):
        esquema = schema.Dict({"a": schema.Dict({"b": schema.Any_JSON()})})
        assert schema.validate(esquema, {"a": {"b": aninhado(FIELD_DEPTH)}})["a"]["b"] == aninhado(FIELD_DEPTH)
        erro = falha(schema.validate, esquema, {"a": {"b": aninhado(FIELD_DEPTH + 1)}})
        assert erro.code == DEPTH and erro.path == "a.b"

    def test_em_lista_de_dicionarios_a_contagem_tambem_parte_do_campo(self):
        esquema = schema.Dict({"queue": schema.List(schema.Dict({"extra": schema.Any_JSON()}), 5)})
        schema.validate(esquema, {"queue": [{"extra": aninhado(FIELD_DEPTH)}]})
        erro = falha(schema.validate, esquema, {"queue": [{"extra": 1}, {"extra": aninhado(FIELD_DEPTH + 1)}]})
        assert erro.code == DEPTH and erro.path == "queue[1].extra"

    def test_limites_informados_valem(self):
        assert livre([[1]], max_depth=2) == [[1]]
        assert falha(livre, [[[1]]], max_depth=2).code == DEPTH
        assert livre([0] * 9, max_nodes=10) == [0] * 9
        assert falha(livre, [0] * 10, max_nodes=10).code == NODES

    def test_5000_nos_passam_e_5001_nao(self):
        assert nos([0] * 4999) == FIELD_NODES
        assert livre([0] * 4999) == [0] * 4999
        erro = falha(livre, [0] * 5000)
        assert erro.code == NODES and erro.path == ""

    def test_nos_de_dicionario_nao_contam_as_chaves(self):
        passa = {str(i): 0 for i in range(4999)}
        assert nos(passa) == FIELD_NODES and livre(passa) == passa
        assert falha(livre, {str(i): 0 for i in range(5000)}).code == NODES

    def test_nos_de_estrutura_mista(self):
        passa = [[0, 0]] * 1666  # 1 + 1666 * 3 = 4999 visitas (a mesma lista de dentro vale a cada visita)
        assert nos(passa) == 4999 and len(livre(passa)) == 1666
        assert falha(livre, [[0, 0]] * 1667).code == NODES

    def test_visita_conta_a_cada_referencia_e_nao_por_objeto_unico(self):
        compartilhado = [0, 0]
        assert livre([compartilhado] * 3, max_nodes=10) == [[0, 0]] * 3  # 1 + 3 * 3 = 10
        assert falha(livre, [compartilhado] * 3, max_nodes=9).code == NODES

    def test_o_teto_de_nos_do_campo_e_por_campo_e_nao_do_documento(self):
        esquema = schema.Dict({"a": schema.Any_JSON(), "b": schema.Any_JSON()})
        valor = {"a": [0] * 4999, "b": [0] * 4999}
        assert schema.validate(esquema, valor) == valor

    def test_lista_gigante_e_recusada_pelo_tamanho_sem_alocar_uma_pilha_do_tamanho_dela(self):
        """Um contêiner com milhões de itens é recusado antes de empilhar os filhos (memória proporcional ao TETO)."""
        gigante = [0] * 3_000_000
        assert cronometrar(falha, livre, gigante, max_nodes=1000).code == NODES
        assert pico_de_memoria(livre, gigante, max_nodes=1000) < 4 * 1024 * 1024
        assert pico_de_memoria(livre, {str(i): 0 for i in range(100_000)}, max_nodes=1000) < 4 * 1024 * 1024

    def test_bomba_de_compartilhamento_e_recusada_no_teto_de_nos_sem_expandir(self):
        bomba = bomba_de_compartilhamento(niveis=FIELD_DEPTH, largura=20)  # 20**7 visitas lógicas, 8 níveis
        assert profundidade(bomba_de_compartilhamento(FIELD_DEPTH, 1)) == FIELD_DEPTH  # a bomba em si não se mede
        erro = cronometrar(falha, livre, bomba)
        assert erro.code == NODES
        assert pico_de_memoria(livre, bomba) < 32 * 1024 * 1024


# ============================================================================ Any_JSON: hostil


class TestAnyJsonHostil:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_aninhamento_enorme_e_recusado_sem_recursionerror(self, construir):
        profundo = construir(300_000)
        erro = cronometrar(falha, livre, profundo)
        assert erro.code == DEPTH
        assert pico_de_memoria(livre, profundo) < 32 * 1024 * 1024

    def test_estrutura_circular_e_recusada(self):
        lista = []
        lista.append(lista)
        dicionario = {}
        dicionario["a"] = dicionario
        assert cronometrar(falha, livre, lista).code in {DEPTH, NODES}
        assert cronometrar(falha, livre, dicionario).code in {DEPTH, NODES}

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

    def test_subclasses_dos_tipos_do_json_sao_recusadas(self):
        class Texto(str):
            pass

        class Numero(int):
            pass

        class Lista(list):
            pass

        class Mapa(dict):
            pass

        for valor in (Texto("a"), Numero(1), Lista(), Mapa(), Numero(True)):
            assert falha(livre, valor).code == TYPE

    @pytest.mark.parametrize("chave", [1, b"a", None, ("a",), 1.5, True], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_e_recusada_em_qualquer_nivel(self, chave):
        assert falha(livre, {chave: 1}).code == KEY_NOT_TEXT
        assert falha(livre, {"a": [{chave: 1}]}).code == KEY_NOT_TEXT

    @pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_numero_nao_finito_e_recusado(self, valor):
        assert falha(livre, valor).code == NOT_FINITE
        assert falha(livre, {"a": [valor]}).code == NOT_FINITE

    @pytest.mark.parametrize("texto", ["a\ud800", "\udfff", PAR_DE_SURROGATES], ids=["alto", "baixo", "par-solto"])
    def test_surrogate_solto_e_recusado_no_valor_e_na_chave(self, texto):
        assert falha(livre, texto).code == SURROGATE
        assert falha(livre, {"a": [texto]}).code == SURROGATE
        assert falha(livre, {texto: 1}).code == SURROGATE

    def test_o_erro_de_dentro_do_campo_aponta_so_o_campo(self):
        esquema = schema.Dict({"extra": schema.Any_JSON()})
        for dado in (
            {"extra": {"x": [b"y"]}},
            {"extra": {"x": float("nan")}},
            {"extra": {1: 2}},
            {"extra": aninhado(20)},
        ):
            assert falha(schema.validate, esquema, dado).path == "extra"

    def test_objeto_de_fora_dos_tipos_nao_tem_metodo_magico_chamado(self):
        chamadas = []

        class Espiao:
            def __getattribute__(self, nome):
                chamadas.append(nome)
                return object.__getattribute__(self, nome)

            def __eq__(self, outro):
                chamadas.append("eq")
                return False

            def __hash__(self):
                chamadas.append("hash")
                return 1

            def __repr__(self):
                chamadas.append("repr")
                return "x"

            def __len__(self):
                chamadas.append("len")
                return 1

            def __iter__(self):
                chamadas.append("iter")
                return iter(())

            def __bool__(self):
                chamadas.append("bool")
                return True

        espiao = Espiao()
        chamadas.clear()
        assert falha(livre, [1, {"a": espiao}]).code == TYPE
        assert chamadas == []

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
    def test_devolve_o_proprio_valor(self):
        valor = {"a": [1, 2]}
        assert estrutura(valor) is valor

    @pytest.mark.parametrize(
        "valor",
        [
            None,
            True,
            3,
            2**70,
            1.5,
            "texto",
            "com\ncontrole\u202e e \u200b",
            [],
            (),
            {},
            set(),
            deque(),
            {1, 2, 3},
            (1, (2, 3)),
            deque([1, 2], maxlen=10),
            datetime(2026, 10, 19, 14, 3, 22, 123456, tzinfo=UTC),
            datetime(2026, 10, 19),
        ],
        ids=repr,
    )
    def test_tipos_permitidos(self, valor):
        assert estrutura(valor) is valor

    def test_misto_de_tipos_dentro_do_teto(self):
        valor = {"dj": {1, 2}, "log": deque([{"text": "a", "timestamp": 1.5}], maxlen=10), "t": (1, "x"), "n": None}
        assert estrutura(valor) is valor

    @pytest.mark.asyncio
    async def test_a_sessao_real_com_datetime_set_e_deque_passa_com_os_limites_padrao(self):
        sessao = await gravar_sessao_real()
        assert profundidade(sessao) == 8
        assert estrutura(sessao) is sessao

    @pytest.mark.asyncio
    async def test_o_pior_caso_plausivel_de_letras_chega_a_10_e_passa(self):
        sessao = await gravar_sessao_real()
        pior = dict(sessao, queue=[{"extra": {"lyrics": letras_palavra_a_palavra()}}])
        assert profundidade(pior) == 10
        assert estrutura(pior) is pior

    def test_fila_salva_real_passa(self):
        conteudo = {
            "tracks": [{"title": "x", "extra": {"requester": 1}}] * 3,
            "created_at": datetime.now(UTC),
            "guild_id": 1,
        }
        assert estrutura(conteudo) is conteudo


async def gravar_sessao_real():
    return await gravar(cog_de_sessoes(), jogador_completo())


# ============================================================================ check_structure: bordas


class TestCheckStructureLimites:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_12_niveis_passam_e_13_nao_contados_da_raiz(self, construir):
        assert estrutura(construir(STRUCTURE_DEPTH)) is not None
        erro = falha(estrutura, construir(STRUCTURE_DEPTH + 1))
        assert erro.code == DEPTH and erro.path == ""

    def test_a_profundidade_mista_com_tuple_set_e_deque_conta_todos(self):
        valor = [(deque([{"a": [(0,)]}]),)]
        assert profundidade(valor) == 6
        fundo = valor
        for _ in range(STRUCTURE_DEPTH - 6):
            fundo = [fundo]
        assert estrutura(fundo) is fundo
        assert falha(estrutura, [fundo]).code == DEPTH

    def test_limite_de_profundidade_informado_vale(self):
        assert estrutura(aninhado(3), max_depth=3) is not None
        assert falha(estrutura, aninhado(4), max_depth=3).code == DEPTH

    def test_dois_milhoes_menos_um_passam_e_dois_milhoes_nao(self):
        assert estrutura([0] * (STRUCTURE_NODES - 1)) is not None
        erro = cronometrar(falha, estrutura, [0] * STRUCTURE_NODES)
        assert erro.code == NODES and erro.path == ""

    def test_lista_gigante_e_recusada_pelo_tamanho_sem_alocar_uma_pilha_do_tamanho_dela(self):
        gigante = [0] * 3_000_000
        for conteiner in (gigante, tuple(gigante), set(range(1_000_000)), deque(gigante)):
            assert cronometrar(falha, estrutura, conteiner, max_nodes=1000).code == NODES
            assert pico_de_memoria(estrutura, conteiner, max_nodes=1000) < 4 * 1024 * 1024

    def test_limite_de_nos_informado_vale(self):
        assert estrutura([0] * 99, max_nodes=100) is not None
        assert falha(estrutura, [0] * 100, max_nodes=100).code == NODES

    def test_nos_de_set_deque_tuple_e_dicionario_contam_os_elementos_e_nao_as_chaves(self):
        assert estrutura({1, 2, 3}, max_nodes=4) is not None and falha(estrutura, {1, 2, 3}, max_nodes=3).code == NODES
        assert (
            estrutura(deque([1, 2]), max_nodes=3) is not None
            and falha(estrutura, deque([1, 2]), max_nodes=2).code == NODES
        )
        assert estrutura((1, 2), max_nodes=3) is not None and falha(estrutura, (1, 2), max_nodes=2).code == NODES
        assert estrutura({"a": 1, "b": 2}, max_nodes=3) is not None
        assert falha(estrutura, {"a": 1, "b": 2}, max_nodes=2).code == NODES

    def test_visita_conta_a_cada_referencia_e_nao_por_objeto_unico(self):
        compartilhado = [0]
        assert estrutura([compartilhado] * 3, max_nodes=7) is not None  # 1 + 3 * 2
        assert falha(estrutura, [compartilhado] * 3, max_nodes=6).code == NODES

    def test_bomba_de_compartilhamento_e_recusada_no_teto_de_nos(self):
        bomba = bomba_de_compartilhamento(niveis=STRUCTURE_DEPTH, largura=50)  # 50**11 visitas, 12 níveis
        assert profundidade(bomba_de_compartilhamento(STRUCTURE_DEPTH, 1)) == STRUCTURE_DEPTH
        erro = cronometrar(falha, estrutura, bomba)
        assert erro.code == NODES
        assert pico_de_memoria(estrutura, bomba, max_nodes=100_000) < 32 * 1024 * 1024

    def test_bomba_com_dicionario_compartilhado(self):
        folha = {"a": [0] * 1000}
        valor = [folha] * 1000
        for _ in range(3):
            valor = [valor] * 1000
        assert cronometrar(falha, estrutura, valor).code == NODES


# ============================================================================ check_structure: hostil


class TestCheckStructureHostil:
    @pytest.mark.parametrize("construir", [aninhado, aninhado_em_dicionarios], ids=["listas", "dicionarios"])
    def test_aninhamento_enorme_e_recusado_sem_recursionerror(self, construir):
        profundo = construir(500_000)
        assert cronometrar(falha, estrutura, profundo).code == DEPTH
        assert pico_de_memoria(estrutura, profundo) < 32 * 1024 * 1024

    def test_aninhamento_enorme_misturando_tipos(self):
        encaixar = [lambda v: [v], lambda v: (v,), lambda v: {"a": v}, lambda v: deque([v])]
        valor = 0
        for indice in range(300_000):
            valor = encaixar[indice % 4](valor)
        assert cronometrar(falha, estrutura, valor).code == DEPTH

    def test_estruturas_circulares_sao_recusadas(self):
        lista = []
        lista.append(lista)
        dicionario = {}
        dicionario["a"] = dicionario
        fila = deque()
        fila.append(fila)
        for circular in (lista, dicionario, fila):
            assert cronometrar(falha, estrutura, circular).code in {DEPTH, NODES}

    @pytest.mark.parametrize(
        "valor",
        [
            b"x",
            bytearray(b"x"),
            memoryview(b"x"),
            frozenset({1}),
            OrderedDict(a=1),
            defaultdict(int),
            object(),
            1j,
            Decimal(1),
            timedelta(1),
            UTC,
            range(2),
            int,
        ],
        ids=lambda v: type(v).__name__,
    )
    def test_so_os_tipos_do_legado(self, valor):
        for embrulho in (lambda v: v, lambda v: [v], lambda v: {"a": v}, lambda v: ({1, 2}, [v]), lambda v: deque([v])):
            assert falha(estrutura, embrulho(valor)).code == TYPE

    def test_subclasses_sao_recusadas(self):
        class Texto(str):
            pass

        class Numero(int):
            pass

        class Lista(list):
            pass

        class Mapa(dict):
            pass

        class Conjunto(set):
            pass

        class Fila(deque):
            pass

        class Tupla(tuple):
            pass

        class Data(datetime):
            pass

        for valor in (Texto("a"), Numero(1), Lista(), Mapa(), Conjunto(), Fila(), Tupla(), Data(2026, 1, 1)):
            assert falha(estrutura, valor).code == TYPE

    @pytest.mark.parametrize(
        "chave", [1, b"a", None, ("a",), 1.5, True, frozenset({1})], ids=lambda v: type(v).__name__
    )
    def test_chave_que_nao_e_texto_e_recusada_em_qualquer_nivel(self, chave):
        assert falha(estrutura, {chave: 1}).code == KEY_NOT_TEXT
        assert falha(estrutura, [{"a": ({chave: 1},)}]).code == KEY_NOT_TEXT

    @pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_numero_nao_finito_e_recusado(self, valor):
        for embrulho in (lambda v: v, lambda v: [v], lambda v: {"a": (v,)}, lambda v: {v}):
            assert falha(estrutura, embrulho(valor)).code == NOT_FINITE

    @pytest.mark.parametrize("texto", ["a\ud800", "\udfff", PAR_DE_SURROGATES], ids=["alto", "baixo", "par-solto"])
    def test_surrogate_solto_e_recusado_no_valor_na_chave_e_dentro_de_set(self, texto):
        assert falha(estrutura, texto).code == SURROGATE
        assert falha(estrutura, [{"a": texto}]).code == SURROGATE
        assert falha(estrutura, {texto: 1}).code == SURROGATE
        assert falha(estrutura, {texto}).code == SURROGATE

    def test_o_erro_nao_aponta_caminho_algum(self):
        for valor in (aninhado(20), {"a": [b"x"]}, {"a": {1: 2}}, [float("nan")], [[["\ud800"]]]):
            assert falha(estrutura, valor).path == ""

    def test_nenhum_metodo_magico_de_objeto_de_fora_e_chamado(self):
        chamadas = []

        class Espiao:
            def __getattribute__(self, nome):
                chamadas.append(nome)
                return object.__getattribute__(self, nome)

            def __eq__(self, outro):
                chamadas.append("eq")
                return False

            def __hash__(self):
                chamadas.append("hash")
                return 1

            def __repr__(self):
                chamadas.append("repr")
                return "x"

            def __len__(self):
                chamadas.append("len")
                return 1

            def __iter__(self):
                chamadas.append("iter")
                return iter(())

        espiao = Espiao()
        chave_espia = Espiao()
        estrutura_ruim = {"a": [espiao]}
        estrutura_com_chave_ruim = [{chave_espia: 1}]
        chamadas.clear()
        assert falha(estrutura, estrutura_ruim).code == TYPE
        assert falha(estrutura, estrutura_com_chave_ruim).code == KEY_NOT_TEXT
        assert chamadas == []

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

    def test_o_valor_recusado_nao_e_alterado(self):
        valor = {"a": [1, 2, {3, 4}], "b": b"x"}
        antes = repr(valor)
        falha(estrutura, valor)
        assert repr(valor) == antes

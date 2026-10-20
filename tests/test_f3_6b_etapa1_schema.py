"""F3-6b, etapa 1 (RED) — ``empiremuse/serialization/schema.py``: os tipos do esquema e o ``SchemaError``.

API fixada por estes testes (as decisões em aberto estão em ``tests/helpers_f3_6b_serializacao.py``):

* ``validate(esquema, valor)`` devolve o dado LIMPO (estrutura nova, a entrada não é alterada) ou levanta
  ``SchemaError(path, code)``; ``path`` é texto (``""`` na raiz, ``campo``, ``lista[2]``, ``a[1].b``) e nunca leva o valor;
* ``Str(max_len, *, min_len=0, pattern=None, multiline=False)``: só ``str`` exato, sem surrogate solto nem ``Cc``/``Cf``
  (``multiline=True`` libera só ``\\n``, ``\\r`` e ``\\t``), ``pattern`` por ``fullmatch``;
* ``Int(min=None, max=None)``: só ``int`` exato (``bool`` NÃO vale), limites inclusivos; ``SNOWFLAKE`` = ``Int(0, 2**63-1)``;
* ``Float(min=None, max=None)``: ``int`` ou ``float`` finito (``bool`` não), devolve ``float``;
* ``Bool()``; ``List(item, max_items, min_items=0)``;
* ``Dict(fields, extra="drop")`` com ``extra`` em ``"drop"`` (descarta e avisa, sem nomes), ``"keep"`` (guarda, validado como
  ``Any_JSON``) ou ``"error"``; ``Optional(inner, default=None)``: o campo pode faltar (vira ``default``) ou ser ``None``.

Os limites e a ``Any_JSON`` ficam em ``test_f3_6b_etapa1_estrutura.py``; o ``codec`` em ``test_f3_6b_etapa1_codec.py``.
"""

import copy
import logging
from collections import OrderedDict

import pytest

from tests.helpers_f3_6b_serializacao import (
    CONTROL,
    DEPTH,
    KEY_NOT_TEXT,
    LENGTH,
    LOGGER,
    MISSING,
    NOT_FINITE,
    PAR_DE_SURROGATES,
    PATTERN,
    RANGE,
    SEGREDO,
    SNOWFLAKE_MAX,
    SURROGATE,
    TYPE,
    UNKNOWN_FIELD,
    aninhado,
    falha,
    schema,
    vazamentos,
)


def validar(esquema, valor):
    return schema.validate(esquema, valor)


# ============================================================================ SchemaError


class TestSchemaError:
    def test_guarda_caminho_e_codigo_na_ordem_do_plano(self):
        erro = schema.SchemaError("queue[3].uri", "length")
        assert erro.path == "queue[3].uri" and erro.code == "length"

    def test_e_um_valueerror_para_quem_so_captura_isso(self):
        assert issubclass(schema.SchemaError, ValueError)

    def test_a_mensagem_diz_o_codigo_e_o_caminho(self):
        texto = str(schema.SchemaError("queue[3].uri", "length"))
        assert "length" in texto and "queue[3].uri" in texto

    def test_a_raiz_tem_caminho_vazio(self):
        assert falha(validar, schema.Bool(), 1).path == ""


# ============================================================================ Str


class TestStr:
    def test_texto_comum_passa_e_volta_igual(self):
        for texto in ("", "Música 1", "日本語", "😀 emoji", "a b-c_d", "com" + chr(0x2028) + "separador"):
            assert validar(schema.Str(50), texto) == texto

    def test_tamanho_maximo_e_inclusivo_e_conta_caracteres(self):
        assert validar(schema.Str(5), "abcde") == "abcde"
        assert falha(validar, schema.Str(5), "abcdef").code == LENGTH
        assert validar(schema.Str(3), "😀😀😀") == "😀😀😀"  # 3 caracteres, não 12 bytes
        assert falha(validar, schema.Str(3), "😀😀😀😀").code == LENGTH

    def test_tamanho_minimo(self):
        assert validar(schema.Str(10, min_len=2), "ab") == "ab"
        assert falha(validar, schema.Str(10, min_len=2), "a").code == LENGTH
        assert validar(schema.Str(10), "") == ""

    @pytest.mark.parametrize(
        "valor",
        [1, 1.5, None, True, b"texto", bytearray(b"x"), ["a"], {"a": 1}, ("a",)],
        ids=lambda v: type(v).__name__,
    )
    def test_so_str_vale(self, valor):
        assert falha(validar, schema.Str(10), valor).code == TYPE

    def test_subclasse_de_str_e_recusada(self):
        class Texto(str):
            pass

        assert falha(validar, schema.Str(10), Texto("abc")).code == TYPE

    @pytest.mark.parametrize("texto", ["a\ud800b", "\udfff", PAR_DE_SURROGATES], ids=["alto", "baixo", "par-solto"])
    def test_surrogate_solto_e_recusado(self, texto):
        """Em ``str`` do Python um par de surrogates continua sendo dois surrogates soltos."""
        assert falha(validar, schema.Str(50), texto).code == SURROGATE

    @pytest.mark.parametrize(
        "texto",
        [
            "a\x00b",
            "a\x1bb",
            "a\x7fb",
            "a\x85b",
            "a\u202eb",
            "a\u200bb",
            "a\u200db",
            "a\ufeffb",
            "a\u2066b",
            "a\u00adb",
        ],
        ids=["nul", "esc", "del", "nel", "bidi-rlo", "zwsp", "zwj", "bom", "bidi-lri", "hifen-suave"],
    )
    def test_controle_e_formatacao_sao_recusados(self, texto):
        assert falha(validar, schema.Str(50), texto).code == CONTROL

    @pytest.mark.parametrize("texto", ["a\nb", "a\rb", "a\tb"], ids=["lf", "cr", "tab"])
    def test_quebra_de_linha_e_tab_so_com_multiline(self, texto):
        assert falha(validar, schema.Str(50), texto).code == CONTROL
        assert validar(schema.Str(50, multiline=True), texto) == texto

    @pytest.mark.parametrize("texto", ["a\x00b", "a\u202eb", "a\u200bb", "a\x1bb", "a\x85b"], ids=str)
    def test_multiline_nao_libera_os_outros_controles(self, texto):
        assert falha(validar, schema.Str(50, multiline=True), texto).code == CONTROL

    def test_multiline_continua_recusando_surrogate(self):
        assert falha(validar, schema.Str(50, multiline=True), "a\ud800\nb").code == SURROGATE

    def test_padrao_vale_para_o_texto_inteiro(self):
        esquema = schema.Str(20, pattern=r"[0-9]{1,20}")
        assert validar(esquema, "12345") == "12345"
        assert falha(validar, esquema, "123a").code == PATTERN
        assert falha(validar, esquema, "a123").code == PATTERN
        assert falha(validar, esquema, "").code in {PATTERN, LENGTH}

    def test_padrao_com_ancoras_nao_aceita_quebra_de_linha_no_fim(self):
        """O ``$`` do ``re`` casa antes de um ``\\n`` final; o nome de arquivo ``^[0-9]{1,20}$`` não pode passar assim."""
        esquema = schema.Str(40, pattern=r"^[0-9]{1,20}$", multiline=True)
        assert validar(esquema, "123") == "123"
        assert falha(validar, esquema, "123\n").code == PATTERN

    def test_padrao_nao_aceita_digitos_de_outros_alfabetos(self):
        esquema = schema.Str(20, pattern=r"[0-9]{1,20}")
        assert falha(validar, esquema, "١٢٣").code == PATTERN
        assert falha(validar, esquema, "１２３").code == PATTERN

    def test_o_valor_devolvido_e_o_proprio_texto(self):
        texto = "Música"
        assert validar(schema.Str(10), texto) == texto


# ============================================================================ Int, Float, Bool


class TestInt:
    def test_sem_limites_aceita_qualquer_inteiro(self):
        for numero in (0, -1, 7, 2**200, -(2**200)):
            assert validar(schema.Int(), numero) == numero

    def test_limites_sao_inclusivos(self):
        esquema = schema.Int(1, 10)
        assert validar(esquema, 1) == 1 and validar(esquema, 10) == 10
        assert falha(validar, esquema, 0).code == RANGE and falha(validar, esquema, 11).code == RANGE

    def test_so_limite_inferior_ou_so_superior(self):
        assert falha(validar, schema.Int(min=0), -1).code == RANGE and validar(schema.Int(min=0), 10**30) == 10**30
        assert falha(validar, schema.Int(max=0), 1).code == RANGE and validar(schema.Int(max=0), -(10**30)) == -(10**30)

    @pytest.mark.parametrize("valor", [True, False], ids=["true", "false"])
    def test_bool_nao_vale_como_inteiro(self, valor):
        assert falha(validar, schema.Int(0, 10), valor).code == TYPE
        assert falha(validar, schema.Int(), valor).code == TYPE

    @pytest.mark.parametrize("valor", [1.0, 1.5, "1", None, b"1", [1], float("nan"), float("inf")], ids=repr)
    def test_so_int_vale(self, valor):
        assert falha(validar, schema.Int(), valor).code == TYPE

    def test_subclasse_de_int_e_recusada(self):
        class Numero(int):
            pass

        assert falha(validar, schema.Int(), Numero(3)).code == TYPE

    def test_snowflake_vai_de_zero_ate_2_elevado_a_63_menos_1(self):
        assert validar(schema.SNOWFLAKE, 0) == 0
        assert validar(schema.SNOWFLAKE, SNOWFLAKE_MAX) == SNOWFLAKE_MAX
        assert validar(schema.SNOWFLAKE, 1100000000000000001) == 1100000000000000001
        assert falha(validar, schema.SNOWFLAKE, -1).code == RANGE
        assert falha(validar, schema.SNOWFLAKE, SNOWFLAKE_MAX + 1).code == RANGE
        assert falha(validar, schema.SNOWFLAKE, 10**40).code == RANGE
        assert falha(validar, schema.SNOWFLAKE, True).code == TYPE
        assert falha(validar, schema.SNOWFLAKE, "123").code == TYPE
        assert falha(validar, schema.SNOWFLAKE, 1.0).code == TYPE


class TestFloat:
    def test_aceita_float_e_int_e_devolve_float(self):
        assert validar(schema.Float(), 2.5) == 2.5
        resultado = validar(schema.Float(), 3)
        assert resultado == 3.0 and type(resultado) is float

    @pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_nao_finito_e_recusado(self, valor):
        assert falha(validar, schema.Float(), valor).code == NOT_FINITE

    def test_inteiro_gigante_que_estoura_o_float_e_recusado_sem_overflowerror(self):
        assert falha(validar, schema.Float(), 10**400).code in {RANGE, NOT_FINITE}

    @pytest.mark.parametrize("valor", [True, False, "1.5", None, b"1", [1.5]], ids=repr)
    def test_bool_e_outros_tipos_sao_recusados(self, valor):
        assert falha(validar, schema.Float(), valor).code == TYPE

    def test_limites_inclusivos(self):
        esquema = schema.Float(0, 100)
        assert validar(esquema, 0) == 0.0 and validar(esquema, 100.0) == 100.0
        assert falha(validar, esquema, -0.001).code == RANGE and falha(validar, esquema, 100.001).code == RANGE


class TestBool:
    @pytest.mark.parametrize("valor", [True, False], ids=["true", "false"])
    def test_aceita_so_bool(self, valor):
        assert validar(schema.Bool(), valor) is valor

    @pytest.mark.parametrize("valor", [0, 1, "true", "false", None, 1.0, [], b"\x01"], ids=repr)
    def test_recusa_o_que_parece_bool(self, valor):
        assert falha(validar, schema.Bool(), valor).code == TYPE


# ============================================================================ List


class TestList:
    def test_valida_cada_item_e_devolve_lista_nova(self):
        entrada = [1, 2, 3]
        saida = validar(schema.List(schema.Int(), 10), entrada)
        assert saida == [1, 2, 3] and saida is not entrada

    def test_lista_vazia_vale(self):
        assert validar(schema.List(schema.Int(), 10), []) == []

    def test_maximo_e_minimo_de_itens(self):
        esquema = schema.List(schema.Int(), 3, min_items=1)
        assert validar(esquema, [1, 2, 3]) == [1, 2, 3]
        assert falha(validar, esquema, [1, 2, 3, 4]).code == LENGTH
        assert falha(validar, esquema, []).code == LENGTH

    @pytest.mark.parametrize(
        "valor", [(1, 2), {1, 2}, "12", {"a": 1}, None, 5, b"12", range(2)], ids=lambda v: type(v).__name__
    )
    def test_so_list_vale(self, valor):
        assert falha(validar, schema.List(schema.Int(), 10), valor).code == TYPE

    def test_o_caminho_do_item_ruim_leva_o_indice(self):
        erro = falha(validar, schema.List(schema.Int(), 10), [1, 2, "tres", 4])
        assert erro.path == "[2]" and erro.code == TYPE

    def test_lista_de_dicionarios_aninhada_leva_o_caminho_completo(self):
        esquema = schema.Dict({"queue": schema.List(schema.Dict({"uri": schema.Str(5)}), 10)})
        erro = falha(validar, esquema, {"queue": [{"uri": "ok"}, {"uri": "demasiado"}]})
        assert erro.path == "queue[1].uri" and erro.code == LENGTH

    def test_o_tamanho_e_conferido_antes_de_validar_os_itens(self):
        """Uma lista enorme de itens ruins deve ser recusada pelo tamanho, sem percorrer tudo."""
        erro = falha(validar, schema.List(schema.Int(), 2), ["x"] * 1000)
        assert erro.code == LENGTH and erro.path == ""

    def test_nao_altera_a_entrada(self):
        entrada = [{"a": 1}, {"a": 2}]
        copia = copy.deepcopy(entrada)
        validar(schema.List(schema.Dict({"a": schema.Int()}), 5), entrada)
        assert entrada == copia


# ============================================================================ Dict e Optional


def esquema_de_sessao(**extra):
    return schema.Dict(
        {
            "_id": schema.SNOWFLAKE,
            "volume": schema.Int(0, 1000),
            "skin": schema.Str(64),
            "paused": schema.Bool(),
            "meta": schema.Dict({"a": schema.Int()}, **extra),
        },
        **extra,
    )


def sessao_valida():
    return {"_id": 5, "volume": 80, "skin": "default", "paused": False, "meta": {"a": 1}}


class TestDict:
    def test_devolve_dicionario_novo_com_os_campos_validados(self):
        entrada = sessao_valida()
        saida = validar(esquema_de_sessao(), entrada)
        assert saida == entrada and saida is not entrada and saida["meta"] is not entrada["meta"]

    def test_campo_obrigatorio_ausente(self):
        entrada = sessao_valida()
        del entrada["volume"]
        erro = falha(validar, esquema_de_sessao(), entrada)
        assert erro.code == MISSING and erro.path == "volume"

    def test_campo_obrigatorio_ausente_em_dicionario_aninhado_leva_o_caminho(self):
        entrada = sessao_valida()
        entrada["meta"] = {}
        erro = falha(validar, esquema_de_sessao(), entrada)
        assert erro.code == MISSING and erro.path == "meta.a"

    def test_campo_obrigatorio_com_none_nao_vale(self):
        entrada = sessao_valida()
        entrada["volume"] = None
        assert falha(validar, esquema_de_sessao(), entrada).code == TYPE

    def test_o_erro_aponta_o_campo_ruim(self):
        entrada = sessao_valida()
        entrada["volume"] = True
        erro = falha(validar, esquema_de_sessao(), entrada)
        assert erro.code == TYPE and erro.path == "volume"

    @pytest.mark.parametrize(
        "valor", [[], None, "texto", 5, (("a", 1),), OrderedDict(a=1)], ids=lambda v: type(v).__name__
    )
    def test_so_dict_vale(self, valor):
        assert falha(validar, schema.Dict({}), valor).code == TYPE

    def test_subclasse_de_dict_e_recusada(self):
        class Mapa(dict):
            pass

        assert falha(validar, schema.Dict({}), Mapa()).code == TYPE

    @pytest.mark.parametrize("chave", [1, b"a", None, ("a",), 1.5, True], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_e_recusada_em_qualquer_modo(self, chave):
        for modo in ("drop", "keep", "error"):
            assert falha(validar, schema.Dict({}, extra=modo), {chave: 1}).code == KEY_NOT_TEXT

    def test_nao_altera_a_entrada(self):
        entrada = sessao_valida()
        entrada["sobra"] = [1, {"x": 2}]
        copia = copy.deepcopy(entrada)
        validar(esquema_de_sessao(), entrada)
        assert entrada == copia

    def test_extra_padrao_e_drop(self):
        entrada = {**sessao_valida(), "desconhecido": 1}
        assert "desconhecido" not in validar(esquema_de_sessao(), entrada)

    def test_extra_invalido_e_recusado_na_construcao(self):
        with pytest.raises(ValueError):
            schema.Dict({}, extra="ignorar")


class TestExtra:
    def test_drop_descarta_os_campos_desconhecidos_em_todos_os_niveis(self):
        entrada = {**sessao_valida(), "x": 1}
        entrada["meta"] = {"a": 1, "y": 2}
        saida = validar(esquema_de_sessao(extra="drop"), entrada)
        assert saida == sessao_valida()

    def test_drop_avisa_no_log_sem_nomes_nem_valores(self, caplog):
        entrada = {**sessao_valida(), SEGREDO: SEGREDO, "outro-" + SEGREDO: 2}
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validar(esquema_de_sessao(), entrada)
        avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(avisos) == 1
        texto = avisos[0].getMessage()
        assert "2" in texto and SEGREDO not in texto and SEGREDO not in repr(avisos[0].args)

    def test_drop_avisa_o_caminho_do_dicionario(self, caplog):
        entrada = sessao_valida()
        entrada["meta"] = {"a": 1, "z": 9}
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validar(esquema_de_sessao(), entrada)
        assert any("meta" in r.getMessage() for r in caplog.records)

    def test_sem_campos_desconhecidos_nao_avisa(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validar(esquema_de_sessao(), sessao_valida())
        assert not [r for r in caplog.records if r.name == LOGGER]

    def test_keep_guarda_os_desconhecidos_validados_como_json_livre(self):
        entrada = {**sessao_valida(), "extra": {"lista": [1, "dois", None, 3.5]}}
        saida = validar(esquema_de_sessao(extra="keep"), entrada)
        assert saida["extra"] == {"lista": [1, "dois", None, 3.5]}
        assert saida["extra"] is not entrada["extra"]

    @pytest.mark.parametrize(
        ("valor", "codigo"),
        [(aninhado(9), DEPTH), ({1, 2}, TYPE), (b"x", TYPE), (float("nan"), NOT_FINITE), ("a\ud800", SURROGATE)],
        ids=["fundo", "set", "bytes", "nan", "surrogate"],
    )
    def test_keep_nao_deixa_passar_dado_que_nao_e_json(self, valor, codigo):
        entrada = {**sessao_valida(), "extra": valor}
        assert falha(validar, esquema_de_sessao(extra="keep"), entrada).code == codigo

    def test_keep_recusa_nome_de_campo_desconhecido_com_surrogate(self):
        entrada = {**sessao_valida(), "a\ud800": 1}
        assert falha(validar, esquema_de_sessao(extra="keep"), entrada).code == SURROGATE

    def test_error_recusa_campo_desconhecido_sem_dizer_o_nome(self):
        entrada = {**sessao_valida(), SEGREDO: 1}
        erro = falha(validar, esquema_de_sessao(extra="error"), entrada)
        assert erro.code == UNKNOWN_FIELD and erro.path == "" and not vazamentos(erro)

    def test_error_aponta_o_dicionario_aninhado_que_tem_a_sobra(self):
        entrada = sessao_valida()
        entrada["meta"] = {"a": 1, "z": 2}
        erro = falha(validar, esquema_de_sessao(extra="error"), entrada)
        assert erro.code == UNKNOWN_FIELD and erro.path == "meta"

    def test_error_sem_sobra_vale(self):
        assert validar(esquema_de_sessao(extra="error"), sessao_valida()) == sessao_valida()


class TestOptional:
    def esquema(self, **opcoes):
        return schema.Dict({"obrigatorio": schema.Int(), "opcional": schema.Optional(schema.Str(5), **opcoes)})

    def test_ausente_vira_o_padrao_none(self):
        assert validar(self.esquema(), {"obrigatorio": 1}) == {"obrigatorio": 1, "opcional": None}

    def test_ausente_vira_o_padrao_informado(self):
        assert validar(self.esquema(default="x"), {"obrigatorio": 1})["opcional"] == "x"

    def test_none_explicito_continua_none(self):
        assert validar(self.esquema(default="x"), {"obrigatorio": 1, "opcional": None})["opcional"] is None

    def test_presente_e_validado_pelo_esquema_de_dentro(self):
        assert validar(self.esquema(), {"obrigatorio": 1, "opcional": "abc"})["opcional"] == "abc"
        erro = falha(validar, self.esquema(), {"obrigatorio": 1, "opcional": "demasiado"})
        assert erro.code == LENGTH and erro.path == "opcional"
        assert falha(validar, self.esquema(), {"obrigatorio": 1, "opcional": 5}).code == TYPE

    def test_o_padrao_mutavel_nao_e_compartilhado_entre_resultados(self):
        esquema = schema.Dict({"lista": schema.Optional(schema.List(schema.Int(), 5), default=[])})
        primeiro, segundo = validar(esquema, {}), validar(esquema, {})
        primeiro["lista"].append(1)
        assert segundo["lista"] == []

    def test_opcional_fora_de_dicionario_aceita_none(self):
        assert validar(schema.Optional(schema.Int()), None) is None
        assert validar(schema.Optional(schema.Int()), 3) == 3
        assert falha(validar, schema.Optional(schema.Int()), "3").code == TYPE


# ============================================================================ nada do conteúdo vaza


def cenarios_de_vazamento():
    """``(descrição, função que recebe o módulo e levanta SchemaError com SEGREDO no dado)``."""
    return {
        "str-longa": lambda s: s.validate(s.Str(5), SEGREDO),
        "str-padrao": lambda s: s.validate(s.Str(80, pattern=r"[0-9]+"), SEGREDO),
        "str-controle": lambda s: s.validate(s.Str(80), SEGREDO + "\u202e"),
        "str-surrogate": lambda s: s.validate(s.Str(80), SEGREDO + "\ud800"),
        "str-tipo": lambda s: s.validate(s.Int(), SEGREDO),
        "int-tipo": lambda s: s.validate(s.Int(0, 5), {SEGREDO: SEGREDO}),
        "float-tipo": lambda s: s.validate(s.Float(), SEGREDO),
        "lista-tipo": lambda s: s.validate(s.List(s.Int(), 5), SEGREDO),
        "item-ruim": lambda s: s.validate(s.List(s.Int(), 5), [1, SEGREDO]),
        "campo-ruim": lambda s: s.validate(s.Dict({"a": s.Int()}), {"a": SEGREDO}),
        "campo-ausente": lambda s: s.validate(s.Dict({"a": s.Int()}), {SEGREDO: SEGREDO}),
        "desconhecido-error": lambda s: s.validate(s.Dict({}, extra="error"), {SEGREDO: SEGREDO}),
        "chave-nao-texto": lambda s: s.validate(s.Dict({}), {1: SEGREDO}),
        "json-livre-fundo": lambda s: s.validate(s.Any_JSON(), aninhado(20, SEGREDO)),
        "json-livre-tipo": lambda s: s.validate(s.Any_JSON(), {"a": [SEGREDO.encode()]}),
        "json-livre-chave": lambda s: s.validate(s.Any_JSON(), {SEGREDO: {1: SEGREDO}}),
        "json-livre-surrogate": lambda s: s.validate(s.Any_JSON(), {SEGREDO: SEGREDO + "\ud800"}),
        "estrutura-fundo": lambda s: s.check_structure(aninhado(40, SEGREDO)),
        "estrutura-tipo": lambda s: s.check_structure({"a": [SEGREDO.encode()]}),
        "estrutura-chave": lambda s: s.check_structure({SEGREDO: {b"x": SEGREDO}}),
        "estrutura-surrogate": lambda s: s.check_structure([SEGREDO + "\ud800"]),
    }


@pytest.mark.parametrize("nome", sorted(cenarios_de_vazamento()))
def test_nenhum_erro_leva_o_conteudo_do_dado(nome):
    erro = falha(cenarios_de_vazamento()[nome], schema)
    assert vazamentos(erro) == [], f"{nome}: o dado apareceu em {vazamentos(erro)}"
    assert SEGREDO not in repr(erro.__context__) and SEGREDO not in repr(erro.__cause__)


def test_o_erro_nao_guarda_referencia_ao_valor_recusado():
    erro = falha(schema.validate, schema.Str(3), SEGREDO)
    assert SEGREDO not in repr(vars(erro)) and SEGREDO not in repr(erro.args)

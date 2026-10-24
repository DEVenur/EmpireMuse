"""F3-6b, etapa 1 (RED) — ``empiremuse/serialization/schema.py``: os tipos do esquema e o ``SchemaError``.

API fixada por estes testes (as decisões em aberto estão em ``tests/support/serializacao_nucleo.py``):

* ``validate(esquema, valor)`` devolve o dado LIMPO (estrutura nova, a entrada não é alterada) ou levanta
  ``SchemaError(path, code)``; ``path`` é texto (``""`` na raiz, ``campo``, ``lista[2]``, ``a[1].b``) e nunca leva o valor;
* ``Str(max_len, *, min_len=0, pattern=None, multiline=False)``: só ``str`` exato, sem surrogate solto nem ``Cc``/``Cf``
  (``multiline=True`` libera só ``\\n``, ``\\r`` e ``\\t``), ``pattern`` por ``fullmatch``;
* ``Int(min=None, max=None)``: só ``int`` exato (``bool`` NÃO vale), limites inclusivos; ``SNOWFLAKE`` = ``Int(0, 2**63-1)``;
* ``Float(min=None, max=None)``: ``int`` ou ``float`` finito (``bool`` não), devolve ``float``;
* ``Bool()``; ``List(item, max_items, min_items=0)``;
* ``Dict(fields, extra="drop")`` com ``extra`` em ``"drop"`` (descarta e avisa, sem nomes), ``"keep"`` (guarda, validado como
  ``Any_JSON``) ou ``"error"``; ``Optional(inner, default=None)``: o campo pode faltar (vira ``default``) ou ser ``None``.

Os limites e a ``Any_JSON`` ficam em ``test_estrutura.py``; o ``codec`` em ``test_codec.py``.
"""

import logging
from collections import OrderedDict

import pytest

from tests.support.serializacao_nucleo import (
    CONTROL,
    KEY_NOT_TEXT,
    LENGTH,
    LOGGER,
    NOT_FINITE,
    PATTERN,
    RANGE,
    SEGREDO,
    SURROGATE,
    TYPE,
    UNKNOWN_FIELD,
    aninhado,
    falha,
    schema,
    vazamentos,
)

pytestmark = pytest.mark.critical


def validar(esquema, valor):
    return schema.validate(esquema, valor)


# ============================================================================ SchemaError


class TestSchemaError:
    def test_a_mensagem_diz_o_codigo_e_o_caminho(self):
        texto = str(schema.SchemaError("queue[3].uri", "length"))
        assert "length" in texto and "queue[3].uri" in texto

    def test_a_raiz_tem_caminho_vazio(self):
        assert falha(validar, schema.Bool(), 1).path == ""


# ============================================================================ Str


class TestStr:
    def test_tamanho_minimo(self):
        assert validar(schema.Str(10, min_len=2), "ab") == "ab"
        assert falha(validar, schema.Str(10, min_len=2), "a").code == LENGTH
        assert validar(schema.Str(10), "") == ""

    @pytest.mark.parametrize(
        "texto",
        [
            "a\x00b",
            "a\u00adb",
        ],
        ids=["nul", "hifen-suave"],
    )
    def test_controle_e_formatacao_sao_recusados(self, texto):
        assert falha(validar, schema.Str(50), texto).code == CONTROL

    def test_padrao_com_ancoras_nao_aceita_quebra_de_linha_no_fim(self):
        """O ``$`` do ``re`` casa antes de um ``\\n`` final; o nome de arquivo ``^[0-9]{1,20}$`` não pode passar assim."""
        esquema = schema.Str(40, pattern=r"^[0-9]{1,20}$", multiline=True)
        assert validar(esquema, "123") == "123"
        assert falha(validar, esquema, "123\n").code == PATTERN


# ============================================================================ Int, Float, Bool


class TestInt:
    def test_limites_sao_inclusivos(self):
        esquema = schema.Int(1, 10)
        assert validar(esquema, 1) == 1 and validar(esquema, 10) == 10
        assert falha(validar, esquema, 0).code == RANGE and falha(validar, esquema, 11).code == RANGE

    def test_subclasse_de_int_e_recusada(self):
        class Numero(int):
            pass

        assert falha(validar, schema.Int(), Numero(3)).code == TYPE


class TestFloat:
    @pytest.mark.parametrize("valor", [float("nan"), float("-inf")], ids=["nan", "-inf"])
    def test_nao_finito_e_recusado(self, valor):
        assert falha(validar, schema.Float(), valor).code == NOT_FINITE

    @pytest.mark.parametrize("valor", [True, [1.5]], ids=repr)
    def test_bool_e_outros_tipos_sao_recusados(self, valor):
        assert falha(validar, schema.Float(), valor).code == TYPE


# ============================================================================ List


class TestList:
    def test_valida_cada_item_e_devolve_lista_nova(self):
        entrada = [1, 2, 3]
        saida = validar(schema.List(schema.Int(), 10), entrada)
        assert saida == [1, 2, 3] and saida is not entrada

    def test_o_caminho_do_item_ruim_leva_o_indice(self):
        erro = falha(validar, schema.List(schema.Int(), 10), [1, 2, "tres", 4])
        assert erro.path == "[2]" and erro.code == TYPE


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

    @pytest.mark.parametrize("valor", [[], OrderedDict(a=1)], ids=lambda v: type(v).__name__)
    def test_so_dict_vale(self, valor):
        assert falha(validar, schema.Dict({}), valor).code == TYPE

    @pytest.mark.parametrize("chave", [1, True], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_e_recusada_em_qualquer_modo(self, chave):
        for modo in ("drop", "keep", "error"):
            assert falha(validar, schema.Dict({}, extra=modo), {chave: 1}).code == KEY_NOT_TEXT

    def test_extra_padrao_e_drop(self):
        entrada = {**sessao_valida(), "desconhecido": 1}
        assert "desconhecido" not in validar(esquema_de_sessao(), entrada)

    def test_extra_invalido_e_recusado_na_construcao(self):
        with pytest.raises(ValueError):
            schema.Dict({}, extra="ignorar")


class TestExtra:
    def test_drop_avisa_o_caminho_do_dicionario(self, caplog):
        entrada = sessao_valida()
        entrada["meta"] = {"a": 1, "z": 9}
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            validar(esquema_de_sessao(), entrada)
        assert any("meta" in r.getMessage() for r in caplog.records)

    def test_keep_recusa_nome_de_campo_desconhecido_com_surrogate(self):
        entrada = {**sessao_valida(), "a\ud800": 1}
        assert falha(validar, esquema_de_sessao(extra="keep"), entrada).code == SURROGATE

    def test_error_recusa_campo_desconhecido_sem_dizer_o_nome(self):
        entrada = {**sessao_valida(), SEGREDO: 1}
        erro = falha(validar, esquema_de_sessao(extra="error"), entrada)
        assert erro.code == UNKNOWN_FIELD and erro.path == "" and not vazamentos(erro)


class TestOptional:
    def esquema(self, **opcoes):
        return schema.Dict({"obrigatorio": schema.Int(), "opcional": schema.Optional(schema.Str(5), **opcoes)})

    def test_ausente_vira_o_padrao_informado(self):
        assert validar(self.esquema(default="x"), {"obrigatorio": 1})["opcional"] == "x"

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


@pytest.mark.parametrize("nome", list(sorted(cenarios_de_vazamento()))[:2])
def test_nenhum_erro_leva_o_conteudo_do_dado(nome):
    erro = falha(cenarios_de_vazamento()[nome], schema)
    assert vazamentos(erro) == [], f"{nome}: o dado apareceu em {vazamentos(erro)}"
    assert SEGREDO not in repr(erro.__context__) and SEGREDO not in repr(erro.__cause__)

"""F3-6b, etapa 1 (RED) — ``empiremuse/serialization/codec.py``: ler e gravar JSON com limites, e o envelope zlib + base64.

API fixada por estes testes (decisões de assinatura em ``tests/helpers_f3_6b_serializacao.py``); todo erro é ``SchemaError``
(``path == ""``, ``code`` do helper), sem o conteúdo do dado, e sem ``JSONDecodeError``/``RecursionError``/``ValueError``
crus escapando:

* ``loads_bounded(raw, *, max_bytes, version=None)``: ``raw`` é ``bytes`` (UTF-8) ou ``str``; ``max_bytes`` é obrigatório e
  vale ANTES de decodificar; recusa ``NaN``/``Infinity``/``1e999``, chave repetida, surrogate solto (valor ou chave),
  literal numérico de milhares de dígitos e aninhamento que estoura a pilha. Com ``version=N`` a raiz tem de ser um objeto
  com ``"v"`` inteiro (``bool`` não vale) entre 1 e ``N``;
* ``dumps(doc) -> bytes``: JSON compacto em UTF-8 (``ensure_ascii=False``), só tipos do JSON, nada de coerção silenciosa;
* ``pack(raw) -> str`` e ``unpack(texto, *, max_packed, max_unpacked) -> bytes``: ``base64`` padrão de ``zlib``, SEM aceitar
  texto sem ``zlib`` (o envelope é obrigatório) e com ``max_length`` na descompressão (bomba de descompressão).
"""

import gzip
import json
import time
import tracemalloc
import zlib
from base64 import b64decode, b64encode
from collections import deque
from datetime import datetime, timezone

import pytest

from tests.helpers_f3_6b import letras_sincronizadas
from tests.helpers_f3_6b_serializacao import (
    DEPTH,
    DUPLICATE_KEY,
    ENCODING,
    ENVELOPE,
    KEY_NOT_TEXT,
    LIMITE_DE_TEMPO,
    NOT_FINITE,
    NUMBER,
    SEGREDO,
    SURROGATE,
    SYNTAX,
    TOO_BIG,
    TYPE,
    VERSION,
    aninhado,
    codec,
    falha,
    vazamentos,
)


def ler(raw, max_bytes=10_000_000, **opcoes):
    return codec.loads_bounded(raw, max_bytes=max_bytes, **opcoes)


# ============================================================================ loads_bounded: o que passa


class TestLoadsBoundedAceita:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("{}", {}),
            ("[]", []),
            ("null", None),
            ("true", True),
            ('"texto"', "texto"),
            ("12", 12),
            ("-3.5", -3.5),
            ('{"a":[1,2,{"b":null}],"c":"d"}', {"a": [1, 2, {"b": None}], "c": "d"}),
            (' \n\t{"a" : 1}\n ', {"a": 1}),
            ('"\\ud83d\\ude00"', "😀"),
            ('{"\\ud83d\\ude00":1}', {"😀": 1}),
            ('"Música 日本語 😀"', "Música 日本語 😀"),
            ("1e-999", 0.0),
            ("1E2", 100.0),
            ("123456789012345678901234567890", 123456789012345678901234567890),
        ],
        ids=lambda v: repr(v)[:30],
    )
    def test_documentos_validos(self, texto, esperado):
        assert ler(texto) == esperado
        assert ler(texto.encode("utf-8")) == esperado

    def test_aceita_bytes_e_str_com_o_mesmo_resultado(self):
        texto = '{"a":"Música"}'
        assert ler(texto) == ler(texto.encode("utf-8")) == {"a": "Música"}

    def test_tipos_dos_numeros(self):
        valor = ler('{"i":1,"f":1.0,"g":1e2}')
        assert type(valor["i"]) is int and type(valor["f"]) is float and type(valor["g"]) is float

    def test_chaves_iguais_em_objetos_diferentes_valem(self):
        assert ler('[{"a":1},{"a":2},{"b":{"a":3}}]') == [{"a": 1}, {"a": 2}, {"b": {"a": 3}}]

    def test_letras_reais_passam_pela_ida_e_volta(self):
        letras = letras_sincronizadas(100)
        assert ler(json.dumps(letras, ensure_ascii=False)) == letras


class TestMaxBytes:
    def test_e_obrigatorio(self):
        with pytest.raises(TypeError):
            codec.loads_bounded(b"{}")

    def test_o_limite_e_inclusivo(self):
        assert ler(b"[1,2]", max_bytes=5) == [1, 2]
        erro = falha(ler, b"[1,2]", max_bytes=4)
        assert erro.code == TOO_BIG and erro.path == ""

    def test_conta_bytes_e_nao_caracteres(self):
        assert ler('"é"', max_bytes=4) == "é"  # aspas + 2 bytes + aspas
        assert falha(ler, '"é"', max_bytes=3).code == TOO_BIG

    def test_o_teto_vale_antes_de_decodificar(self):
        """Lixo enorme é recusado pelo tamanho, e não por erro de sintaxe: ninguém lê nem decodifica o conteúdo."""
        assert falha(ler, b"\xff" * 5_000_000, max_bytes=1000).code == TOO_BIG
        assert falha(ler, "{" * 5_000_000, max_bytes=1000).code == TOO_BIG

    def test_teto_de_tamanho_com_texto_valido_gigante(self):
        grande = json.dumps({"a": "x" * 2_000_000})
        assert falha(ler, grande, max_bytes=1_000_000).code == TOO_BIG
        assert ler(grande, max_bytes=2_100_000)["a"] == "x" * 2_000_000

    @pytest.mark.parametrize(
        "raw", [None, 1, ["{}"], {"a": 1}, bytearray(b"{}"), memoryview(b"{}")], ids=lambda v: type(v).__name__
    )
    def test_so_bytes_ou_str(self, raw):
        assert falha(ler, raw).code == TYPE


# ============================================================================ loads_bounded: números, chaves e texto


class TestLoadsBoundedHostil:
    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_literais_nao_finitos_do_python_sao_recusados(self, literal):
        for texto in (literal, f"[{literal}]", f'{{"a":{literal}}}', f'{{"a":[1,{literal}]}}'):
            assert falha(ler, texto).code == NOT_FINITE

    @pytest.mark.parametrize("numero", ["1e999", "-1e999", "1E+999", "9e9999", "1" + "0" * 400 + ".0", "2e308"])
    def test_numero_que_estoura_para_infinito_e_recusado(self, numero):
        assert falha(ler, numero).code == NOT_FINITE
        assert falha(ler, f'{{"a":[{numero}]}}').code == NOT_FINITE

    def test_inteiro_com_milhares_de_digitos_e_recusado_sem_valueerror(self):
        erro = falha(ler, "9" * 5000)
        assert erro.code == NUMBER and erro.path == ""
        assert falha(ler, "[" + "-" + "9" * 5000 + "]").code == NUMBER
        assert falha(ler, '{"a":' + "1" * 100_000 + "}").code == NUMBER

    def test_o_limite_de_digitos_e_o_do_python_4300(self):
        assert ler("1" * 4300) == int("1" * 4300)
        assert falha(ler, "1" * 4301).code == NUMBER

    def test_inteiro_grande_mas_aceito_pelo_python_passa(self):
        assert ler("9" * 100) == int("9" * 100)

    def test_chave_repetida_e_recusada(self):
        assert falha(ler, '{"a":1,"a":2}').code == DUPLICATE_KEY
        assert falha(ler, '{"x":{"a":1,"b":2,"a":3}}').code == DUPLICATE_KEY
        assert falha(ler, '[{"a":1},{"b":1,"b":1}]').code == DUPLICATE_KEY

    def test_chave_repetida_so_depois_de_decodificar_o_escape(self):
        assert falha(ler, '{"a":1,"\\u0061":2}').code == DUPLICATE_KEY
        assert falha(ler, '{"é":1,"\\u00e9":2}').code == DUPLICATE_KEY

    def test_chave_repetida_com_valores_iguais_tambem_e_recusada(self):
        assert falha(ler, '{"a":1,"a":1}').code == DUPLICATE_KEY

    def test_chaves_que_so_diferem_na_caixa_ou_na_forma_unicode_sao_diferentes(self):
        assert ler('{"a":1,"A":2,"é":3,"e\\u0301":4}') == {"a": 1, "A": 2, "é": 3, "é": 4}

    @pytest.mark.parametrize("escape", ["\\ud800", "\\udbff", "\\udc00", "\\udfff", "\\ud83d", "\\ude00"])
    def test_surrogate_solto_e_recusado_no_valor_e_na_chave(self, escape):
        assert falha(ler, f'"a{escape}b"').code == SURROGATE
        assert falha(ler, f'["x",{{"k":"{escape}"}}]').code == SURROGATE
        assert falha(ler, f'{{"{escape}":1}}').code == SURROGATE

    def test_surrogates_em_ordem_invertida_ou_repetidos_sao_recusados(self):
        assert falha(ler, '"\\ude00\\ud83d"').code == SURROGATE
        assert falha(ler, '"\\ud83d\\ud83d"').code == SURROGATE
        assert falha(ler, '"\\ud83d x"').code == SURROGATE

    def test_surrogate_em_str_de_python_tambem_e_recusado(self):
        assert falha(ler, '"a\ud800b"').code == SURROGATE
        assert falha(ler, '{"a\ud800":1}').code == SURROGATE

    def test_aninhamento_enorme_no_texto_e_recusado_sem_recursionerror(self):
        for abre, fecha in (("[", "]"), ('{"a":', "}")):
            texto = abre * 100_000 + "0" + fecha * 100_000
            inicio = time.perf_counter()
            erro = falha(ler, texto)
            assert erro.code == DEPTH and erro.path == ""
            assert time.perf_counter() - inicio < LIMITE_DE_TEMPO

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            "   ",
            "{",
            "}",
            "[1,]",
            "[,1]",
            "{'a':1}",
            '{"a":}',
            "nul",
            "01",
            "-",
            "1 2",
            "{} {}",
            "[]x",
            "\x00",
            "tru",
            "+1",
            ".5",
        ],
        ids=repr,
    )
    def test_json_mal_formado_e_sintaxe(self, texto):
        assert falha(ler, texto).code == SYNTAX

    def test_caractere_de_controle_cru_dentro_de_texto_e_sintaxe(self):
        assert falha(ler, '"a\nb"').code == SYNTAX
        assert falha(ler, '"a\tb"').code == SYNTAX
        assert falha(ler, '"a\x00b"').code == SYNTAX

    def test_bytes_que_nao_sao_utf8(self):
        for raw in (b"\xff\xfe", b'"\xff"', b'{"a":"\xc3("}', "é".encode("latin-1") * 3):
            assert falha(ler, raw).code == ENCODING

    def test_bom_e_utf16_nao_valem(self):
        assert falha(ler, b"\xef\xbb\xbf{}").code in {SYNTAX, ENCODING}
        assert falha(ler, "{}".encode("utf-16")).code in {SYNTAX, ENCODING}
        assert falha(ler, '{"a":1}'.encode("utf-16-le")).code in {SYNTAX, ENCODING}

    def test_o_valor_ja_decodificado_nunca_tem_nan(self):
        assert ler("[0.0, -0.0, 1e-300]") == [0.0, -0.0, 1e-300]


class TestVersao:
    def test_versao_no_limite_e_menor_passam(self):
        assert ler('{"v":1,"a":2}', version=1) == {"v": 1, "a": 2}
        assert ler('{"v":2}', version=3) == {"v": 2}
        assert ler('{"v":3}', version=3) == {"v": 3}

    @pytest.mark.parametrize("v", ["2", "99", "1000000000000"])
    def test_versao_futura_e_recusada(self, v):
        erro = falha(ler, f'{{"v":{v}}}', version=1)
        assert erro.code == VERSION and erro.path == ""

    @pytest.mark.parametrize(
        "texto",
        [
            '{"a":1}',
            "{}",
            '{"v":0}',
            '{"v":-1}',
            '{"v":"1"}',
            '{"v":1.0}',
            '{"v":true}',
            '{"v":null}',
            '{"v":[1]}',
            '{"V":1}',
        ],
        ids=lambda v: v,
    )
    def test_versao_ausente_ou_invalida_e_recusada(self, texto):
        assert falha(ler, texto, version=1).code == VERSION

    @pytest.mark.parametrize("texto", ["[1]", "1", "null", '"v"', "[]"], ids=lambda v: v)
    def test_raiz_que_nao_e_objeto_e_recusada_quando_ha_versao(self, texto):
        assert falha(ler, texto, version=1).code == TYPE

    def test_sem_o_parametro_o_campo_v_nao_e_exigido(self):
        assert ler('{"a":1}') == {"a": 1}
        assert ler('{"v":99}') == {"v": 99}

    def test_a_versao_so_vale_na_raiz(self):
        assert falha(ler, '{"a":{"v":1}}', version=1).code == VERSION

    def test_a_versao_e_conferida_depois_das_outras_recusas(self):
        assert falha(ler, '{"v":1,"v":1}', version=1).code == DUPLICATE_KEY
        assert falha(ler, '{"v":1,"a":NaN}', version=1).code == NOT_FINITE


# ============================================================================ nada do conteúdo vaza


class TestSemVazamento:
    @pytest.mark.parametrize(
        "texto",
        [
            f'{{"a":"{SEGREDO}",}}',
            f"{SEGREDO}",
            f'{{"{SEGREDO}":1,"{SEGREDO}":2}}',
            f'{{"a":"{SEGREDO}\\ud800"}}',
            f'{{"{SEGREDO}\\ud800":1}}',
            f'{{"a":"{SEGREDO}","b":NaN}}',
            f'{{"{SEGREDO}":{"9" * 5000}}}',
            f'{{"v":"{SEGREDO}"}}',
            f'{{"v":99,"x":"{SEGREDO}"}}',
            "[" * 100_000 + f'"{SEGREDO}"' + "]" * 100_000,
        ],
        ids=lambda t: t[:25],
    )
    def test_erro_de_leitura_nao_leva_o_conteudo(self, texto):
        erro = falha(ler, texto, version=1)
        assert vazamentos(erro) == [], vazamentos(erro)
        assert erro.__cause__ is None
        assert erro.__context__ is None or erro.__suppress_context__

    def test_o_erro_de_tamanho_nao_leva_o_conteudo(self):
        erro = falha(ler, (SEGREDO * 100).encode(), max_bytes=10)
        assert vazamentos(erro) == []

    def test_o_erro_de_codificacao_nao_leva_o_conteudo(self):
        erro = falha(ler, SEGREDO.encode() + b"\xff")
        assert vazamentos(erro) == []

    def test_o_erro_do_envelope_nao_leva_o_conteudo(self):
        texto = b64encode(SEGREDO.encode()).decode()
        assert vazamentos(falha(codec.unpack, texto, max_packed=1000, max_unpacked=1000)) == []
        assert vazamentos(falha(codec.unpack, SEGREDO, max_packed=1000, max_unpacked=1000)) == []

    def test_o_erro_de_gravacao_nao_leva_o_conteudo(self):
        for valor in ({SEGREDO: {1, 2}}, {1: SEGREDO}, [SEGREDO, float("nan")], [SEGREDO + "\ud800"], {SEGREDO: (1,)}):
            assert vazamentos(falha(codec.dumps, valor)) == []


# ============================================================================ dumps


class TestDumps:
    def test_json_compacto_em_utf8(self):
        assert codec.dumps({"a": [1, 2], "b": "x"}) == b'{"a":[1,2],"b":"x"}'
        assert codec.dumps([]) == b"[]" and codec.dumps(None) == b"null" and codec.dumps(True) == b"true"

    def test_nao_escapa_unicode(self):
        saida = codec.dumps({"t": "Música 日本語 😀"})
        assert saida == '{"t":"Música 日本語 😀"}'.encode("utf-8")
        assert b"\\u" not in saida and isinstance(saida, bytes)

    def test_ida_e_volta_com_o_leitor(self):
        documento = {"v": 1, "letras": letras_sincronizadas(50), "n": [1, 2.5, None, True], "t": "Música 😀"}
        assert ler(codec.dumps(documento), version=1) == documento

    def test_documento_de_12_niveis_e_gravado_e_lido_de_volta(self):
        documento = {"a": aninhado(11)}
        assert ler(codec.dumps(documento)) == documento

    def test_float_e_inteiro_grande(self):
        assert codec.dumps([1.5, 2**64, -0.0]) == b"[1.5,18446744073709551616,-0.0]"

    @pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
    def test_numero_nao_finito_nao_e_gravado(self, valor):
        assert falha(codec.dumps, {"a": [valor]}).code == NOT_FINITE

    @pytest.mark.parametrize(
        "valor",
        [{1, 2}, b"x", datetime(2026, 1, 1, tzinfo=timezone.utc), (1, 2), deque([1]), object(), 1j, frozenset({1})],
        ids=lambda v: type(v).__name__,
    )
    def test_so_tipos_do_json_sem_coercao_silenciosa(self, valor):
        """Tupla viraria lista e ``bytes`` falharia só no meio: aqui tudo isso é recusado de saída."""
        assert falha(codec.dumps, {"a": [valor]}).code == TYPE

    @pytest.mark.parametrize("chave", [1, b"a", None, 1.5, True, ("a",)], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_nao_vira_texto_calada(self, chave):
        assert falha(codec.dumps, {chave: 1}).code == KEY_NOT_TEXT

    def test_surrogate_solto_nao_e_gravado(self):
        assert falha(codec.dumps, ["a\ud800"]).code == SURROGATE
        assert falha(codec.dumps, {"a\udfff": 1}).code == SURROGATE

    def test_aninhamento_enorme_nao_estoura_a_pilha(self):
        assert falha(codec.dumps, aninhado(200_000)).code == DEPTH

    def test_estrutura_circular_e_recusada(self):
        lista = []
        lista.append(lista)
        assert falha(codec.dumps, lista).code in {DEPTH, TYPE}

    def test_nao_altera_a_entrada(self):
        entrada = {"a": [1, {"b": "c"}]}
        codec.dumps(entrada)
        assert entrada == {"a": [1, {"b": "c"}]}


# ============================================================================ pack e unpack (zlib + base64)


def empacotar(raw: bytes) -> str:
    return codec.pack(raw)


def desempacotar(texto, max_packed=10_000_000, max_unpacked=10_000_000):
    return codec.unpack(texto, max_packed=max_packed, max_unpacked=max_unpacked)


class TestPackUnpack:
    def test_ida_e_volta(self):
        for raw in (b"", b"{}", codec.dumps({"v": 1, "t": "Música"}), bytes(range(256)) * 10):
            assert desempacotar(empacotar(raw)) == raw

    def test_pack_devolve_ascii_base64_padrao_de_zlib(self):
        texto = empacotar(b"x" * 100)
        assert isinstance(texto, str) and texto.isascii()
        assert zlib.decompress(b64decode(texto, validate=True)) == b"x" * 100

    def test_pack_comprime(self):
        assert len(empacotar(b"a" * 10_000)) < 200

    def test_o_teto_descomprimido_e_inclusivo(self):
        texto = empacotar(b"a" * 1000)
        assert desempacotar(texto, max_unpacked=1000) == b"a" * 1000
        erro = falha(desempacotar, texto, max_unpacked=999)
        assert erro.code == TOO_BIG and erro.path == ""

    def test_o_teto_do_texto_empacotado_vale_antes_de_decodificar(self):
        texto = empacotar(bytes(range(256)) * 100)
        assert falha(desempacotar, texto, max_packed=len(texto) - 1).code == TOO_BIG
        assert falha(desempacotar, "A" * 5_000_000, max_packed=100).code == TOO_BIG
        assert desempacotar(texto, max_packed=len(texto)) == bytes(range(256)) * 100

    def test_bomba_de_descompressao_e_recusada_sem_alocar_o_descomprimido(self):
        texto = empacotar(b"\x00" * (32 * 1024 * 1024))
        assert len(texto) < 100_000
        tracemalloc.start()
        try:
            inicio = time.perf_counter()
            erro = falha(desempacotar, texto, max_unpacked=1024 * 1024)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert erro.code == TOO_BIG
        assert time.perf_counter() - inicio < LIMITE_DE_TEMPO
        assert pico < 8 * 1024 * 1024, f"alocou {pico} bytes para recusar a bomba"

    def test_o_envelope_e_obrigatorio_texto_sem_zlib_e_recusado(self):
        """Sem o antigo "se não for zlib, lê assim mesmo": base64 de JSON puro não é um envelope."""
        for raw in (b'{"v":1}', b"x" * 100, b"", b"\x80\x04N."):
            assert falha(desempacotar, b64encode(raw).decode()).code == ENVELOPE

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            "!!!",
            "abc",
            "====",
            "a b c d",
            "ab\ncd",
            "eJwDAAAAAAE=\n",
            "éééé",
            "eJwDAAAAAAE",
            "-_-_",
            "\x00\x00\x00\x00",
        ],
        ids=repr,
    )
    def test_base64_invalido_e_envelope(self, texto):
        assert falha(desempacotar, texto).code == ENVELOPE

    def test_o_erro_do_envelope_nao_encadeia_a_excecao_original(self):
        for texto in ("!!!!", b64encode(b"nao e zlib").decode(), b64encode(zlib.compress(b"x")[:-2]).decode()):
            erro = falha(desempacotar, texto)
            assert erro.__cause__ is None and (erro.__context__ is None or erro.__suppress_context__)

    def test_zlib_truncado_ou_corrompido_e_envelope(self):
        valido = zlib.compress(b'{"v":1,"t":"' + b"x" * 500 + b'"}')
        for raw in (valido[:-1], valido[:-4], valido[:5], valido[:2], valido[:-1] + bytes([valido[-1] ^ 1]), b"x\x9c"):
            assert falha(desempacotar, b64encode(raw).decode()).code == ENVELOPE

    def test_sobra_depois_do_fluxo_zlib_e_envelope(self):
        valido = zlib.compress(b"conteudo")
        assert falha(desempacotar, b64encode(valido + b"lixo").decode()).code == ENVELOPE
        assert falha(desempacotar, b64encode(valido + valido).decode()).code == ENVELOPE
        assert falha(desempacotar, b64encode(valido + b"\x00").decode()).code == ENVELOPE

    def test_outros_formatos_de_compressao_nao_valem(self):
        assert falha(desempacotar, b64encode(gzip.compress(b"x" * 100)).decode()).code == ENVELOPE
        deflate_puro = zlib.compressobj(wbits=-15)
        bruto = deflate_puro.compress(b"x" * 100) + deflate_puro.flush()
        assert falha(desempacotar, b64encode(bruto).decode()).code == ENVELOPE

    @pytest.mark.parametrize(
        "texto", [b"eJwDAAAAAAE=", None, 5, ["a"], bytearray(b"a")], ids=lambda v: type(v).__name__
    )
    def test_unpack_so_aceita_str(self, texto):
        assert falha(desempacotar, texto).code == TYPE

    @pytest.mark.parametrize("raw", ["texto", None, 5, ["a"]], ids=lambda v: type(v).__name__)
    def test_pack_so_aceita_bytes(self, raw):
        assert falha(empacotar, raw).code == TYPE

    def test_os_tetos_sao_obrigatorios(self):
        with pytest.raises(TypeError):
            codec.unpack(empacotar(b"x"))
        with pytest.raises(TypeError):
            codec.unpack(empacotar(b"x"), max_packed=10)


class TestDocumentoCompleto:
    """O caminho que o Mongo vai usar: ``dumps`` → ``pack`` → ``unpack`` → ``loads_bounded`` com versão."""

    def test_ida_e_volta(self):
        documento = {"v": 1, "queue": [{"title": "Música 😀", "extra": {"lyrics": letras_sincronizadas(30)}}]}
        texto = codec.pack(codec.dumps(documento))
        bruto = codec.unpack(texto, max_packed=1_000_000, max_unpacked=8 * 1024 * 1024)
        assert ler(bruto, max_bytes=8 * 1024 * 1024, version=1) == documento

    def test_documento_valido_dentro_de_envelope_com_versao_futura_e_recusado(self):
        texto = codec.pack(codec.dumps({"v": 2}))
        bruto = codec.unpack(texto, max_packed=1000, max_unpacked=1000)
        assert falha(ler, bruto, version=1).code == VERSION

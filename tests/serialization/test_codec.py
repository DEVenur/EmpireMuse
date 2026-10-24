"""F3-6b, etapa 1 (RED) — ``empiremuse/serialization/codec.py``: ler e gravar JSON com limites, e o envelope zlib + base64.

API fixada por estes testes (decisões de assinatura em ``tests/support/serializacao_nucleo.py``); todo erro é ``SchemaError``
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

import json
import zlib
from base64 import b64encode

import pytest

from tests.support.formatos_reais import letras_sincronizadas
from tests.support.serializacao_nucleo import (
    DUPLICATE_KEY,
    ENCODING,
    ENVELOPE,
    KEY_NOT_TEXT,
    NUMBER,
    SEGREDO,
    SURROGATE,
    SYNTAX,
    TOO_BIG,
    TYPE,
    VERSION,
    codec,
    falha,
    vazamentos,
)

pytestmark = pytest.mark.critical


def ler(raw, max_bytes=10_000_000, **opcoes):
    return codec.loads_bounded(raw, max_bytes=max_bytes, **opcoes)


# ============================================================================ loads_bounded: o que passa


class TestLoadsBoundedAceita:
    @pytest.mark.smoke
    def test_aceita_bytes_e_str_com_o_mesmo_resultado(self):
        texto = '{"a":"Música"}'
        assert ler(texto) == ler(texto.encode("utf-8")) == {"a": "Música"}

    def test_letras_reais_passam_pela_ida_e_volta(self):
        letras = letras_sincronizadas(100)
        assert ler(json.dumps(letras, ensure_ascii=False)) == letras


class TestMaxBytes:
    def test_conta_bytes_e_nao_caracteres(self):
        assert ler('"é"', max_bytes=4) == "é"  # aspas + 2 bytes + aspas
        assert falha(ler, '"é"', max_bytes=3).code == TOO_BIG

    @pytest.mark.parametrize("raw", [None, memoryview(b"{}")], ids=lambda v: type(v).__name__)
    def test_so_bytes_ou_str(self, raw):
        assert falha(ler, raw).code == TYPE


# ============================================================================ loads_bounded: números, chaves e texto


class TestLoadsBoundedHostil:
    def test_inteiro_com_milhares_de_digitos_e_recusado_sem_valueerror(self):
        erro = falha(ler, "9" * 5000)
        assert erro.code == NUMBER and erro.path == ""
        assert falha(ler, "[" + "-" + "9" * 5000 + "]").code == NUMBER
        assert falha(ler, '{"a":' + "1" * 100_000 + "}").code == NUMBER

    def test_chave_repetida_so_depois_de_decodificar_o_escape(self):
        assert falha(ler, '{"a":1,"\\u0061":2}').code == DUPLICATE_KEY
        assert falha(ler, '{"é":1,"\\u00e9":2}').code == DUPLICATE_KEY

    @pytest.mark.parametrize("escape", ["\\ud800", "\\ude00"])
    def test_surrogate_solto_e_recusado_no_valor_e_na_chave(self, escape):
        assert falha(ler, f'"a{escape}b"').code == SURROGATE
        assert falha(ler, f'["x",{{"k":"{escape}"}}]').code == SURROGATE
        assert falha(ler, f'{{"{escape}":1}}').code == SURROGATE

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            ".5",
        ],
        ids=repr,
    )
    def test_json_mal_formado_e_sintaxe(self, texto):
        assert falha(ler, texto).code == SYNTAX

    def test_bom_e_utf16_nao_valem(self):
        assert falha(ler, b"\xef\xbb\xbf{}").code in {SYNTAX, ENCODING}
        assert falha(ler, "{}".encode("utf-16")).code in {SYNTAX, ENCODING}
        assert falha(ler, '{"a":1}'.encode("utf-16-le")).code in {SYNTAX, ENCODING}


class TestVersao:
    @pytest.mark.parametrize("v", ["2", "1000000000000"])
    def test_versao_futura_e_recusada(self, v):
        erro = falha(ler, f'{{"v":{v}}}', version=1)
        assert erro.code == VERSION and erro.path == ""

    def test_sem_o_parametro_o_campo_v_nao_e_exigido(self):
        assert ler('{"a":1}') == {"a": 1}
        assert ler('{"v":99}') == {"v": 99}


# ============================================================================ nada do conteúdo vaza


class TestSemVazamento:
    @pytest.mark.parametrize(
        "texto",
        [
            f'{{"a":"{SEGREDO}",}}',
            "[" * 100_000 + f'"{SEGREDO}"' + "]" * 100_000,
        ],
        ids=lambda t: t[:25],
    )
    def test_erro_de_leitura_nao_leva_o_conteudo(self, texto):
        erro = falha(ler, texto, version=1)
        assert vazamentos(erro) == [], vazamentos(erro)
        assert erro.__cause__ is None
        assert erro.__context__ is None or erro.__suppress_context__

    def test_o_erro_do_envelope_nao_leva_o_conteudo(self):
        texto = b64encode(SEGREDO.encode()).decode()
        assert vazamentos(falha(codec.unpack, texto, max_packed=1000, max_unpacked=1000)) == []
        assert vazamentos(falha(codec.unpack, SEGREDO, max_packed=1000, max_unpacked=1000)) == []


# ============================================================================ dumps


class TestDumps:
    def test_nao_escapa_unicode(self):
        saida = codec.dumps({"t": "Música 日本語 😀"})
        assert saida == '{"t":"Música 日本語 😀"}'.encode("utf-8")
        assert b"\\u" not in saida and isinstance(saida, bytes)

    def test_float_e_inteiro_grande(self):
        assert codec.dumps([1.5, 2**64, -0.0]) == b"[1.5,18446744073709551616,-0.0]"

    @pytest.mark.parametrize("chave", [1, ("a",)], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_nao_vira_texto_calada(self, chave):
        assert falha(codec.dumps, {chave: 1}).code == KEY_NOT_TEXT

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
    def test_pack_comprime(self):
        assert len(empacotar(b"a" * 10_000)) < 200

    def test_o_envelope_e_obrigatorio_texto_sem_zlib_e_recusado(self):
        """Sem o antigo "se não for zlib, lê assim mesmo": base64 de JSON puro não é um envelope."""
        for raw in (b'{"v":1}', b"x" * 100, b"", b"\x80\x04N."):
            assert falha(desempacotar, b64encode(raw).decode()).code == ENVELOPE

    def test_zlib_truncado_ou_corrompido_e_envelope(self):
        valido = zlib.compress(b'{"v":1,"t":"' + b"x" * 500 + b'"}')
        for raw in (valido[:-1], valido[:-4], valido[:5], valido[:2], valido[:-1] + bytes([valido[-1] ^ 1]), b"x\x9c"):
            assert falha(desempacotar, b64encode(raw).decode()).code == ENVELOPE

    @pytest.mark.parametrize("texto", [b"eJwDAAAAAAE=", bytearray(b"a")], ids=lambda v: type(v).__name__)
    def test_unpack_so_aceita_str(self, texto):
        assert falha(desempacotar, texto).code == TYPE


class TestDocumentoCompleto:
    """O caminho que o Mongo vai usar: ``dumps`` → ``pack`` → ``unpack`` → ``loads_bounded`` com versão."""

    def test_ida_e_volta(self):
        documento = {"v": 1, "queue": [{"title": "Música 😀", "extra": {"lyrics": letras_sincronizadas(30)}}]}
        texto = codec.pack(codec.dumps(documento))
        bruto = codec.unpack(texto, max_packed=1_000_000, max_unpacked=8 * 1024 * 1024)
        assert ler(bruto, max_bytes=8 * 1024 * 1024, version=1) == documento

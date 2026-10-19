"""Ler e gravar JSON com limites, e o envelope ``zlib`` + ``base64`` usado no Mongo.

Todo erro é ``SchemaError`` (``path == ""``), sem o conteúdo do dado e sem a exceção original encadeada.
O envelope é obrigatório: não existe leitura "sem zlib".
"""

from __future__ import annotations

import binascii
import json
import math
import zlib
from base64 import b64decode, b64encode
from typing import Any

from .schema import (
    DEPTH,
    DUPLICATE_KEY,
    ENCODING,
    ENVELOPE,
    NOT_FINITE,
    NUMBER,
    STRUCTURE_MAX_DEPTH,
    STRUCTURE_MAX_NODES,
    SURROGATE,
    SYNTAX,
    TOO_BIG,
    TYPE,
    VERSION,
    SchemaError,
    scan,
)

MAX_INT_DIGITS = 4300  # igual ao padrão do Python, mas fixo: não depende de ``sys.set_int_max_str_digits``
MAX_DUMPS_DEPTH = 64  # mais fundo que qualquer documento real (8 a 12) e bem abaixo do limite de recursão

# Na leitura, um documento de ``max_bytes`` bytes não tem mais que ``max_bytes`` nós; o aninhamento já é limitado pela pilha.
_LOADS_DEPTH = 10**9


def _fail(code: str) -> SchemaError:
    return SchemaError("", code)


# ============================================================================ leitura


def _parse_constant(_name: str) -> Any:
    raise _fail(NOT_FINITE)


def _parse_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise _fail(NOT_FINITE)
    return number


def _parse_int(text: str) -> int:
    if len(text) > MAX_INT_DIGITS:
        raise _fail(NUMBER)
    try:
        return int(text)
    except ValueError:
        raise _fail(NUMBER) from None


def _object_from_pairs(pairs: list) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _fail(DUPLICATE_KEY)
    return result


def _to_text(raw: Any, max_bytes: int) -> str:
    """Confere tipo e tamanho ANTES de decodificar e devolve o texto UTF-8."""
    if type(raw) is str:
        if len(raw) > max_bytes:
            raise _fail(TOO_BIG)
        try:
            data = raw.encode("utf-8")
        except UnicodeEncodeError:
            raise _fail(SURROGATE) from None
    elif type(raw) is bytes:
        data = raw
    else:
        raise _fail(TYPE)
    if len(data) > max_bytes:
        raise _fail(TOO_BIG)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail(ENCODING) from None


def _check_version(document: Any, version: int) -> None:
    if type(document) is not dict:
        raise _fail(TYPE)
    found = document.get("v")
    if type(found) is not int or not 1 <= found <= version:
        raise _fail(VERSION)


def loads_bounded(raw: bytes | str, *, max_bytes: int, version: int | None = None) -> Any:
    """Lê JSON de até ``max_bytes`` bytes; com ``version=N`` a raiz é um objeto com ``"v"`` inteiro entre 1 e ``N``."""
    text = _to_text(raw, max_bytes)
    try:
        document = json.loads(
            text,
            parse_float=_parse_float,
            parse_int=_parse_int,
            parse_constant=_parse_constant,
            object_pairs_hook=_object_from_pairs,
        )
    except SchemaError:
        raise
    except json.JSONDecodeError:
        raise _fail(SYNTAX) from None
    except RecursionError:
        raise _fail(DEPTH) from None
    except MemoryError:
        raise _fail(TOO_BIG) from None
    scan(document, "", _LOADS_DEPTH, max_bytes + 1, legacy=False)
    if version is not None:
        _check_version(document, version)
    return document


# ============================================================================ gravação


def dumps(document: Any) -> bytes:
    """JSON compacto em UTF-8, estrito: só tipos do JSON e nada de coerção silenciosa (``tuple``, chave ``int``...)."""
    scan(document, "", MAX_DUMPS_DEPTH, STRUCTURE_MAX_NODES, legacy=False)
    try:
        text = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError:  # inteiro com milhares de dígitos
        raise _fail(NUMBER) from None
    return text.encode("utf-8")


# ============================================================================ envelope zlib + base64


def pack(raw: bytes) -> str:
    """``base64`` padrão (ASCII) de ``zlib`` do conteúdo."""
    if type(raw) is not bytes:
        raise _fail(TYPE)
    return b64encode(zlib.compress(raw)).decode("ascii")


def _decode_base64(text: str) -> bytes:
    try:
        return b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise _fail(ENVELOPE) from None


def unpack(text: str, *, max_packed: int, max_unpacked: int) -> bytes:
    """Desfaz o envelope: texto até ``max_packed``, conteúdo até ``max_unpacked`` (``max_length``), fluxo íntegro e sem sobra."""
    if type(text) is not str:
        raise _fail(TYPE)
    if len(text) > max_packed:
        raise _fail(TOO_BIG)
    stream = zlib.decompressobj()
    try:
        content = stream.decompress(_decode_base64(text), max_unpacked + 1)
    except zlib.error:
        raise _fail(ENVELOPE) from None
    if len(content) > max_unpacked:
        raise _fail(TOO_BIG)
    if not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise _fail(ENVELOPE)
    return content

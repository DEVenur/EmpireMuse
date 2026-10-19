"""Leitor do formato antigo (``pickle``) das sessões, filas salvas e skins: a ÚNICA porta de entrada do ``pickle``.

``load_legacy(raw, kind)`` nunca chama um ``pickle.load(s)`` completo sobre dado não confiável. Ordem fixa:

1. envelope: tamanho bruto, ``zlib`` com ``max_length`` (bomba de descompressão), sem sobra;
2. pré-varredura por ``pickletools.genops`` (Python puro, não executa nada): protocolo 4 ou 5, lista fechada de opcodes,
   ``STACK_GLOBAL`` só com o par da allowlist do ``kind`` (a varredura simula pilha, marcas e memo, então nomes vindos de
   ``BINGET`` também são conferidos) e tetos de opcodes, de ``MARK`` aninhado, de itens de ``set`` e de ``deque``;
3. ``Unpickler`` restrito: ``find_class`` só devolve as classes da allowlist, ``persistent_load`` levanta;
4. ``check_structure`` (validador iterativo do documento legado inteiro) no resultado.

Todo erro é ``LegacyFormatError`` (``SchemaError``), sem o valor do dado e sem a exceção original encadeada.
O arquivo é descartável: sai na etapa 7 da F3-6b, depois de uma versão publicada com a migração.
"""

from __future__ import annotations

import base64
import binascii
import io
import pickle
import pickletools
import zlib
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, NamedTuple

from .schema import DEPTH, ENVELOPE, KEY_NOT_TEXT, TOO_BIG, TYPE, SchemaError, check_structure

PROTOCOL = "protocol"
OPCODE = "opcode"
GLOBAL = "global"
OPCODE_LIMIT = "opcode_limit"
MARK_LIMIT = "mark_limit"
SET_LIMIT = "set_limit"
CORRUPT = "corrupt"

MIB = 1024 * 1024
MAX_RAW = {"session": 8 * MIB, "queue": 4 * MIB, "skin": 100 * 1024}  # bruto e descomprimido, em bytes
MAX_OPCODES = {"session": 1_500_000, "queue": 600_000, "skin": 50_000}
MAX_MARK_DEPTH = 64
MAX_SET_ITEMS = 1000  # teto de itens de ``set``, somando todos os ``ADDITEMS`` do documento
MAX_TUPLE_DEPTH = 8  # tuplas dentro de tuplas (o gravador real tem até 3 níveis)
MAX_DEQUES = 2  # a sessão real tem um (``command_log_list``); ``deque(iteravel)`` copia o argumento a cada chamada
PROTOCOLS = (4, 5)

_DATE_CLASSES = {
    ("datetime", "datetime"): datetime,
    ("datetime", "timezone"): timezone,
    ("datetime", "timedelta"): timedelta,
}
_CLASSES = {**_DATE_CLASSES, ("collections", "deque"): deque}
ALLOWED_GLOBALS = {
    "session": frozenset(_CLASSES),
    "queue": frozenset(_DATE_CLASSES),
    "skin": frozenset(),
}

_PLAIN_OPCODES = frozenset(
    "PROTO FRAME STOP MARK NONE NEWTRUE NEWFALSE BININT BININT1 BININT2 LONG1 BINFLOAT SHORT_BINUNICODE BINUNICODE "
    "SHORT_BINBYTES BINBYTES EMPTY_LIST EMPTY_DICT EMPTY_TUPLE EMPTY_SET APPEND APPENDS SETITEM SETITEMS ADDITEMS "
    "TUPLE1 TUPLE2 TUPLE3 MEMOIZE BINGET LONG_BINGET".split()
)
_OPCODES = {
    "session": _PLAIN_OPCODES | {"STACK_GLOBAL", "REDUCE"},
    "queue": _PLAIN_OPCODES | {"STACK_GLOBAL", "REDUCE"},
    "skin": _PLAIN_OPCODES,
}


class LegacyFormatError(SchemaError):
    """Dado legado recusado (``path`` sempre vazio; ``code`` diz o motivo, sem o valor)."""


def _error(code: str) -> LegacyFormatError:
    return LegacyFormatError("", code)


# ============================================================================ 1. envelope


def _from_base64(text: str, limit: int) -> bytes:
    if len(text) > 4 * ((limit + 2) // 3):
        raise _error(TOO_BIG)
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise _error(ENVELOPE) from None


def _inflate(data: bytes, limit: int) -> bytes:
    if len(data) > limit:
        raise _error(TOO_BIG)
    stream = zlib.decompressobj()
    try:
        content = stream.decompress(data, limit + 1)
    except zlib.error:
        raise _error(ENVELOPE) from None
    if len(content) > limit or stream.unconsumed_tail:
        raise _error(TOO_BIG)
    if not stream.eof or stream.unused_data:
        raise _error(ENVELOPE)
    return content


def _open_envelope(raw: Any, kind: str) -> bytes:
    """Os bytes do pickle: skin = base64 sem zlib; sessão = zlib (disco) ou base64 de zlib (Mongo); fila = zlib."""
    limit = MAX_RAW[kind]
    if kind == "skin":
        if type(raw) is not str:
            raise _error(TYPE)
        data = _from_base64(raw, limit)
        if len(data) > limit:
            raise _error(TOO_BIG)
        return data
    if kind == "session" and type(raw) is str:
        raw = _from_base64(raw, limit)
    elif type(raw) is not bytes:
        raise _error(TYPE)
    return _inflate(raw, limit)


# ============================================================================ 2. pré-varredura (pilha, marcas e memo simulados)


class _Global(NamedTuple):
    module: str
    name: str


class _Tuple:
    """Tupla da pilha simulada: só carrega a profundidade de tuplas encadeadas."""

    __slots__ = ("depth",)

    def __init__(self, depth: int):
        self.depth = depth


_MUTABLE = object()  # lista, dicionário ou conjunto na pilha simulada: não serve de chave nem de item de conjunto


class _Simulation:
    """Espelha a pilha do ``Unpickler`` só no que importa: textos (para ``STACK_GLOBAL``), marcas e memo.

    Cada operação respeita a *fence* (a última ``MARK``): quem desce abaixo dela é corrupção, como no ``Unpickler`` real.
    """

    __slots__ = ("allowed", "stack", "marks", "memo", "set_items", "deques", "bad_key")

    def __init__(self, allowed: frozenset):
        self.allowed = allowed
        self.stack: list = []
        self.marks: list[int] = []
        self.memo: list = []
        self.set_items = 0
        self.deques = 0
        self.bad_key = False

    def need(self, count: int) -> None:
        """Há ``count`` itens acima da última marca?"""
        fence = self.marks[-1] if self.marks else 0
        if len(self.stack) - fence < count:
            raise _error(CORRUPT)

    def drop(self, count: int) -> None:
        self.need(count)
        del self.stack[len(self.stack) - count :]

    def push_opaque(self, _arg: Any) -> None:
        self.stack.append(None)

    def push_mutable(self, _arg: Any) -> None:
        self.stack.append(_MUTABLE)

    def push_text(self, arg: str) -> None:
        self.stack.append(arg)

    def nothing(self, _arg: Any) -> None:
        pass

    def memoize(self, _arg: Any) -> None:
        self.need(1)
        self.memo.append(self.stack[-1])

    def memo_get(self, index: int) -> None:
        if not 0 <= index < len(self.memo):
            raise _error(CORRUPT)
        self.stack.append(self.memo[index])

    def mark(self, _arg: Any) -> None:
        self.marks.append(len(self.stack))
        if len(self.marks) > MAX_MARK_DEPTH:
            raise _error(MARK_LIMIT)

    def drop_one(self, _arg: Any) -> None:
        self.need(2)  # o contêiner e o item
        self.drop(1)

    def drop_two(self, _arg: Any) -> None:
        self.need(3)  # o dicionário, a chave e o valor
        self.check_keys([self.stack[-2]])
        self.drop(2)

    def check_keys(self, keys: list) -> None:
        """Chave de dicionário só pode ser texto (é o que o documento aceita). Recusa já na pré-varredura, sem deixar
        o ``Unpickler`` montar chaves de outros tipos; o erro sai no fim, para não mascarar corrupção anterior."""
        for key in keys:
            if key is _MUTABLE:
                raise _error(CORRUPT)  # não hashável: o ``Unpickler`` real também falharia
            if type(key) is not str:
                self.bad_key = True

    def close_mark(self) -> int:
        """Fecha a última marca e devolve a base; exige o contêiner logo abaixo dela."""
        if not self.marks:
            raise _error(CORRUPT)
        base = self.marks.pop()
        if base <= (self.marks[-1] if self.marks else 0):
            raise _error(CORRUPT)
        return base

    def appends(self, _arg: Any) -> None:
        del self.stack[self.close_mark() :]

    def setitems(self, _arg: Any) -> None:
        base = self.close_mark()
        self.check_keys(self.stack[base::2])
        del self.stack[base:]

    def additems(self, _arg: Any) -> None:
        base = self.close_mark()
        self.set_items += len(self.stack) - base
        if self.set_items > MAX_SET_ITEMS:
            raise _error(SET_LIMIT)
        del self.stack[base:]

    def tuple_of(self, count: int) -> Callable[[Any], None]:
        def build(_arg: Any) -> None:
            self.need(count)
            items = self.stack[-count:]
            depth = 1 + max((item.depth for item in items if type(item) is _Tuple), default=0)
            if depth > MAX_TUPLE_DEPTH:
                raise _error(DEPTH)
            del self.stack[-count:]
            self.stack.append(_Tuple(depth))

        return build

    def stack_global(self, _arg: Any) -> None:
        self.need(2)
        module, name = self.stack[-2], self.stack[-1]
        if type(module) is not str or type(name) is not str or (module, name) not in self.allowed:
            raise _error(GLOBAL)
        self.drop(2)
        self.stack.append(_Global(module, name))

    def reduce(self, _arg: Any) -> None:
        self.need(2)
        target = self.stack[-2]
        if type(target) is not _Global:
            raise _error(CORRUPT)
        if target.name == "deque":
            self.deques += 1
            if self.deques > MAX_DEQUES:
                raise _error(OPCODE_LIMIT)
        self.drop(2)
        self.stack.append(None)

    def handlers(self) -> dict[str, Callable[[Any], None]]:
        table = dict.fromkeys(
            "NONE NEWTRUE NEWFALSE BININT BININT1 BININT2 LONG1 BINFLOAT BINBYTES SHORT_BINBYTES EMPTY_TUPLE".split(),
            self.push_opaque,
        )
        table.update(dict.fromkeys(("EMPTY_LIST", "EMPTY_DICT", "EMPTY_SET"), self.push_mutable))
        table.update(dict.fromkeys(("SHORT_BINUNICODE", "BINUNICODE"), self.push_text))
        table.update(dict.fromkeys(("PROTO", "FRAME"), self.nothing))
        table.update(dict.fromkeys(("BINGET", "LONG_BINGET"), self.memo_get))
        table.update(
            MEMOIZE=self.memoize,
            MARK=self.mark,
            APPEND=self.drop_one,
            SETITEM=self.drop_two,
            APPENDS=self.appends,
            SETITEMS=self.setitems,
            ADDITEMS=self.additems,
            TUPLE1=self.tuple_of(1),
            TUPLE2=self.tuple_of(2),
            TUPLE3=self.tuple_of(3),
            STACK_GLOBAL=self.stack_global,
            REDUCE=self.reduce,
        )
        return table


def _prescan(data: bytes, kind: str) -> None:
    """Recusa o que não for um pickle de protocolo 4 ou 5 só com opcodes, globais e quantidades permitidos."""
    simulation = _Simulation(ALLOWED_GLOBALS[kind])
    handlers = simulation.handlers()
    permitted = _OPCODES[kind]
    limit = MAX_OPCODES[kind]
    count = 0
    end = None
    try:
        for opcode, arg, position in pickletools.genops(data):
            name = opcode.name
            if count == 0:
                if name != "PROTO" or arg not in PROTOCOLS:
                    raise _error(PROTOCOL)
            elif name == "PROTO":
                raise _error(PROTOCOL)  # a versão só vale no primeiro opcode
            count += 1
            if count > limit:
                raise _error(OPCODE_LIMIT)
            if name not in permitted:
                raise _error(OPCODE)
            if name == "STOP":
                simulation.need(1)
                end = position + 1
                break
            handlers[name](arg)
    except LegacyFormatError:
        raise
    except Exception:
        raise _error(CORRUPT) from None
    if end != len(data):
        raise _error(CORRUPT)
    if simulation.bad_key:
        raise _error(KEY_NOT_TEXT)


# ============================================================================ 3. Unpickler restrito


class _RestrictedUnpickler(pickle.Unpickler):
    def __init__(self, file: io.BytesIO, allowed: frozenset):
        super().__init__(file, fix_imports=False, encoding="ascii", errors="strict", buffers=None)
        self._allowed = allowed

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) in self._allowed and (module, name) in _CLASSES:
            return _CLASSES[(module, name)]
        raise pickle.UnpicklingError("global fora da allowlist")

    def persistent_load(self, pid: Any) -> Any:
        raise pickle.UnpicklingError("id persistente recusado")


def _unpickle(data: bytes, kind: str) -> Any:
    try:
        return _RestrictedUnpickler(io.BytesIO(data), ALLOWED_GLOBALS[kind]).load()
    except Exception:  # UnpicklingError, EOFError, ValueError, OverflowError, RecursionError, MemoryError...
        raise _error(CORRUPT) from None


# ============================================================================ porta de entrada


def load_legacy(raw: bytes | str, kind: str) -> dict:
    """Lê um documento legado (``session``, ``queue`` ou ``skin``) e devolve o ``dict`` validado, ou levanta
    ``LegacyFormatError``. Só aqui o ``pickle`` roda, e só depois do envelope e da pré-varredura."""
    if kind not in MAX_RAW:
        raise ValueError("kind desconhecido")
    data = _open_envelope(raw, kind)
    _prescan(data, kind)
    document = _unpickle(data, kind)
    if type(document) is not dict:
        raise _error(TYPE)
    try:
        return check_structure(document)
    except SchemaError as error:
        raise _error(error.code) from None

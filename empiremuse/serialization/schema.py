"""Mini-validador declarativo para documentos JSON e validação estrutural iterativa.

Todo erro é um ``SchemaError(path, code)``: o ``code`` é um texto curto e estável, o ``path`` aponta o campo do esquema
(``""`` na raiz, ``queue[3].uri``) e nenhum dos dois leva o VALOR recusado. Os validadores devolvem uma cópia limpa do dado
(a entrada nunca é alterada) e só aceitam o tipo exato (``bool`` não vale como ``int``; subclasses são recusadas).

A varredura de campo livre (``Any_JSON``) e a do documento legado (``check_structure``) usam pilha explícita de iteradores,
sem recursão, e contam VISITAS (uma referência compartilhada conta a cada vez que é visitada).
"""

from __future__ import annotations

import copy
import logging
import math
import re
import unicodedata
from collections import deque
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Códigos de ``SchemaError.code``.
TYPE = "type"
RANGE = "range"
LENGTH = "length"
PATTERN = "pattern"
MISSING = "missing"
UNKNOWN_FIELD = "unknown_field"
KEY_NOT_TEXT = "key_not_text"
DUPLICATE_KEY = "duplicate_key"
SURROGATE = "surrogate"
CONTROL = "control"
NOT_FINITE = "not_finite"
DEPTH = "depth"
NODES = "nodes"
TOO_BIG = "too_big"
SYNTAX = "syntax"
ENCODING = "encoding"
ENVELOPE = "envelope"
NUMBER = "number"
VERSION = "version"

# Campo livre: profundidade contada a partir do valor do campo. Documento legado: contada da raiz (DE-4).
FIELD_MAX_DEPTH = 8
FIELD_MAX_NODES = 5_000
STRUCTURE_MAX_DEPTH = 12
STRUCTURE_MAX_NODES = 2_000_000

_SURROGATE = re.compile("[\ud800-\udfff]")
_CONTROL_CATEGORIES = frozenset({"Cc", "Cf"})
_LINE_CONTROLS = frozenset("\n\r\t")
_LONG_TEXT = 256  # acima disso o texto é verificado uma vez só por objeto durante a varredura

_PLAIN = frozenset({type(None), bool, int})
_JSON_CONTAINERS = frozenset({list, dict})
_LEGACY_PLAIN = _PLAIN | {datetime}
_LEGACY_CONTAINERS = frozenset({list, dict, tuple, set, deque})
_END = object()


class SchemaError(ValueError):
    """Dado recusado: ``path`` aponta o campo e ``code`` diz o motivo; nunca leva o valor."""

    def __init__(self, path: str, code: str):
        super().__init__(path, code)  # ``args`` = (path, code): é o que ``copy`` e ``pickle`` usam para reconstruir
        self.path = path
        self.code = code

    def __str__(self) -> str:
        return f"{self.code} em {self.path or '<raiz>'}"


# ============================================================================ varredura iterativa


def _check_text(text: str, path: str, seen: set) -> None:
    """Sem surrogate solto. Texto longo é verificado uma vez só por objeto (a mesma referência pode aparecer muitas vezes)."""
    if len(text) > _LONG_TEXT:
        identity = id(text)
        if identity in seen:
            return
        seen.add(identity)
    if _SURROGATE.search(text):
        raise SchemaError(path, SURROGATE)


def _check_keys(mapping: dict, path: str, seen: set) -> None:
    for key in mapping:
        if type(key) is not str:
            raise SchemaError(path, KEY_NOT_TEXT)
        _check_text(key, path, seen)


def _check_scalar(value: Any, kind: type, plain: frozenset, path: str, seen: set) -> None:
    if kind in plain:
        return
    if kind is str:
        _check_text(value, path, seen)
    elif kind is float:
        if not math.isfinite(value):
            raise SchemaError(path, NOT_FINITE)
    else:
        raise SchemaError(path, TYPE)


def _next_value(stack: list) -> Any:
    while stack:
        try:
            return next(stack[-1])
        except StopIteration:
            stack.pop()
    return _END


def scan(root: Any, path: str, max_depth: int, max_nodes: int, legacy: bool) -> None:
    """Valida ``root`` sem recursão: tipos exatos, chaves ``str``, números finitos, sem surrogate solto e sob os tetos.

    A memória é proporcional à profundidade (pilha de iteradores), e o tamanho de cada contêiner é conferido contra o
    teto de nós ANTES de os filhos serem percorridos.
    """
    containers = _LEGACY_CONTAINERS if legacy else _JSON_CONTAINERS
    plain = _LEGACY_PLAIN if legacy else _PLAIN
    visits = 1
    seen: set = set()
    stack: list = []
    value = root
    while value is not _END:
        kind = type(value)
        if kind in containers:
            if len(stack) >= max_depth:
                raise SchemaError(path, DEPTH)
            visits += len(value)
            if visits > max_nodes:
                raise SchemaError(path, NODES)
            if kind is dict:
                _check_keys(value, path, seen)
                stack.append(iter(value.values()))
            else:
                stack.append(iter(value))
        else:
            _check_scalar(value, kind, plain, path, seen)
        value = _next_value(stack)


def _copy_json(value: Any) -> Any:
    """Cópia profunda de um valor JÁ varrido (profundidade e nós limitados, portanto a recursão é curta)."""
    kind = type(value)
    if kind is list:
        return [_copy_json(item) for item in value]
    if kind is dict:
        return {key: _copy_json(item) for key, item in value.items()}
    return value


def check_structure(value: Any, *, max_depth: int = STRUCTURE_MAX_DEPTH, max_nodes: int = STRUCTURE_MAX_NODES) -> Any:
    """Validação genérica do documento legado inteiro (JSON + ``tuple``, ``set``, ``deque`` e ``datetime``); devolve ``value``."""
    scan(value, "", max_depth, max_nodes, legacy=True)
    return value


# ============================================================================ tipos do esquema


class _Schema:
    __slots__ = ()

    def check(self, value: Any, path: str) -> Any:
        raise NotImplementedError


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _has_control(text: str, multiline: bool) -> bool:
    for char in text:
        if unicodedata.category(char) in _CONTROL_CATEGORIES and not (multiline and char in _LINE_CONTROLS):
            return True
    return False


class Str(_Schema):
    """Texto: sem surrogate solto nem ``Cc``/``Cf`` (``multiline`` libera só ``\\n``, ``\\r`` e ``\\t``)."""

    __slots__ = ("max_len", "min_len", "multiline", "_pattern")

    def __init__(self, max_len: int, *, min_len: int = 0, pattern: str | None = None, multiline: bool = False):
        self.max_len = max_len
        self.min_len = min_len
        self.multiline = multiline
        self._pattern = re.compile(pattern) if pattern is not None else None

    def check(self, value: Any, path: str) -> str:
        if type(value) is not str:
            raise SchemaError(path, TYPE)
        if not self.min_len <= len(value) <= self.max_len:
            raise SchemaError(path, LENGTH)
        if _SURROGATE.search(value):
            raise SchemaError(path, SURROGATE)
        if _has_control(value, self.multiline):
            raise SchemaError(path, CONTROL)
        if self._pattern is not None and not self._pattern.fullmatch(value):
            raise SchemaError(path, PATTERN)
        return value


class Int(_Schema):
    """Inteiro exato (``bool`` não vale), com limites inclusivos opcionais."""

    __slots__ = ("min", "max")

    def __init__(self, min: int | None = None, max: int | None = None):
        self.min = min
        self.max = max

    def check(self, value: Any, path: str) -> int:
        if type(value) is not int:
            raise SchemaError(path, TYPE)
        if (self.min is not None and value < self.min) or (self.max is not None and value > self.max):
            raise SchemaError(path, RANGE)
        return value


SNOWFLAKE = Int(0, 2**63 - 1)


class Float(_Schema):
    """``int`` ou ``float`` finito (``bool`` não vale); devolve ``float``."""

    __slots__ = ("min", "max")

    def __init__(self, min: float | None = None, max: float | None = None):
        self.min = min
        self.max = max

    def check(self, value: Any, path: str) -> float:
        kind = type(value)
        if kind is float:
            number = value
        elif kind is int:
            try:
                number = float(value)
            except OverflowError:
                raise SchemaError(path, RANGE) from None
        else:
            raise SchemaError(path, TYPE)
        if not math.isfinite(number):
            raise SchemaError(path, NOT_FINITE)
        if (self.min is not None and number < self.min) or (self.max is not None and number > self.max):
            raise SchemaError(path, RANGE)
        return number


class Bool(_Schema):
    __slots__ = ()

    def check(self, value: Any, path: str) -> bool:
        if type(value) is not bool:
            raise SchemaError(path, TYPE)
        return value


class List(_Schema):
    """Lista de itens do mesmo esquema; o tamanho é conferido antes de validar os itens."""

    __slots__ = ("item", "max_items", "min_items")

    def __init__(self, item: _Schema, max_items: int, min_items: int = 0):
        self.item = item
        self.max_items = max_items
        self.min_items = min_items

    def check(self, value: Any, path: str) -> list:
        if type(value) is not list:
            raise SchemaError(path, TYPE)
        if not self.min_items <= len(value) <= self.max_items:
            raise SchemaError(path, LENGTH)
        return [self.item.check(item, f"{path}[{index}]") for index, item in enumerate(value)]


class Optional(_Schema):
    """Campo que pode faltar (vira ``default``) ou ser ``None``."""

    __slots__ = ("inner", "default")

    def __init__(self, inner: _Schema, default: Any = None):
        self.inner = inner
        self.default = default

    def check(self, value: Any, path: str) -> Any:
        return None if value is None else self.inner.check(value, path)

    def default_value(self) -> Any:
        return copy.deepcopy(self.default)


class Any_JSON(_Schema):  # noqa: N801 - nome fixado pelo plano da F3-6b
    """Campo livre: só tipos do JSON, com tetos de profundidade e de nós; recusa só surrogate solto no texto."""

    __slots__ = ("max_depth", "max_nodes")

    def __init__(self, max_depth: int = FIELD_MAX_DEPTH, max_nodes: int = FIELD_MAX_NODES):
        self.max_depth = max_depth
        self.max_nodes = max_nodes

    def check(self, value: Any, path: str) -> Any:
        scan(value, path, self.max_depth, self.max_nodes, legacy=False)
        return _copy_json(value)


_EXTRA_MODES = ("drop", "keep", "error")


class Dict(_Schema):
    """Objeto com campos conhecidos; ``extra`` define o destino dos desconhecidos: ``drop``, ``keep`` ou ``error``."""

    __slots__ = ("fields", "extra")

    def __init__(self, fields: dict[str, _Schema], extra: str = "drop"):
        if extra not in _EXTRA_MODES:
            raise ValueError(f"extra deve ser um de {_EXTRA_MODES}")
        self.fields = dict(fields)
        self.extra = extra

    def check(self, value: Any, path: str) -> dict:
        if type(value) is not dict:
            raise SchemaError(path, TYPE)
        for key in value:
            if type(key) is not str:
                raise SchemaError(path, KEY_NOT_TEXT)
        unknown = [key for key in value if key not in self.fields]
        if unknown and self.extra == "error":
            raise SchemaError(path, UNKNOWN_FIELD)
        result = {name: self._field(name, field, value, path) for name, field in self.fields.items()}
        if unknown and self.extra == "keep":
            result.update(self._keep(unknown, value, path))
        elif unknown:
            logger.warning("Campos desconhecidos descartados: %d em %s", len(unknown), path or "<raiz>")
        return result

    @staticmethod
    def _field(name: str, field: _Schema, value: dict, path: str) -> Any:
        if name in value:
            return field.check(value[name], _join(path, name))
        if isinstance(field, Optional):
            return field.default_value()
        raise SchemaError(_join(path, name), MISSING)

    @staticmethod
    def _keep(unknown: list[str], value: dict, path: str) -> dict:
        free = Any_JSON()
        kept = {}
        for key in unknown:
            if _SURROGATE.search(key):
                raise SchemaError(path, SURROGATE)
            kept[key] = free.check(value[key], path)
        return kept


def validate(schema: _Schema, value: Any) -> Any:
    """Valida ``value`` contra ``schema`` e devolve o dado limpo, ou levanta ``SchemaError``."""
    return schema.check(value, "")

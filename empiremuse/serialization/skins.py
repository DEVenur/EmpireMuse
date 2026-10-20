"""Esquema da skin personalizada (v1, sem campo ``v``): o dicionário que o editor monta e o ``skin_converter`` consome.

``validate_skin`` é a porta de TUDO que vira dicionário no documento do servidor: o que o editor salva, o que a migração lê do
texto legado e o que já estava gravado. Devolve uma cópia nova e limpa, NUNCA acrescenta chave que a entrada não tinha (o
``skin_converter`` trata chave ausente e ``None`` de jeitos diferentes), descarta em silêncio o que não conhece e levanta
``SchemaError(path, code)`` sem o valor. Texto livre aceita ``Cf`` (emoji composto, campo "em branco") e recusa ``Cc``, menos
quebra de linha e tabulação. Teto de 100 KiB por skin; nome da skin e quantidade por modo são conferidos ao salvar.
"""

from __future__ import annotations

from typing import Any

from .codec import dumps
from .schema import (
    OMIT,
    TOO_BIG,
    TYPE,
    Bool,
    Dict,
    Int,
    List,
    Optional,
    SchemaError,
    Str,
    _Schema,
    validate,
)

MAX_BYTES = 100 * 1024
MAX_SKINS_PER_MODE = 25
MAX_NAME = 64
MAX_QUEUE_ENTRIES = 25
MAX_EMBEDS = 10
MAX_FIELDS = 25
MAX_URL = 2048
MAX_COLOR_TEXT = 64
MAX_COLOR_NUMBER = 0xFFFFFF


def _text(max_len: int) -> Str:
    return Str(max_len, multiline=True, allow_format=True)


def _optional(inner: _Schema) -> Optional:
    return Optional(inner, default=OMIT)


class _Color(_Schema):
    """Cor do embed: número de 0 a 0xFFFFFF ou texto (hexadecimal, com ``#`` ou um placeholder como ``{guild.color}``)."""

    __slots__ = ()
    _NUMBER = Int(0, MAX_COLOR_NUMBER)
    _TEXT = Str(MAX_COLOR_TEXT)

    def check(self, value: Any, path: str) -> Any:
        if type(value) is int:
            return self._NUMBER.check(value, path)
        return self._TEXT.check(value, path)


def _url() -> Optional:
    return _optional(Str(MAX_URL))


_FIELD = Dict({"name": _text(256), "value": _text(1024), "inline": _optional(Bool())}, extra="ignore")
_FOOTER = Dict({"text": _optional(_text(2048)), "icon_url": _url()}, extra="ignore")
_AUTHOR = Dict({"name": _optional(_text(256)), "url": _url(), "icon_url": _url()}, extra="ignore")
_IMAGE = Dict({"url": _url()}, extra="ignore")
_EMBED = Dict(
    {
        "title": _optional(_text(256)),
        "description": _optional(_text(4096)),
        "color": _optional(_Color()),
        "fields": _optional(List(_FIELD, MAX_FIELDS)),
        "footer": _optional(_FOOTER),
        "author": _optional(_AUTHOR),
        "image": _optional(_IMAGE),
        "thumbnail": _optional(_IMAGE),
    },
    extra="ignore",
)
SKIN = Dict(
    {
        "queue_max_entries": _optional(Int(0, MAX_QUEUE_ENTRIES)),
        "queue_format": _optional(_text(500)),
        "content": _optional(_text(4000)),
        "controller_enabled": _optional(Bool()),
        "embeds": _optional(List(_EMBED, MAX_EMBEDS)),
    },
    extra="ignore",
)
_NAME = Str(MAX_NAME, min_len=1, pattern=r"[^.$]+")


def validate_skin(skin: Any) -> dict:
    """A skin validada (cópia limpa) ou ``SchemaError``; mais de 100 KiB em UTF-8 é ``too_big``."""
    clean = validate(SKIN, skin)
    if len(dumps(clean)) > MAX_BYTES:
        raise SchemaError("", TOO_BIG)
    return clean


def validate_skin_name(name: Any) -> str:
    """O nome da skin sem as pontas em branco: 1 a 64 caracteres, sem ``Cc``/``Cf``, sem ``.`` nem ``$``."""
    if type(name) is not str:
        raise SchemaError("skin_name", TYPE)
    return _NAME.check(name.strip(), "skin_name")

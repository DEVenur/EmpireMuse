"""A faixa (o ``info`` que o player guarda) nos documentos JSON: esquema comum da fila salva e da sessão do player.

Os campos conhecidos são validados quando existem e os desconhecidos são mantidos como JSON livre com teto (cada versão do
Lavalink traz os seus). Texto de faixa vem de fora do bot, então aceita ``Cc``/``Cf`` (emoji de ZWJ, marcas bidirecionais) e só
recusa surrogate solto; o escape fica com quem exibe. A régua das URLs fica com quem decide (a sessão, ver ``session.py``).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from . import schema
from .schema import (
    SNOWFLAKE,
    Any_JSON,
    Bool,
    Dict,
    Float,
    OneOf,
    Optional,
    SchemaError,
    Str,
)

MAX_TEXT = 2_048
MAX_ENCODED_TRACK = 16_384

BASE64 = r"[A-Za-z0-9+/]*={0,2}"


def text(max_len: int = MAX_TEXT) -> Str:
    return Str(max_len, allow_controls=True)


def optional(inner: schema._Schema) -> Optional:
    return Optional(inner, default=schema.OMIT)


TRACK = Dict(
    {
        "title": text(),
        "sourceName": text(256),
        "author": optional(text()),
        "uri": optional(text()),
        "identifier": optional(text()),
        "artworkUrl": optional(text()),
        "isrc": optional(text(64)),
        "length": optional(Float(min=0)),
        "position": optional(Float(min=0)),
        "isStream": optional(Bool()),
        "isSeekable": optional(Bool()),
        "is_partial": optional(Bool()),
        "id": optional(Str(MAX_ENCODED_TRACK, pattern=BASE64)),
        "playlist": optional(Dict({"name": text(), "url": text()}, extra="keep")),
        "pluginInfo": optional(Any_JSON()),
        "extra": Dict({"requester": OneOf(SNOWFLAKE, text(256))}, extra="keep"),
    },
    extra="keep",
)


def clean_track(info: Any, path: str) -> dict:
    """A faixa validada; se a letra for o problema, a faixa fica sem ela (a letra se busca de novo)."""
    try:
        return TRACK.check(info, path)
    except SchemaError:
        extra = info.get("extra") if type(info) is dict else None
        if type(extra) is not dict or "lyrics" not in extra:
            raise
        reduced = {**info, "extra": {key: value for key, value in extra.items() if key != "lyrics"}}
        return TRACK.check(reduced, path)


def plain(value: Any) -> Any:
    """Tupla e ``deque`` viram lista (o legado já passou por ``check_structure``, então a recursão é curta)."""
    kind = type(value)
    if kind is list or kind is tuple or kind is deque:
        return [plain(item) for item in value]
    if kind is dict:
        return {key: plain(item) for key, item in value.items()}
    return value

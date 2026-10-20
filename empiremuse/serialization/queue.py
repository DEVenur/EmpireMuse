"""Fila salva do usuário em JSON (v1): ``{"v": 1, "tracks": [faixa...], "created_at": ISO com offset, "guild_id": int}``.

Até 5 000 faixas e 4 MiB. A faixa é o ``info`` que o player já guarda: os campos conhecidos são validados quando existem e os
desconhecidos são mantidos como JSON livre com teto (cada versão do Lavalink traz os seus). Texto de faixa vem de fora do
bot, então aceita ``Cc``/``Cf`` (emoji de ZWJ, marcas bidirecionais) e só recusa surrogate solto; o escape fica com quem exibe.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

from . import schema
from .codec import dumps, loads_bounded
from .schema import (
    LENGTH,
    MISSING,
    PATTERN,
    RANGE,
    SNOWFLAKE,
    TOO_BIG,
    TYPE,
    Any_JSON,
    Bool,
    Dict,
    Float,
    Int,
    List,
    OneOf,
    Optional,
    SchemaError,
    Str,
)

VERSION = 1
MAX_TRACKS = 5_000
MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT = 2_048
MAX_ENCODED_TRACK = 16_384

_BASE64 = r"[A-Za-z0-9+/]*={0,2}"
_ISO_WITH_OFFSET = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?([+-][0-9]{2}:[0-9]{2})"


def _text(max_len: int = MAX_TEXT) -> Str:
    return Str(max_len, allow_controls=True)


def _optional(inner: schema._Schema) -> Optional:
    return Optional(inner, default=schema.OMIT)


TRACK = Dict(
    {
        "title": _text(),
        "sourceName": _text(256),
        "author": _optional(_text()),
        "uri": _optional(_text()),
        "identifier": _optional(_text()),
        "artworkUrl": _optional(_text()),
        "isrc": _optional(_text(64)),
        "length": _optional(Float(min=0)),
        "position": _optional(Float(min=0)),
        "isStream": _optional(Bool()),
        "isSeekable": _optional(Bool()),
        "is_partial": _optional(Bool()),
        "id": _optional(Str(MAX_ENCODED_TRACK, pattern=_BASE64)),
        "playlist": _optional(Dict({"name": _text(), "url": _text()}, extra="keep")),
        "pluginInfo": _optional(Any_JSON()),
        "extra": Dict({"requester": OneOf(SNOWFLAKE, _text(256))}, extra="keep"),
    },
    extra="keep",
)

DOCUMENT = Dict(
    {
        "v": Int(VERSION, VERSION),
        "tracks": List(TRACK, MAX_TRACKS, min_items=1),
        "created_at": Str(64, pattern=_ISO_WITH_OFFSET),
        "guild_id": SNOWFLAKE,
    }
)


def _clean_track(info: Any, index: int) -> dict:
    """A faixa validada; se a letra for o problema, a faixa é salva sem ela (a letra se busca de novo)."""
    path = f"tracks[{index}]"
    try:
        return TRACK.check(info, path)
    except SchemaError:
        extra = info.get("extra") if type(info) is dict else None
        if type(extra) is not dict or "lyrics" not in extra:
            raise
        reduced = {**info, "extra": {key: value for key, value in extra.items() if key != "lyrics"}}
        return TRACK.check(reduced, path)


def _format_date(created_at: Any) -> str:
    if type(created_at) is not datetime or created_at.tzinfo is None:
        raise SchemaError("created_at", TYPE)
    try:
        return created_at.astimezone(timezone.utc).isoformat()
    except OverflowError:  # perto de 0001-01-01 ou 9999-12-31 com offset: não cabe em UTC
        raise SchemaError("created_at", RANGE) from None


def _parse_date(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        raise SchemaError("created_at", PATTERN) from None
    except OverflowError:
        raise SchemaError("created_at", RANGE) from None


def encode_saved_queue(tracks: list, created_at: datetime, guild_id: int) -> bytes:
    """O JSON da fila (UTF-8 compacto) ou ``SchemaError`` com o caminho do campo ruim, nunca o valor."""
    if type(tracks) is not list or not 1 <= len(tracks) <= MAX_TRACKS:
        raise SchemaError("tracks", LENGTH)
    document = {
        "v": VERSION,
        "tracks": [_clean_track(info, index) for index, info in enumerate(tracks)],
        "created_at": _format_date(created_at),
        "guild_id": SNOWFLAKE.check(guild_id, "guild_id"),
    }
    raw = dumps(document)
    if len(raw) > MAX_BYTES:
        raise SchemaError("", TOO_BIG)
    return raw


def decode_saved_queue(raw: bytes) -> dict:
    """``{"tracks", "created_at" (datetime UTC), "guild_id"}`` validado, ou ``SchemaError``."""
    document = schema.validate(DOCUMENT, loads_bounded(raw, max_bytes=MAX_BYTES, version=VERSION))
    document["created_at"] = _parse_date(document["created_at"])
    del document["v"]
    return document


def _plain(value: Any) -> Any:
    """Tupla e ``deque`` viram lista (o legado já passou por ``check_structure``, então a recursão é curta)."""
    kind = type(value)
    if kind is list or kind is tuple or kind is deque:
        return [_plain(item) for item in value]
    if kind is dict:
        return {key: _plain(item) for key, item in value.items()}
    return value


def normalize_legacy_queue(document: dict) -> dict:
    """Converte o documento lido do ``.pkl`` antigo para o mesmo formato de ``decode_saved_queue`` (e o revalida)."""
    for name in ("tracks", "created_at", "guild_id"):
        if name not in document:
            raise SchemaError(name, MISSING)
    created_at = document["created_at"]
    if type(created_at) is datetime and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return decode_saved_queue(encode_saved_queue(_plain(document["tracks"]), created_at, document["guild_id"]))

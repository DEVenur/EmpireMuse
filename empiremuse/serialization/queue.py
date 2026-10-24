"""Fila salva do usuário em JSON (v1): ``{"v": 1, "tracks": [faixa...], "created_at": ISO com offset, "guild_id": int}``.

Até 5 000 faixas e 4 MiB. A faixa é o ``info`` que o player já guarda: os campos conhecidos são validados quando existem e os
desconhecidos são mantidos como JSON livre com teto (cada versão do Lavalink traz os seus). Texto de faixa vem de fora do
bot, então aceita ``Cc``/``Cf`` (emoji de ZWJ, marcas bidirecionais) e só recusa surrogate solto; o escape fica com quem exibe.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .codec import dumps, loads_bounded
from .schema import (
    LENGTH,
    PATTERN,
    RANGE,
    SNOWFLAKE,
    TOO_BIG,
    TYPE,
    Dict,
    Int,
    List,
    SchemaError,
    Str,
    validate,
)
from .tracks import TRACK, clean_track

VERSION = 1
MAX_TRACKS = 5_000
MAX_BYTES = 4 * 1024 * 1024
_ISO_WITH_OFFSET = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?([+-][0-9]{2}:[0-9]{2})"


DOCUMENT = Dict(
    {
        "v": Int(VERSION, VERSION),
        "tracks": List(TRACK, MAX_TRACKS, min_items=1),
        "created_at": Str(64, pattern=_ISO_WITH_OFFSET),
        "guild_id": SNOWFLAKE,
    }
)


def _clean_track(info: Any, index: int) -> dict:
    return clean_track(info, f"tracks[{index}]")


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
    document = validate(DOCUMENT, loads_bounded(raw, max_bytes=MAX_BYTES, version=VERSION))
    document["created_at"] = _parse_date(document["created_at"])
    del document["v"]
    return document

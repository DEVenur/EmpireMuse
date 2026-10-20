"""Caches em disco (playlist e Last.fm) em JSON (v1): ``{"v": 1, "saved_at": epoch, "items": [{"k": texto, "d": JSON}]}``.

Cache não é dado do usuário: o que não vale é descartado, nunca recusado por inteiro. Item com chave ou valor inválido (tipo
fora do JSON, número não finito, surrogate solto, fundo demais) sai sozinho na gravação e na leitura; o arquivo mais velho que
o TTL do cache, ou com data no futuro, não volta. Tetos: playlist 64 MiB e Last.fm 4 MiB.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from .codec import dumps, loads_bounded
from .schema import MISSING, RANGE, TYPE, SchemaError, check_structure

logger = logging.getLogger(__name__)

VERSION = 1
PLAYLIST_MAX_BYTES = 64 * 1024 * 1024
LASTFM_MAX_BYTES = 4 * 1024 * 1024
MAX_KEY = 512
MAX_ITEM_DEPTH = 16
MAX_ITEM_NODES = 2_000_000
CLOCK_TOLERANCE = 60  # segundos de folga para um relógio ligeiramente adiantado
MAX_SAVED_AT = (
    253_402_300_799  # 9999-12-31T23:59:59Z: acima disso não é um instante (e a conta com ``time.time()`` estoura)
)

_HEAD = b'{"v":%d,"saved_at":%s,"items":['
_TAIL = b"]}"


def _encode_item(key: Any, value: Any) -> bytes | None:
    """O JSON do item, ou ``None`` se ele não vale (chave que não é texto curto, valor fora do JSON ou fundo demais)."""
    if type(key) is not str or len(key) > MAX_KEY:
        return None
    try:
        piece = dumps({"k": key, "d": value})
        check_structure(value, max_depth=MAX_ITEM_DEPTH, max_nodes=MAX_ITEM_NODES)
    except SchemaError:
        return None
    return piece


def _check_saved_at(saved_at: Any) -> None:
    """Instante entre 0 e 9999-12-31 (a comparação vem ANTES de qualquer conta, que estouraria com um inteiro enorme)."""
    if type(saved_at) not in (int, float):
        raise SchemaError("saved_at", TYPE)
    if not 0 <= saved_at <= MAX_SAVED_AT:
        raise SchemaError("saved_at", RANGE)


def encode_cache(items: Iterable[tuple[Any, Any]], *, max_bytes: int, saved_at: float | None = None) -> bytes:
    """O JSON do cache com até ``max_bytes`` bytes; item inválido é descartado e, ao estourar o teto, os últimos saem."""
    saved_at = time.time() if saved_at is None else saved_at
    _check_saved_at(saved_at)
    head = _HEAD % (VERSION, dumps(saved_at))
    budget = max_bytes - len(head) - len(_TAIL)
    pieces: list[bytes] = []
    used = dropped = 0
    for key, value in items:
        piece = _encode_item(key, value)
        if piece is None:
            dropped += 1
            continue
        needed = len(piece) + (1 if pieces else 0)
        if used + needed > budget:
            dropped += 1
            break
        pieces.append(piece)
        used += needed
    if dropped:
        logger.warning("Cache gravado sem %d item(ns) que não valiam ou não couberam no teto", dropped)
    return head + b",".join(pieces) + _TAIL


def _decode_item(item: Any) -> tuple[str, Any] | None:
    if type(item) is not dict or "d" not in item:
        return None
    key = item.get("k")
    if type(key) is not str or len(key) > MAX_KEY:
        return None
    try:
        check_structure(item["d"], max_depth=MAX_ITEM_DEPTH, max_nodes=MAX_ITEM_NODES)
    except SchemaError:
        return None
    return key, item["d"]


def decode_cache(raw: bytes, *, max_bytes: int, max_age: float, now: float | None = None) -> dict:
    """``{chave: valor}`` do cache gravado há menos de ``max_age`` segundos, ou ``{}``; documento ruim levanta ``SchemaError``."""
    document = loads_bounded(raw, max_bytes=max_bytes, version=VERSION)
    for name in ("saved_at", "items"):
        if name not in document:
            raise SchemaError(name, MISSING)
    saved_at, items = document["saved_at"], document["items"]
    _check_saved_at(saved_at)
    if type(items) is not list:
        raise SchemaError("items", TYPE)
    now = time.time() if now is None else now
    if now - saved_at >= max_age or saved_at > now + CLOCK_TOLERANCE:
        return {}
    decoded = (_decode_item(item) for item in items)
    return dict(pair for pair in decoded if pair is not None)

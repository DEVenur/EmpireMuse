"""Agregador de avisos e erros repetidos por template em janelas de 60 s (item 7, 3.7).

Compartilhado pelos handlers do root: a decisão da 1ª passagem fica gravada em ``record.empiremuse_emit`` para que
cada registro conte uma única vez (V-L6). Resumos saem fora da trava interna para permitir reentrância nos handlers.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable

AGGREGATE_WINDOW = 60.0
MAX_KEYS = 500
MAX_TEMPLATE_KEY_CHARS = 256

type _AggregateKey = tuple[str, int, str, str | None]


def _normalize_template(raw: object) -> str:
    if isinstance(raw, str):
        return raw[:MAX_TEMPLATE_KEY_CHARS]
    return f"<{type(raw).__qualname__}>"


@dataclasses.dataclass
class _Bucket:
    started_at: float
    first_msg: str
    name: str
    levelno: int
    pathname: str
    lineno: int
    bot: str | None
    guild: int | None
    count: int = 0


class RepeatAggregator(logging.Filter):
    """Agrega registros ``WARNING+`` com mesma chave ``(name, levelno, empiremuse_template, empiremuse_exc_type)``."""

    def __init__(
        self,
        emit: Callable[[logging.LogRecord], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        window: float = AGGREGATE_WINDOW,
        max_keys: int = MAX_KEYS,
    ) -> None:
        super().__init__()
        self._emit = emit
        self._clock = clock
        self._window = window
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._buckets: dict[_AggregateKey, _Bucket] = {}

    def _make_summary(self, bucket: _Bucket) -> logging.LogRecord:
        window_label = int(self._window) if self._window == int(self._window) else self._window
        msg = f"↻ {bucket.first_msg} — repetida {bucket.count}× em {window_label} s"
        summary = logging.LogRecord(
            name=bucket.name,
            level=bucket.levelno,
            pathname=bucket.pathname,
            lineno=bucket.lineno,
            msg=msg,
            args=None,
            exc_info=None,
        )
        summary.bot = bucket.bot
        summary.guild = bucket.guild
        summary.empiremuse_template = msg[:MAX_TEMPLATE_KEY_CHARS]
        summary.empiremuse_exc_type = None
        summary.empiremuse_redacted = True
        summary.empiremuse_emit = True
        return summary

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if hasattr(record, "empiremuse_emit"):
                return bool(record.empiremuse_emit)
            if record.levelno < logging.WARNING:
                record.empiremuse_emit = True
                return True
            raw_template = getattr(record, "empiremuse_template", record.msg)
            template_key = _normalize_template(raw_template)
            if hasattr(record, "empiremuse_template"):
                record.empiremuse_template = template_key
            key: _AggregateKey = (
                record.name,
                record.levelno,
                template_key,
                getattr(record, "empiremuse_exc_type", None),
            )
            to_emit: list[logging.LogRecord] = []
            with self._lock:
                now = self._clock()
                existing = self._buckets.get(key)
                if existing is not None:
                    if now - existing.started_at < self._window:
                        existing.count += 1
                        record.empiremuse_emit = False
                        return False
                    del self._buckets[key]
                    if existing.count > 0:
                        to_emit.append(self._make_summary(existing))
                elif len(self._buckets) >= self._max_keys:
                    expired = [k for k, b in self._buckets.items() if now - b.started_at >= self._window]
                    for k in expired:
                        b = self._buckets.pop(k)
                        if b.count > 0:
                            to_emit.append(self._make_summary(b))
                    if len(self._buckets) >= self._max_keys:
                        oldest_key = next(iter(self._buckets))
                        oldest = self._buckets.pop(oldest_key)
                        if oldest.count > 0:
                            to_emit.append(self._make_summary(oldest))
                self._buckets[key] = _Bucket(
                    started_at=now,
                    first_msg=record.getMessage(),
                    name=record.name,
                    levelno=record.levelno,
                    pathname=record.pathname,
                    lineno=record.lineno,
                    bot=getattr(record, "bot", None),
                    guild=getattr(record, "guild", None),
                )
                record.empiremuse_emit = True
            for summary in to_emit:
                self._emit(summary)
            return True
        except Exception:
            return True

    def tick(self) -> None:
        """Fecha todas as janelas já vencidas e emite seus resumos fora da trava."""
        to_emit: list[logging.LogRecord] = []
        with self._lock:
            now = self._clock()
            expired = [key for key, bucket in self._buckets.items() if now - bucket.started_at >= self._window]
            for key in expired:
                bucket = self._buckets.pop(key)
                if bucket.count > 0:
                    to_emit.append(self._make_summary(bucket))
        for summary in to_emit:
            self._emit(summary)

    def flush(self) -> None:
        """Descarrega todas as contagens pendentes imediatamente fora da trava."""
        to_emit: list[logging.LogRecord] = []
        with self._lock:
            for bucket in self._buckets.values():
                if bucket.count > 0:
                    to_emit.append(self._make_summary(bucket))
            self._buckets.clear()
        for summary in to_emit:
            self._emit(summary)

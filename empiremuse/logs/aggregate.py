"""Agregador de avisos e erros repetidos por template em janelas de 60 s (item 7, 3.7, K8).

Compartilhado pelos handlers do root: a decisão da 1ª passagem fica gravada em ``record.empiremuse_emit`` para que
cada registro conte uma única vez (V-L6). Resumos saem fora da trava interna para permitir reentrância nos handlers.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable

from empiremuse.logs.redact import sanitize_value
from empiremuse.rules.error_code import ERROR_CODE_RE

AGGREGATE_WINDOW = 60.0
MAX_KEYS = 500
MAX_TEMPLATE_KEY_CHARS = 256
MAX_CODED_REPEATS = 50
MAX_AGGREGATE_KEY_CHARS = 64
MAX_EXC_SUMMARY_CHARS = 300

type _AggregateKey = tuple[str, int, str, str | None, str | None, str | None, str | None]


def _normalize_template(raw: object) -> str:
    if isinstance(raw, str):
        return raw[:MAX_TEMPLATE_KEY_CHARS]
    return f"<{type(raw).__qualname__}>"


def _normalize_aggregate_key(raw: object) -> str | None:
    """Chave opcional que o produtor passa em ``extra={"aggregate_key": ...}`` para separar problemas de mesmo template.

    Só ``str`` não vazia (cortada e saneada); outro tipo vale como ausente. Só dado de baixa cardinalidade (identificador de nó, código),
    nunca ID de servidor, canal ou usuário. Nunca é emitida.
    """
    if isinstance(raw, str) and raw:
        return sanitize_value(raw[:MAX_AGGREGATE_KEY_CHARS])
    return None


def _last_exc_line(exc_text: object) -> str:
    if not isinstance(exc_text, str) or not exc_text:
        return ""
    lines = [line for line in exc_text.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][:MAX_EXC_SUMMARY_CHARS]


def _valid_error_code(record: logging.LogRecord) -> str | None:
    code = getattr(record, "error_code", None)
    if isinstance(code, str) and ERROR_CODE_RE.fullmatch(code):
        return code
    return None


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
    first_code: str | None = None
    coded_seen: int = 0
    count: int = 0


class RepeatAggregator(logging.Filter):
    """Agrega registros ``WARNING+`` com mesma chave ``(name, levelno, empiremuse_template, empiremuse_exc_type, empiremuse_tb_fp)``."""

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
        if bucket.first_code is not None:
            msg = (
                f"↻ {bucket.first_msg} — repetida {bucket.count}× em {window_label} s "
                f"(códigos omitidos; traceback igual ao de {bucket.first_code})"
            )
        else:
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
        summary.empiremuse_tb_fp = None
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
            exc_text = getattr(record, "exc_text", None)
            tb_fp = getattr(record, "empiremuse_tb_fp", None)
            template_fp = getattr(record, "empiremuse_template_fp", None)
            aggregate_key = _normalize_aggregate_key(getattr(record, "aggregate_key", None))
            error_code = _valid_error_code(record)
            key: _AggregateKey = (
                record.name,
                record.levelno,
                template_key,
                getattr(record, "empiremuse_exc_type", None),
                tb_fp if isinstance(tb_fp, str) else None,
                template_fp if isinstance(template_fp, str) else None,
                aggregate_key,
            )
            to_emit: list[logging.LogRecord] = []
            with self._lock:
                now = self._clock()
                existing = self._buckets.get(key)
                if existing is not None:
                    if now - existing.started_at < self._window:
                        if error_code is not None:
                            if existing.first_code is None:
                                existing.first_code = error_code
                            if existing.coded_seen < MAX_CODED_REPEATS:
                                existing.coded_seen += 1
                                last_line = _last_exc_line(exc_text)
                                base_msg = record.getMessage()
                                if last_line:
                                    record.msg = (
                                        f"{base_msg} — {last_line} — traceback igual ao de {existing.first_code}"
                                    )
                                else:
                                    record.msg = f"{base_msg} — traceback igual ao de {existing.first_code}"
                                record.args = None
                                record.exc_info = None
                                record.exc_text = None
                                record.stack_info = None
                                record.empiremuse_emit = True
                                return True
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
                    first_code=error_code,
                    coded_seen=1 if error_code is not None else 0,
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

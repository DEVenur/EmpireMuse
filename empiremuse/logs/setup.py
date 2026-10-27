"""Montagem do log (item 7): handlers de console e de arquivo no root, com a mesma cadeia de filtros nos dois."""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TextIO

from empiremuse import paths
from empiremuse.logs.aggregate import RepeatAggregator
from empiremuse.logs.console import ConsoleFormatter, FileFormatter, report_emit_failure
from empiremuse.logs.context import ContextFilter, LevelGate
from empiremuse.logs.redact import SanitizeAndRedact, configure_secrets, register_secret
from empiremuse.logs.settings import LogSettings

__all__ = ["LIBRARY_LOGGERS", "configure_logging", "flush_logging", "register_secret", "tick_logging"]

# Bibliotecas externas ficam sempre em WARNING; o pacote vendorizado empiremuse.wavelink é nosso e segue o LOG_LEVEL.
LIBRARY_LOGGERS = ("disnake", "aiohttp", "asyncio", "tornado", "urllib3", "pymongo", "motor", "websockets", "PIL")
LOGS_DIR_NAME = ".logs"

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_installed: list[logging.Handler] = []
_aggregator: RepeatAggregator | None = None
_debug_guilds: frozenset[int] = frozenset()


class _ConsoleHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 (nome da API do logging)
        report_emit_failure()


def _uninstall() -> None:
    """Descarrega as contagens pendentes e tira do root os handlers que o ``configure_logging`` anterior instalou."""
    global _aggregator
    root = logging.getLogger()
    if _aggregator is not None:
        _aggregator.flush()
        _aggregator = None
    for handler in _installed:
        root.removeHandler(handler)
        handler.close()
    _installed.clear()


def _file_handler(logs_dir: Path) -> tuple[logging.Handler | None, str | None]:
    """O handler do arquivo e, se ele não abriu, o tipo do erro (pasta sem permissão ou disco cheio não derruba a subida)."""
    from empiremuse.utils.file_log import build_file_log_handler  # import tardio: o file_log importa o pacote logs

    try:
        return build_file_log_handler(logs_dir), None
    except OSError as e:
        return None, type(e).__name__


def configure_logging(
    settings: LogSettings,
    secrets: Iterable[str],
    *,
    stream: TextIO | None = None,
    logs_dir: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Instala o console e, com ``settings.file``, o arquivo. Idempotente: a segunda chamada troca o que a primeira instalou.

    Cadeia dos dois handlers, nesta ordem: ``ContextFilter`` → ``LevelGate`` → ``SanitizeAndRedact`` → ``RepeatAggregator`` →
    formatter. O redator e o agregador são uma instância só, compartilhada, para o console e o arquivo terem o mesmo conteúdo.
    """
    global _aggregator, _debug_guilds
    with _lock:
        _uninstall()
        configure_secrets(secrets)

        console = _ConsoleHandler(stream if stream is not None else sys.stderr)
        console.setFormatter(ConsoleFormatter(settings.color))
        handlers: list[logging.Handler] = [console]
        file_error = None
        if settings.file:
            file_handler, file_error = _file_handler(
                logs_dir if logs_dir is not None else paths.RUNTIME_DIR / LOGS_DIR_NAME
            )
            if file_handler is not None:
                file_handler.setFormatter(FileFormatter())
                handlers.append(file_handler)

        def deliver(record: logging.LogRecord) -> None:
            for handler in list(handlers):
                handler.handle(record)

        redactor = SanitizeAndRedact()
        aggregator = RepeatAggregator(deliver, clock=clock)
        root = logging.getLogger()
        for handler in handlers:
            handler.filters.clear()  # o handler do arquivo já nasce com o redator próprio; aqui a cadeia entra uma vez só
            for filter_ in (ContextFilter(), LevelGate(settings.level, settings.debug_guilds), redactor, aggregator):
                handler.addFilter(filter_)
            root.addHandler(handler)
        _installed.extend(handlers)
        _aggregator = aggregator

        _debug_guilds = settings.debug_guilds
        root.setLevel(logging.DEBUG if settings.debug_guilds else settings.level)
        for name in LIBRARY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
        if file_error is not None:  # depois do addHandler: o aviso sai pelo console já configurado
            logger.warning("Não foi possível abrir o arquivo de log (%s); seguindo só no console.", file_error)


def is_configured() -> bool:
    """Se os handlers do ``configure_logging`` estão no root agora (antes disso valem só os ganchos iniciais)."""
    root_handlers = logging.getLogger().handlers
    return any(handler in root_handlers for handler in _installed)


def configured_debug_guilds() -> frozenset[int]:
    """Servidores em ``LOG_DEBUG_GUILDS`` do último ``configure_logging`` (vazio antes dele)."""
    return _debug_guilds


def flush_logging() -> None:
    """Emite as contagens de repetidos pendentes (no ``shutdown`` do ``BotPool``)."""
    with _lock:
        aggregator = _aggregator
    if aggregator is not None:
        aggregator.flush()


def tick_logging() -> None:
    """Fecha as janelas de repetidos já vencidas (chamado pelo resumo periódico)."""
    with _lock:
        aggregator = _aggregator
    if aggregator is not None:
        aggregator.tick()

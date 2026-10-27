"""Ganchos iniciais de exceção não tratada instalados antes de ``configure_logging`` (item 7, 3.2, V-L9).

Configura o redator único do processo com os segredos de ``environ`` (``collect_secret_values``) e instala
``sys.excepthook`` e ``threading.excepthook`` para nunca escrever tracebacks crus no stderr durante a subida.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from collections.abc import Mapping
from contextlib import suppress
from types import TracebackType
from typing import TextIO

from empiremuse.logs.redact import MAX_TRACEBACK_CHARS, configure_secrets, sanitize_value, scrub
from empiremuse.rules.owner_shell import collect_secret_values

_FRAME = "  │ "


def _write_scrubbed_traceback(
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
    stream: TextIO | None,
    *,
    header: str = "",
    chain: bool = True,
) -> None:
    with suppress(Exception):
        formatted = header + "".join(traceback.format_exception(exc_type, exc_value, exc_tb, chain=chain))
        sanitized = scrub(formatted, MAX_TRACEBACK_CHARS)
        target = stream if stream is not None else sys.stderr
        if target is None:
            return
        framed = "\n".join(f"{_FRAME}{line}" for line in sanitized.splitlines()) + "\n"
        target.write(framed)
        target.flush()


def _log_if_configured(
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
    what: str,
    *,
    chain: bool,
) -> bool:
    """Depois do ``configure_logging`` a exceção vai ao logger ``empiremuse.errors`` (redator, agregador e arquivo); antes, não.

    Import tardio: ``logs.errors`` depende do ``logs.setup``, que não pode depender deste módulo.
    """
    with suppress(Exception):
        from empiremuse.logs.errors import log_unhandled
        from empiremuse.logs.setup import is_configured

        if not is_configured():
            return False
        if not chain and exc_value is not None:
            exc_value.__context__ = exc_value.__cause__ = None
        log_unhandled(exc_type, exc_value, exc_tb, what)
        return True
    return False


def install_early_hooks(
    environ: Mapping[str, str] = os.environ,
    *,
    stream: TextIO | None = None,
) -> None:
    """Alimenta o redator único com ``environ`` e instala ``sys.excepthook`` e ``threading.excepthook`` redigidos."""

    def _sys_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        chain = not issubclass(exc_type, KeyboardInterrupt)
        if _log_if_configured(exc_type, exc_value, exc_tb, "Exceção não tratada", chain=chain):
            return
        _write_scrubbed_traceback(exc_type, exc_value, exc_tb, stream, chain=chain)

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is None or issubclass(args.exc_type, SystemExit):
            return
        thread_name = getattr(args.thread, "name", None) or "Thread"
        what = f"Exceção não tratada na thread {sanitize_value(str(thread_name))}"
        if _log_if_configured(args.exc_type, args.exc_value, args.exc_traceback, what, chain=True):
            return
        header = f"Exception in thread {thread_name}:\n"
        _write_scrubbed_traceback(args.exc_type, args.exc_value, args.exc_traceback, stream, header=header)

    sys.excepthook = _sys_excepthook
    threading.excepthook = _threading_excepthook
    with suppress(Exception):
        configure_secrets(collect_secret_values(environ))

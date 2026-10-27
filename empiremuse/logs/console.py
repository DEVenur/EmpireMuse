"""Formatters do log (item 7): console (cor e emoji) e arquivo (texto puro), e a linha fixa de falha ao emitir.

Os dois recebem registros já processados pelo filtro de redação: ``exc_info`` zerado, ``exc_text`` e ``stack_info`` prontos. Nunca
formatam ``exc_info`` (o traceback sairia sem redação). Toda linha depois do cabeçalho leva o prefixo ``  │ ``: nenhum texto de terceiros
consegue produzir uma linha que pareça um registro novo.
"""

from __future__ import annotations

import logging
import sys
import time

FRAME = "  │ "
BULLET = "•"
ERROR_EMOJI = "❌"
RESET = "\x1b[0m"
LEVEL_NAME_WIDTH = 8

CATEGORY_EMOJI = {
    "empiremuse.boot": "🚀",
    "empiremuse.player": "🎵",
    "empiremuse.wavelink": "🌋",
    "empiremuse.metrics": "📊",
    "empiremuse.db": "🗄️",
    "empiremuse.panel": "🌐",
    "empiremuse.updater": "⬆️",
}

# Parâmetros SGR: DEBUG cinza, INFO ciano, WARNING amarelo, ERROR vermelho, CRITICAL vermelho negrito; contexto em cinza.
LEVEL_COLORS = {
    logging.DEBUG: "90",
    logging.INFO: "36",
    logging.WARNING: "33",
    logging.ERROR: "31",
    logging.CRITICAL: "1;31",
}
CONTEXT_COLOR = "90"


def report_emit_failure() -> None:
    """Linha fixa no stderr quando um handler falha ao emitir; nunca a mensagem, os argumentos nem o texto da exceção.

    Chamada de dentro do ``except`` do ``Handler.emit`` (é o ``handleError`` dos handlers instalados), então ``sys.exc_info`` vale.
    """
    kind = sys.exc_info()[0]
    name = kind.__name__ if kind is not None else "desconhecido"
    try:
        sys.stderr.write(f"[log] falha ao emitir um registro ({name})\n")
        sys.stderr.flush()
    except Exception:
        pass  # sem stderr não há para onde avisar, e log nunca derruba quem logou


def _category_emoji(record: logging.LogRecord) -> str:
    if record.levelno >= logging.ERROR:
        return ERROR_EMOJI
    for prefix, emoji in CATEGORY_EMOJI.items():
        if record.name == prefix or record.name.startswith(prefix + "."):
            return emoji
    return BULLET


def _context(record: logging.LogRecord) -> str:
    """``bot/servidor``, ``bot`` ou ``servidor`` (só o que existe); vazio sem contexto."""
    parts = [str(part) for part in (getattr(record, "bot", None), getattr(record, "guild", None)) if part is not None]
    return "/".join(parts)


def _frame(text: str) -> list[str]:
    return [FRAME + line for line in text.rstrip("\n").split("\n")]


class _FramedFormatter(logging.Formatter):
    """Cabeçalho + corpo enquadrado; as subclasses montam só o cabeçalho."""

    def header(self, record: logging.LogRecord, first_line: str) -> str:
        raise NotImplementedError

    def format(self, record: logging.LogRecord) -> str:
        first_line, *continuation = record.getMessage().split("\n")
        lines = [self.header(record, first_line)]
        lines.extend(FRAME + line for line in continuation)
        if record.exc_text:
            lines.extend(_frame(record.exc_text))
        if record.stack_info:
            lines.extend(_frame(record.stack_info))
        return "\n".join(lines)


class ConsoleFormatter(_FramedFormatter):
    """``HH:MM:SS NÍVEL emoji [bot/servidor] logger: mensagem``; a cor vale só para o nível e o contexto, nunca para o texto."""

    def __init__(self, color: bool) -> None:
        super().__init__()
        self.color = color

    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}{RESET}" if self.color else text

    def header(self, record: logging.LogRecord, first_line: str) -> str:
        clock = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = self._paint(record.levelname.ljust(LEVEL_NAME_WIDTH), LEVEL_COLORS.get(record.levelno, "0"))
        context = _context(record)
        context = self._paint(f"[{context}]", CONTEXT_COLOR) + " " if context else ""
        return f"{clock} {level} {_category_emoji(record)} {context}{record.name}: {first_line}"


class FileFormatter(_FramedFormatter):
    """``AAAA-MM-DD HH:MM:SS,mmm NÍVEL [bot/servidor] logger: mensagem``: sem cor e sem emoji (dá para usar grep)."""

    def header(self, record: logging.LogRecord, first_line: str) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        context = _context(record)
        context = f"[{context}] " if context else ""
        return f"{stamp},{int(record.msecs):03d} {record.levelname} {context}{record.name}: {first_line}"

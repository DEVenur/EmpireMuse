"""Contexto do log (item 7): bot e servidor da tarefa atual, e o nível por servidor (``LOG_DEBUG_GUILDS``)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from empiremuse.logs.redact import sanitize_value

OWN_LOGGER = "empiremuse"

log_bot: ContextVar[str | None] = ContextVar("log_bot", default=None)
log_guild: ContextVar[int | None] = ContextVar("log_guild", default=None)


@contextmanager
def log_context(*, bot: str | None = None, guild: int | None = None) -> Iterator[None]:
    """Bot e servidor dos registros emitidos dentro do bloco; o que não vier fica como estava (aninhamento)."""
    tokens = []
    if bot is not None:
        tokens.append((log_bot, log_bot.set(bot)))
    if guild is not None:
        tokens.append((log_guild, log_guild.set(guild)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def guild_extra(value: object) -> dict[str, int]:
    """``extra`` com o servidor para o log: ``{"guild": id}`` se ``value`` é um ID (int ou texto só de dígitos ASCII), senão vazio.

    O ``LevelGate`` só deixa o DEBUG de um servidor de ``LOG_DEBUG_GUILDS`` passar com ``record.guild`` int, e o ``ContextFilter`` só
    aceita int: um ``_id`` de sessão vem como texto, então a conversão fica aqui e um valor inválido nunca levanta.
    """
    if isinstance(value, bool):
        return {}
    if isinstance(value, int):
        return {"guild": value}
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return {"guild": int(value)}
    return {}


class ContextFilter(logging.Filter):
    """Copia o contexto para ``record.bot`` e ``record.guild``; um ``extra`` do próprio registro vence.

    Total: nunca levanta e nunca descarta. O nome do bot é texto livre, então passa pelo saneamento de controles.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            bot = getattr(record, "bot", None)
            if not isinstance(bot, str):
                bot = log_bot.get()
            record.bot = sanitize_value(bot) if bot is not None else None
            guild = getattr(record, "guild", None)
            if isinstance(guild, bool) or not isinstance(guild, int):
                guild = log_guild.get()
            record.guild = guild
        except Exception:
            record.bot = record.guild = None
        return True


class LevelGate(logging.Filter):
    """Abaixo de ``level`` só passa o DEBUG de um logger nosso, no contexto de um servidor em ``debug_guilds``.

    O DEBUG de bibliotecas fora do ``LIBRARY_LOGGERS`` (``requests``, ``charset_normalizer``...) nunca passa só por estar dentro do
    contexto de um servidor em debug. Não formata nada: lê o nível, o nome e o servidor do registro.
    """

    def __init__(self, level: int, debug_guilds: frozenset[int]) -> None:
        super().__init__()
        self.level = level
        self.debug_guilds = debug_guilds

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.levelno >= self.level:
                return True
            if not self.debug_guilds:
                return False
            if record.name != OWN_LOGGER and not record.name.startswith(OWN_LOGGER + "."):
                return False
            guild = getattr(record, "guild", None)
            return isinstance(guild, int) and guild in self.debug_guilds
        except Exception:
            return True  # na dúvida o registro segue: a redação vem depois e nada se perde por um filtro defeituoso

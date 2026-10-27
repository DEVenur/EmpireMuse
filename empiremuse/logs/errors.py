"""Erros no log (item 7, P4): o contexto de um comando que falha, os ganchos globais e o tratador do laço de eventos.

Tudo vai para o logger ``empiremuse.errors``. O contexto de um comando (``command_context``) leva só IDs e um resumo por tipo dos
parâmetros: nunca nome de usuário, apelido, nome de servidor, conteúdo de mensagem nem a URL assinada de um anexo.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Mapping

import disnake

from empiremuse.logs.redact import redact, sanitize_value
from empiremuse.logs.setup import configured_debug_guilds
from empiremuse.rules.owner_shell import is_secret_name

ERRORS_LOGGER = "empiremuse.errors"
MAX_TEXT_CHARS = 100  # texto livre de um parâmetro, quando ele pode aparecer
MAX_PARAMS_CHARS = 500  # teto do conjunto dos parâmetros
MASKED = "***"

logger = logging.getLogger(ERRORS_LOGGER)

# Modelos do disnake resumidos por tipo e ID.
_BY_ID = (
    disnake.Member,
    disnake.User,
    disnake.Message,
    disnake.Guild,
    disnake.Role,
    disnake.abc.GuildChannel,
    disnake.abc.PrivateChannel,
    disnake.Thread,
    disnake.Emoji,
)


def _first_id(*candidates: object) -> int | None:
    return next((value for value in candidates if isinstance(value, int) and not isinstance(value, bool)), None)


def _command_name(ctx_or_inter: object) -> str:
    command = getattr(ctx_or_inter, "application_command", None) or getattr(ctx_or_inter, "command", None)
    name = getattr(command, "qualified_name", None) or getattr(getattr(ctx_or_inter, "data", None), "name", None)
    return sanitize_value(str(name)) if name else "?"


def _rest_of_prefix_command(ctx: object) -> str | None:
    """O que veio depois do prefixo e do nome do comando numa mensagem de prefixo; ``None`` se não é uma."""
    content = getattr(getattr(ctx, "message", None), "content", None)
    if not isinstance(content, str):
        return None
    content = content[len(getattr(ctx, "prefix", "") or "") :].strip()
    return content.split(None, 1)[1] if " " in content else ""


def _summarize(name: str, value: object, *, reveal: bool, budget: int) -> str:
    """Resumo de um parâmetro por tipo, sem ``repr`` (que traria nome, apelido e URL assinada da CDN)."""
    if is_secret_name(name):
        return MASKED
    if isinstance(value, disnake.Attachment):
        return f"Attachment(tipo={value.content_type}, tamanho={value.size})"
    if isinstance(value, _BY_ID):
        return f"{value.__class__.__name__}(id={getattr(value, 'id', '?')})"
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, str):
        if not reveal:
            return f"str(len={len(value)})"
        return redact(sanitize_value(value[: min(MAX_TEXT_CHARS, max(budget, 0))]))
    return type(value).__name__


def command_context(ctx_or_inter: object, *, level: int) -> dict[str, object]:
    """``command``, ``user_id``, ``guild_id``, ``channel_id`` e ``params`` (nome → resumo em texto) de uma interação ou contexto de prefixo.

    O texto livre só aparece com ``level <= DEBUG`` ou com o servidor em ``LOG_DEBUG_GUILDS``; nos demais casos vai só o tamanho. Um
    parâmetro cujo nome casa com o regex de segredo vira ``***`` em qualquer nível. Nunca levanta.
    """
    author = getattr(ctx_or_inter, "author", None) or getattr(ctx_or_inter, "user", None)
    guild_id = _first_id(
        getattr(ctx_or_inter, "guild_id", None), getattr(getattr(ctx_or_inter, "guild", None), "id", None)
    )
    channel_id = _first_id(
        getattr(ctx_or_inter, "channel_id", None), getattr(getattr(ctx_or_inter, "channel", None), "id", None)
    )
    reveal = level <= logging.DEBUG or (guild_id is not None and guild_id in configured_debug_guilds())

    options = getattr(ctx_or_inter, "filled_options", None)
    if not isinstance(options, Mapping):
        rest = _rest_of_prefix_command(ctx_or_inter)
        options = {} if rest is None else {"texto": rest}

    params: dict[str, str] = {}
    budget = MAX_PARAMS_CHARS
    for name, value in options.items():
        key = sanitize_value(str(name))
        try:
            summary = _summarize(key, value, reveal=reveal, budget=budget)
        except Exception:
            summary = type(value).__name__
        params[key] = summary
        budget -= len(summary)

    return {
        "command": _command_name(ctx_or_inter),
        "user_id": _first_id(getattr(author, "id", None)),
        "guild_id": guild_id,
        "channel_id": channel_id,
        "params": params,
    }


def loop_exception_handler(loop: asyncio.AbstractEventLoop, context: Mapping[str, object]) -> None:
    """Tratador de exceção do laço (``Task exception was never retrieved`` etc.): ERROR com traceback; o cancelamento não é erro."""
    error = context.get("exception")
    if isinstance(error, asyncio.CancelledError):
        return
    message = str(context.get("message") or "Erro no laço de eventos")
    if isinstance(error, BaseException):
        logger.error("%s", message, exc_info=(type(error), error, error.__traceback__))
    else:
        logger.error("%s", message)


def install_exception_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Liga o tratador de exceção do laço ao logger de erros."""
    loop.set_exception_handler(loop_exception_handler)


def log_unhandled(exc_type: type[BaseException], exc_value: BaseException | None, exc_tb: object, what: str) -> None:
    """Exceção não tratada (processo ou thread) no logger de erros, com o traceback."""
    logger.error("%s", what, exc_info=(exc_type, exc_value, exc_tb))

"""Cota do usuário no bot: junta a configuração, o dono do bot e a regra de ``empiremuse.rules.quota``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from empiremuse.rules.errors import NAME_INVALID, RuleError
from empiremuse.rules.quota import quota_limit

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore


async def quota_for(bot: BotCore, user: Any, config_key: str) -> int:
    """Limite de itens do usuário: ``0`` = sem limite (configuração ``0`` ou dono do bot); o dono só é consultado se houver limite."""
    maximum = int(bot.config[config_key])
    if maximum <= 0:
        return 0
    return quota_limit(maximum, await bot.is_owner(user))


def track_fav_error_text(error: RuleError) -> str:
    """Mensagem ao usuário quando o botão de favoritar a faixa não pôde gravar (``error`` vem de ``save_track``)."""
    if error.code == NAME_INVALID:
        return "O nome da faixa é curto demais para virar favorito."
    return (
        "Você não possui espaço suficiente para adicionar este favorito (remova algum e tente novamente).\n"
        f"Limite atual: {error.limit}"
    )

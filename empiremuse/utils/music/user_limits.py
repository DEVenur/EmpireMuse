"""Cota do usuário no bot: junta a configuração, o dono do bot e a regra de ``empiremuse.rules.quota``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from empiremuse.rules.quota import quota_limit

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore


async def quota_for(bot: BotCore, user: Any, config_key: str) -> int:
    """Limite de itens do usuário: ``0`` = sem limite (configuração ``0`` ou dono do bot); o dono só é consultado se houver limite."""
    maximum = int(bot.config[config_key])
    if maximum <= 0:
        return 0
    return quota_limit(maximum, await bot.is_owner(user))

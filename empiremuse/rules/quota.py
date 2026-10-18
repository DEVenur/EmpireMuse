"""Regra de cota de itens (favoritos e integrações)."""

from __future__ import annotations


def quota_limit(maximum: int, is_owner: bool) -> int:
    """Limite aplicável ao usuário: ``0`` = ilimitado (configuração ``<= 0`` ou dono do bot)."""
    if maximum <= 0:
        return 0
    return 0 if is_owner else maximum

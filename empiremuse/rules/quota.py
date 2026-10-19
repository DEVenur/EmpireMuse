"""Regra de cota de itens (favoritos e integrações)."""

from __future__ import annotations

from typing import Any, Mapping


def quota_limit(maximum: int, is_owner: bool) -> int:
    """Limite aplicável ao usuário: ``0`` = ilimitado (configuração ``<= 0`` ou dono do bot)."""
    if maximum <= 0:
        return 0
    return 0 if is_owner else maximum


def has_room(entries: Mapping[str, Any], name: str, limit: int) -> bool:
    """Cabe ``name`` em ``entries``? Sobrescrever um nome que já existe não ocupa vaga; ``limit`` ``0`` = sem limite."""
    return not limit or name in entries or len(entries) < limit


def file_exceeds(incoming: int, limit: int) -> bool:
    """O arquivo de importação, sozinho, tem mais itens do que o limite permite?"""
    return bool(limit) and incoming > limit


def import_has_room(kept: int, incoming: int, limit: int) -> bool:
    """Cabem os ``incoming`` itens do arquivo junto dos ``kept`` que sobraram depois de tirar os nomes sobrescritos?"""
    return not limit or kept + incoming <= limit

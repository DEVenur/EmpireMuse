"""Regras das configurações de servidor: skins permitidas."""

from __future__ import annotations

from typing import Iterable


def allowed_names(names: Iterable[str], ignored: str) -> tuple[str, ...]:
    """Nomes de skin que não estão na lista ``ignored`` (texto da configuração, separado por espaços)."""
    skip = ignored.split()
    return tuple(name for name in names if name not in skip)

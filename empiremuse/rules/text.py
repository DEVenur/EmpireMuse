"""Regras de texto: nomes normalizados, nomes iguais sem diferenciar a caixa e status de voz."""

from __future__ import annotations

import unicodedata
from typing import Any, Mapping, Optional


def clean_title(raw: Any, low: int, high: int) -> Optional[str]:
    """Nome normalizado (strip, ``low``–``high`` caracteres, sem controle/formatação) ou ``None``."""
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if not low <= len(name) <= high:
        return None
    if any(unicodedata.category(char) in ("Cc", "Cf") for char in name):
        return None
    return name


def clean_import_name(name: str, low: int, high: int, already: dict) -> Optional[str]:
    """Nome normalizado (regra do painel) que ainda não apareceu em ``already``; ``None`` se inválido ou repetido."""
    clean = clean_title(name, low, high)
    if clean is None or clean.casefold() in {key.casefold() for key in already}:
        return None
    return clean


def drop_same_names(entries: dict, names) -> None:
    """Tira de ``entries`` (cópia de trabalho) as chaves iguais a ``names``, sem diferenciar maiúsculas de minúsculas."""
    wanted = {name.casefold() for name in names}
    for key in [key for key in entries if key.casefold() in wanted]:
        del entries[key]


def normalize_status(text: str) -> str:
    """Quebras de linha viram espaço e as pontas são aparadas, como o modal do comando."""
    flat = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    return flat.strip()


def find_same_name(entries: Mapping[str, Any], name: str) -> Optional[str]:
    """A chave de ``entries`` igual a ``name`` sem diferenciar maiúsculas de minúsculas, ou ``None``."""
    wanted = name.casefold()
    return next((key for key in entries if key.casefold() == wanted), None)


def clean_track_name(raw: Any, low: int, high: int) -> Optional[str]:
    """Nome vindo do título de uma faixa: sem controle/formatação, aparado, cortado em ``high`` e aparado de novo.

    ``None`` se não for texto ou se sobrar menos de ``low`` caracteres.
    """
    if not isinstance(raw, str):
        return None
    visible = "".join(char for char in raw if unicodedata.category(char) not in ("Cc", "Cf"))
    name = visible.strip()[:high].strip()
    return name if len(name) >= low else None

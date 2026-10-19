"""Listas de entradas nomeadas (favoritos, links do servidor): salvar uma entrada e mesclar uma importação.

Os nomes são comparados sem diferenciar maiúsculas de minúsculas. Nada aqui altera os dicionários recebidos: o
resultado é sempre um dicionário novo (ou um ``RuleError``).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from empiremuse.rules.errors import FILE_TOO_LARGE, NAME_INVALID, NAME_TAKEN, NO_SPACE, QUOTA_FULL, RuleError
from empiremuse.rules.quota import file_exceeds, has_room, import_has_room
from empiremuse.rules.text import clean_title, find_same_name


def check_name(
    entries: Mapping[str, Any], old_name: Optional[str], raw_name: Any, *, name_min: int, name_max: int
) -> str | RuleError:
    """Nome para salvar: aparado, de ``name_min`` a ``name_max`` caracteres, sem controle/formatação e sem colidir
    (sem diferenciar a caixa) com OUTRA entrada. ``old_name`` é a entrada que está sendo editada (``None`` ao adicionar);
    reenviar exatamente o nome dela não revalida nada."""
    if old_name is not None and raw_name == old_name:
        return old_name
    name = clean_title(raw_name, name_min, name_max)
    if name is None:
        return RuleError(NAME_INVALID, value=raw_name)
    others = {key: None for key in entries if key != old_name}
    clash = find_same_name(others, name)
    if clash is not None:
        return RuleError(NAME_TAKEN, key=clash)
    return name


def save_entry(
    entries: Mapping[str, Any],
    old_name: Optional[str],
    raw_name: Any,
    value: Any,
    *,
    name_min: int,
    name_max: int,
    limit: int,
) -> dict[str, Any] | RuleError:
    """``entries`` com ``value`` gravado sob o nome validado; renomear move a entrada e editar sem renomear a troca no lugar.

    ``limit`` ``0`` = sem limite; só um nome NOVO ocupa vaga (renomear ou editar não).
    """
    old = old_name if old_name in entries else None
    name = check_name(entries, old, raw_name, name_min=name_min, name_max=name_max)
    if isinstance(name, RuleError):
        return name
    renamed = old is not None and name != old
    remaining = {key: item for key, item in entries.items() if not (renamed and key == old)}
    if not has_room(remaining, name, limit):
        return RuleError(QUOTA_FULL, limit=limit)
    if old is not None and not renamed:
        return {key: (value if key == old else item) for key, item in entries.items()}
    return {**remaining, name: value}


def merge_import(existing: Mapping[str, Any], incoming: Mapping[str, Any], limit: int) -> dict[str, Any] | RuleError:
    """``existing`` sem as entradas de mesmo nome do arquivo (substituir não ocupa vaga) mais o ``incoming``."""
    if file_exceeds(len(incoming), limit):
        return RuleError(FILE_TOO_LARGE, limit=limit)
    wanted = {name.casefold() for name in incoming}
    kept = {key: item for key, item in existing.items() if key.casefold() not in wanted}
    if not import_has_room(len(kept), len(incoming), limit):
        return RuleError(NO_SPACE, value=(len(kept), len(incoming)), limit=limit)
    return {**kept, **incoming}

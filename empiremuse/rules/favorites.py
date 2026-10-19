"""Favoritos pessoais: limite do nome, nome de importação e favoritar a faixa que está tocando."""

from __future__ import annotations

from typing import Any, Mapping, NamedTuple

from empiremuse.rules.errors import NAME_INVALID, NAME_TOO_LONG, QUOTA_FULL, RuleError
from empiremuse.rules.limits import FAV_NAME_MAX, FAV_NAME_MIN, FAV_URL_MAX
from empiremuse.rules.quota import has_room
from empiremuse.rules.text import clean_title, clean_track_name, find_same_name
from empiremuse.rules.urls import check_url


def name_limit(configured: Any) -> int:
    """Teto do nome do favorito: o menor entre ``USER_FAV_MAX_NAME_LENGTH`` e os 25 caracteres do modal do Discord."""
    return min(int(configured), FAV_NAME_MAX)


def check_import_name(raw: Any, already: Mapping[str, Any], configured: Any) -> str | RuleError:
    """Nome de um item do arquivo: 2 a 25 caracteres limpos e sem repetir (sem diferenciar a caixa) um já aceito;
    com a configuração abaixo de 25, o que passar dela é ``NAME_TOO_LONG``."""
    name = clean_title(raw, FAV_NAME_MIN, FAV_NAME_MAX)
    if name is None or find_same_name(already, name) is not None:
        return RuleError(NAME_INVALID, value=raw)
    if len(name) > int(configured):
        return RuleError(NAME_TOO_LONG, value=name, limit=int(configured))
    return name


class TrackSave(NamedTuple):
    entries: dict[str, Any]
    name: str
    url: str


def save_track(entries: Mapping[str, Any], raw_name: Any, raw_url: Any, *, limit: int) -> TrackSave | RuleError:
    """Favoritar a faixa que toca: o nome vem do título (cortado em 25 e limpo) e sobrescreve o favorito de mesmo nome."""
    name = clean_track_name(raw_name, FAV_NAME_MIN, FAV_NAME_MAX)
    if name is None:
        return RuleError(NAME_INVALID, value=raw_name)
    url = check_url(raw_url, FAV_URL_MAX)
    if isinstance(url, RuleError):
        return url
    key = find_same_name(entries, name) or name
    if not has_room(entries, key, limit):
        return RuleError(QUOTA_FULL, limit=limit)
    return TrackSave({**entries, key: url}, key, url)

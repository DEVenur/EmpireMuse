"""Integrações pessoais (``integration_links``): item de importação e integração montada com dados externos."""

from __future__ import annotations

from typing import Any, Mapping, NamedTuple

from empiremuse.rules.errors import AVATAR_INVALID, NAME_INVALID, QUOTA_FULL, RuleError
from empiremuse.rules.limits import ITG_TITLE_MAX, ITG_URL_MAX
from empiremuse.rules.quota import has_room
from empiremuse.rules.text import clean_track_name, find_same_name
from empiremuse.rules.urls import check_url, clean_avatar


def import_entry(value: Any) -> dict[str, str] | RuleError:
    """Item de importação: o texto-URL do formato antigo ou ``{"url", "avatar"?}``; vira ``{"url"}`` ou ``{"url", "avatar"}``."""
    is_object = isinstance(value, Mapping)
    url = check_url(value.get("url") if is_object else value, ITG_URL_MAX)
    if isinstance(url, RuleError):
        return url
    avatar = clean_avatar(value.get("avatar")) if is_object else ""
    if avatar is None:
        return RuleError(AVATAR_INVALID, value=value["avatar"])
    return {"url": url, "avatar": avatar} if avatar else {"url": url}


class ExternalSave(NamedTuple):
    entries: dict[str, Any]
    name: str
    url: str


def save_external(
    entries: Mapping[str, Any], raw_title: Any, raw_url: Any, raw_avatar: Any, *, limit: int
) -> ExternalSave | RuleError:
    """Grava a integração montada com dados de Spotify, Deezer ou yt-dlp (fonte semiconfiável, revalidada).

    O título perde controle/formatação e é cortado em 90; a URL é a URL pura de até 200 (``RuleError`` se não for); o avatar
    inválido é descartado. Um título igual a outro sem diferenciar a caixa sobrescreve a entrada existente e só um título
    novo ocupa vaga.
    """
    title = clean_track_name(raw_title, 1, ITG_TITLE_MAX)
    if title is None:
        return RuleError(NAME_INVALID, value=raw_title)
    url = check_url(raw_url, ITG_URL_MAX)
    if isinstance(url, RuleError):
        return url
    avatar = clean_avatar(raw_avatar) or ""
    key = find_same_name(entries, title) or title
    if not has_room(entries, key, limit):
        return RuleError(QUOTA_FULL, limit=limit)
    entry = {"url": url, "avatar": avatar} if avatar else {"url": url}
    return ExternalSave({**entries, key: entry}, key, url)

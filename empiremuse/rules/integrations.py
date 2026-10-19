"""Integrações pessoais (``integration_links``): item de importação, sempre gravado como objeto."""

from __future__ import annotations

from typing import Any, Mapping

from empiremuse.rules.errors import AVATAR_INVALID, RuleError
from empiremuse.rules.limits import ITG_URL_MAX
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

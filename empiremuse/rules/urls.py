"""Regras de URL: extração do modal manual, prefixo do importador do painel e URL inteira limpa do importador do bot.

As três variantes existem hoje com comportamentos diferentes e são mantidas como estão (a unificação vem depois).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from empiremuse.rules.limits import ITG_AVATAR_MAX

URL_REG = re.compile("http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%[0-9a-fA-F][0-9a-fA-F])+")
_MASS_MENTION_REG = re.compile(r"@(?:everyone|here)", re.IGNORECASE)


def extract_url_legacy(text: str) -> Optional[str]:
    """Primeiro trecho de ``text`` que casa com ``URL_REG`` (em qualquer posição), como o modal manual; ou ``None``."""
    found = URL_REG.findall(text)
    return found[0] if found else None


def url_prefix_legacy(value: Any, max_chars: int) -> Optional[str]:
    """URL do importador do painel: texto, até ``max_chars`` e começando com URL; devolve só o trecho que casa."""
    if not isinstance(value, str) or len(value) > max_chars:
        return None
    match = URL_REG.match(value)
    return match.group(0) if match else None


def is_clean_url(url: str) -> bool:
    """A URL INTEIRA (não só o prefixo) casa com ``URL_REG``, sem colchetes (markdown) nem menções em massa."""
    if not URL_REG.fullmatch(url) or "[" in url or "]" in url:
        return False
    return not _MASS_MENTION_REG.search(url)


def clean_avatar(avatar) -> Optional[str]:
    """Avatar opcional da integração: ``""`` se ausente (``None`` ou vazio), a URL limpa, ou ``None`` se inválido."""
    if avatar is None or avatar == "":
        return ""
    if not isinstance(avatar, str):
        return None
    avatar = avatar.strip()
    if len(avatar) > ITG_AVATAR_MAX or not URL_REG.match(avatar) or not is_clean_url(avatar):
        return None
    return avatar

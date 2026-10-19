"""Regras de URL: a URL pura (``check_url``/``clean_url``) vale para modais, importadores, painel e botões de favoritar.

``extract_url_legacy`` e ``url_prefix_legacy`` são as regras antigas (primeiro trecho do texto e só o prefixo); não são mais
usadas e saem junto com os testes que as fixam.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from empiremuse.rules.errors import URL_INVALID, URL_TOO_LONG, RuleError
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


def _unwrap(raw: str) -> str:
    """Apara as pontas e tira o ``<`` e o ``>`` que envolvem o link (usados no Discord para não gerar prévia)."""
    text = raw.strip()
    if len(text) >= 2 and text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    return text


def check_url(raw: Any, max_chars: Optional[int] = None) -> str | RuleError:
    """URL pura: apara as pontas, desembrulha ``<...>`` e exige a URL INTEIRA limpa (sem texto ao redor, colchetes nem
    menções em massa). ``URL_TOO_LONG`` se passar de ``max_chars``; ``URL_INVALID`` nos demais casos."""
    if not isinstance(raw, str):
        return RuleError(URL_INVALID, value=raw)
    text = _unwrap(raw)
    if max_chars is not None and len(text) > max_chars:
        return RuleError(URL_TOO_LONG, value=text, limit=max_chars)
    return text if is_clean_url(text) else RuleError(URL_INVALID, value=text)


def clean_url(raw: Any, max_chars: Optional[int] = None) -> Optional[str]:
    """A URL pura de ``check_url``, ou ``None`` se não vale (qualquer motivo)."""
    result = check_url(raw, max_chars)
    return None if isinstance(result, RuleError) else result


def clean_avatar(avatar) -> Optional[str]:
    """Avatar opcional da integração: ``""`` se ausente (``None`` ou vazio), a URL pura, ou ``None`` se inválido."""
    if avatar is None or avatar == "":
        return ""
    return clean_url(avatar, ITG_AVATAR_MAX)

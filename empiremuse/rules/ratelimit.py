"""Pausa por limite de requisições (HTTP 429): quanto tempo esperar a partir do cabeçalho ``Retry-After``."""

from __future__ import annotations

from typing import Any

DEFAULT_PAUSE_SECONDS = 60
MIN_PAUSE_SECONDS = 1
MAX_PAUSE_SECONDS = 3600
_MAX_DIGITS = 12  # acima disso o número já passa de qualquer teto razoável (e evita converter texto enorme)


def retry_after_seconds(
    raw: Any,
    *,
    default: int = DEFAULT_PAUSE_SECONDS,
    minimum: int = MIN_PAUSE_SECONDS,
    maximum: int = MAX_PAUSE_SECONDS,
) -> int:
    """Segundos de espera: o ``Retry-After`` em inteiro, limitado entre ``minimum`` e ``maximum``; ``default`` se ausente
    ou inválido (vazio, negativo, decimal, data HTTP ou qualquer outra coisa que não seja um inteiro sem sinal)."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        if raw < 0:
            return default
        seconds = raw
    elif isinstance(raw, str) and (text := raw.strip()).isascii() and text.isdigit():
        seconds = maximum if len(text) > _MAX_DIGITS else int(text)
    else:
        return default
    return max(minimum, min(seconds, maximum))

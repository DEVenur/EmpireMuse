"""IP do visitante atrás da Cloudflare: o cabeçalho ``CF-Connecting-IP``, só quando o proxy é confiável.

A Cloudflare sempre envia ``CF-Connecting-IP`` com o IP do visitante. O proxy da frente (ex.: Traefik) costuma preencher
``X-Real-IP``/``X-Forwarded-For`` com o IP da BORDA da Cloudflare, e aí todos os visitantes pareceriam o mesmo IP (limite de
tentativas do login e logs quebrados). Sem proxy confiável o cabeçalho é ignorado: um cliente que chega direto poderia forjá-lo.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

CLOUDFLARE_IP_HEADER = "CF-Connecting-IP"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """O valor do cabeçalho sem diferenciar maiúsculas de minúsculas (``HTTPHeaders`` já é; um ``dict`` comum não)."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _valid_ip(text: str) -> str | None:
    """O IP no formato canônico, ou ``None`` se não for um endereço IPv4/IPv6 simples (sem lista, porta nem escopo)."""
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id:
        return None
    return str(address)


def client_ip_from_headers(headers: Mapping[str, str], trust_proxy: bool, fallback: str | None) -> str | None:
    """O IP do visitante: ``CF-Connecting-IP`` válido com proxy confiável; senão ``fallback`` (o IP já resolvido).

    ``fallback`` é o que o servidor já tem (``request.remote_ip``, com ``xheaders`` quando o proxy é confiável). Cabeçalho
    ausente, repetido (valores juntos viram uma lista) ou inválido cai no ``fallback``.
    """
    if not trust_proxy:
        return fallback
    value = _header(headers, CLOUDFLARE_IP_HEADER)
    if value is None:
        return fallback
    return _valid_ip(value) or fallback

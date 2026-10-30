# -*- coding: utf-8 -*-
"""Baixar o arquivo de playlists de um link (item 17, P5), com a defesa contra SSRF.

O link vem de um administrador do Discord e o bot faz a requisição de dentro da rede dele, então cada passo fecha uma porta:
só ``https`` e só quatro hosts (``rules.playlists.check_import_url``); o MESMO ``yarl.URL`` conferido é o enviado; o nome é
resolvido aqui e TODO endereço precisa ser público; a conexão usa um resolvedor fixo com os IPs conferidos (SNI e certificado
continuam no nome do host, nunca ``ssl=False``); sem redirecionamento, sem proxy, sem cookie, sem descompressão; corpo lido em
pedaços e cortado acima de 64 KiB sem confiar em ``Content-Length``; no máximo 10 s no total. A URL nunca vai para o log nem
para a resposta (link do CDN e ``?token=`` são credenciais): o log leva só o host e o tipo do erro.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Optional

import aiohttp
import yarl

from empiremuse.rules.errors import FILE_TOO_LARGE, IMPORT_FETCH_FAILED, IMPORT_URL_REFUSED, RuleError
from empiremuse.rules.limits import PLAYLIST_FILE_MAX_BYTES
from empiremuse.rules.playlists import IMPORT_URL_HOSTS, check_import_url, is_public_address

logger = logging.getLogger(__name__)

USER_AGENT = "EmpireMuse-playlist-import"
TOTAL_TIMEOUT = 10.0  # segundos, do DNS ao último byte
CONNECT_TIMEOUT = 5.0
CHUNK_SIZE = 8192
MAX_CONCURRENT = 2  # além do cooldown do comando: no máximo duas buscas ao mesmo tempo no processo
HTTPS_PORT = 443

Resolve = Callable[[str, int], Awaitable[Sequence[str]]]
SessionFactory = Callable[[Sequence[str], str], aiohttp.ClientSession]

_gate = asyncio.Semaphore(MAX_CONCURRENT)


class PinnedResolver(aiohttp.abc.AbstractResolver):
    """Resolvedor do conector: só devolve os IPs que já foram conferidos, e só para o host do link (nada de DNS de novo)."""

    def __init__(self, host: str, addresses: Sequence[str]) -> None:
        self._host = host
        self._addresses = tuple(addresses)

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict[str, Any]]:
        if host != self._host:
            raise OSError("host fora do link conferido")
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self._addresses
        ]

    async def close(self) -> None:
        return None


async def system_resolve(host: str, port: int) -> list[str]:
    """Todos os endereços (A e AAAA) que o sistema dá para o nome."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def default_session(addresses: Sequence[str], host: str) -> aiohttp.ClientSession:
    """Sessão própria da busca: sem proxy do ambiente, sem cookie, sem descompressão, uma conexão, IPs fixos."""
    connector = aiohttp.TCPConnector(
        resolver=PinnedResolver(host, addresses), use_dns_cache=False, limit=1, force_close=True
    )
    return aiohttp.ClientSession(
        connector=connector,
        trust_env=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "application/json, text/plain;q=0.8",
        },
        timeout=aiohttp.ClientTimeout(total=TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT),
    )


def _sent_url(checked: str) -> Optional[yarl.URL]:
    """O ``yarl.URL`` que será enviado, conferido de novo: o que a regra aprovou como texto tem de valer também depois do parse."""
    try:
        url = yarl.URL(checked)
    except ValueError:
        return None
    ok = (
        url.scheme == "https"
        and url.user is None
        and url.password is None
        and url.raw_host in IMPORT_URL_HOSTS
        and url.explicit_port in (None, HTTPS_PORT)
        and url.is_absolute()
        and not url.raw_fragment
    )
    return url if ok else None


def _failed(host: str, reason: str) -> RuleError:
    logger.warning("Importação por link falhou [%s] (%s)", host, reason)
    return RuleError(IMPORT_FETCH_FAILED)


async def _read_body(response: aiohttp.ClientResponse, host: str) -> bytes | RuleError:
    if response.status != 200:
        return _failed(host, f"status {response.status}")
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        return _failed(host, "content-encoding")
    declared = response.headers.get("Content-Length", "")
    if declared.isdecimal() and int(declared) > PLAYLIST_FILE_MAX_BYTES:
        return RuleError(FILE_TOO_LARGE, limit=PLAYLIST_FILE_MAX_BYTES)
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(
        CHUNK_SIZE
    ):  # o cabeçalho pode mentir ou faltar: conta o que chega
        total += len(chunk)
        if total > PLAYLIST_FILE_MAX_BYTES:
            return RuleError(FILE_TOO_LARGE, limit=PLAYLIST_FILE_MAX_BYTES)
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_import(
    url: Any,
    *,
    resolve: Optional[Resolve] = None,
    session_factory: Optional[SessionFactory] = None,
    timeout: float = TOTAL_TIMEOUT,
) -> bytes | RuleError:
    """Os bytes do arquivo do link, ou ``RuleError`` (``IMPORT_URL_REFUSED``, ``FILE_TOO_LARGE``, ``IMPORT_FETCH_FAILED``).

    ``resolve`` e ``session_factory`` existem para os testes (sem rede de verdade); o padrão é o DNS do sistema e a sessão fixada.
    """
    checked = check_import_url(url)
    if isinstance(checked, RuleError):
        return checked
    target = _sent_url(checked)
    if target is None:
        return RuleError(IMPORT_URL_REFUSED)
    host = str(target.raw_host)
    try:
        async with _gate, asyncio.timeout(timeout):
            addresses = await (resolve or system_resolve)(host, HTTPS_PORT)
            if not addresses or not all(is_public_address(address) for address in addresses):
                logger.warning("Importação por link recusada [%s] (endereço não público)", host)
                return RuleError(IMPORT_URL_REFUSED)
            async with (session_factory or default_session)(addresses, host) as session:
                async with session.get(target, allow_redirects=False) as response:
                    return await _read_body(response, host)
    except TimeoutError:
        return _failed(host, "timeout")
    except Exception as exc:  # noqa: BLE001 - rede, TLS, DNS: o usuário recebe um erro genérico, o log só o tipo
        return _failed(host, type(exc).__name__)

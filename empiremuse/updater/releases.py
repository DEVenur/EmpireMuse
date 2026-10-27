"""Releases do GitHub para o fluxo Docker: quais versões estão publicadas, o digest da imagem de cada uma e o CHANGELOG.

Só stdlib e aiohttp, sem token. Uma release só é elegível se for definitiva (nem rascunho nem pré-release), imutável
(``immutable``), tiver tag estrita ``vX.Y.Z`` e o arquivo ``image-digest.txt``. O download do digest não segue
redirecionamento sozinho: cada salto é conferido (esquema e host) antes de ser pedido. Toda falha vira ``UpdateError`` com
mensagem genérica, sem URL nem detalhe; nada daqui chega ao proxy.
"""

from __future__ import annotations

import dataclasses
import json
import re
import urllib.parse

import aiohttp

from empiremuse.rules.release import Version, parse_tag
from empiremuse.updater.git_flow import UpdateError
from empiremuse.utils import branding

GITHUB_API_URL = "https://api.github.com"
RAW_URL = "https://raw.githubusercontent.com"
TIMEOUT = 10  # segundos, por pedido
ALLOWED_REDIRECT_HOSTS = ("github.com", "githubusercontent.com")  # o host ou um subdomínio dele
ALLOWED_REDIRECT_SCHEMES = ("https",)
DIGEST_ASSET = "image-digest.txt"
MAX_LISTING_BYTES = 1024 * 1024
MAX_DIGEST_BYTES = 128
MAX_CHANGELOG_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
RELEASES_PER_PAGE = 30

MSG_LISTING = "Não consegui consultar as versões publicadas agora."
MSG_DIGEST = "Não consegui conferir a imagem da versão publicada."
MSG_CHANGELOG = "Não consegui obter o histórico de mudanças desta versão."

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclasses.dataclass(frozen=True)
class Release:
    """Release elegível: a versão, a tag e o endereço do ``image-digest.txt``."""

    version: Version
    tag: str
    digest_url: str


class _TooLarge(Exception):
    """O corpo passou do limite."""


_FETCH_ERRORS = (aiohttp.ClientError, TimeoutError, OSError, ValueError, RecursionError, _TooLarge)


async def _read_limited(response: aiohttp.ClientResponse, limit: int) -> bytes:
    """Corpo da resposta, no máximo ``limit`` bytes; mais que isso levanta ``_TooLarge`` sem ler o resto."""
    received = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        received += chunk
        if len(received) > limit:
            raise _TooLarge
    return bytes(received)


def _host_allowed(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_REDIRECT_HOSTS)


def _url_allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ALLOWED_REDIRECT_SCHEMES and _host_allowed(parts.hostname)


async def _get_limited(session: aiohttp.ClientSession, url: str, limit: int) -> tuple[int, bytes, str | None]:
    """``GET`` sem seguir redirecionamento: ``(status, corpo, Location)``; só lê o corpo de uma resposta 200."""
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with session.get(url, allow_redirects=False, timeout=timeout) as response:
        location = response.headers.get("Location")
        if response.status != 200:
            return response.status, b"", location
        return response.status, await _read_limited(response, limit), location


def _eligible(item: object) -> Release | None:
    if not isinstance(item, dict):
        return None
    if item.get("draft") is not False or item.get("prerelease") is not False or item.get("immutable") is not True:
        return None
    tag = item.get("tag_name")
    version = parse_tag(tag) if isinstance(tag, str) else None
    if version is None or not isinstance(tag, str):
        return None
    for asset in item.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == DIGEST_ASSET:
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url:
                return Release(version, tag, url)
    return None


async def list_releases(session: aiohttp.ClientSession) -> list[Release]:
    """Releases elegíveis, da maior versão para a menor. Qualquer falha é ``UpdateError`` genérico."""
    url = f"{GITHUB_API_URL}/repos/{branding.GITHUB_REPO}/releases?per_page={RELEASES_PER_PAGE}"
    try:
        status, body, _ = await _get_limited(session, url, MAX_LISTING_BYTES)
        if status != 200:
            raise UpdateError(MSG_LISTING)
        data = json.loads(body.decode("utf-8"))
    except UpdateError:
        raise
    except _FETCH_ERRORS as error:
        raise UpdateError(MSG_LISTING) from error
    if not isinstance(data, list):
        raise UpdateError(MSG_LISTING)
    found = [release for release in map(_eligible, data) if release is not None]
    return sorted(found, key=lambda release: release.version, reverse=True)


async def fetch_image_digest(session: aiohttp.ClientSession, release: Release) -> str:
    """Conteúdo de ``image-digest.txt`` (``sha256:<64 hex>``). Redirecionamento só para esquema e host permitidos."""
    url = release.digest_url
    try:
        for hop in range(MAX_REDIRECTS + 1):
            if not _url_allowed(url):
                raise UpdateError(MSG_DIGEST)
            status, body, location = await _get_limited(session, url, MAX_DIGEST_BYTES)
            if status == 200:
                text = body.decode("ascii").strip()
                break
            if status not in _REDIRECT_STATUSES or not location or hop == MAX_REDIRECTS:
                raise UpdateError(MSG_DIGEST)
            url = urllib.parse.urljoin(url, location)
        else:  # pragma: no cover - o laço sempre sai por break ou por erro
            raise UpdateError(MSG_DIGEST)
    except UpdateError:
        raise
    except _FETCH_ERRORS as error:
        raise UpdateError(MSG_DIGEST) from error
    if not _DIGEST.fullmatch(text):
        raise UpdateError(MSG_DIGEST)
    return text


async def fetch_changelog(session: aiohttp.ClientSession, tag: str) -> str:
    """CHANGELOG.md da tag em ``raw.githubusercontent.com`` (até 1 MiB, utf-8 com substituição)."""
    if parse_tag(tag) is None:
        raise UpdateError(MSG_CHANGELOG)
    url = f"{RAW_URL}/{branding.GITHUB_REPO}/{tag}/CHANGELOG.md"
    try:
        status, body, _ = await _get_limited(session, url, MAX_CHANGELOG_BYTES)
    except _FETCH_ERRORS as error:
        raise UpdateError(MSG_CHANGELOG) from error
    if status != 200:
        raise UpdateError(MSG_CHANGELOG)
    return body.decode("utf-8", errors="replace")

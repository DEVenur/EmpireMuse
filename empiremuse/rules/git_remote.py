"""URL web do repositório a partir da saída de ``git remote -v`` (usada no link do commit).

Parsing por campos: prefere o remote ``origin`` e, na falta dele, o primeiro remote de ``fetch``. A URL vira
``https://host/caminho`` (ssh, scp e ``git://`` viram https), sem usuário, senha, porta ssh, sufixo ``.git`` nem barra
final. Remote local, saída vazia ou ilegível devolvem ``""`` (o chamador cai na configuração ``SOURCE_REPO``), e o mesmo
vale para uma URL com caractere de controle ou de formatação, espaço, ``)``, ``[``, ``]``, ``<``, ``>`` ou ``\\`` (fora do
colchete do host IPv6) ou com mais de ``MAX_URL_LENGTH`` caracteres: ela vira link markdown e texto de página.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

_FETCH_SUFFIX = "(fetch)"
_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.\-]+):(?!//)(?P<path>.+)$")
_WEB_SCHEMES = ("http", "https")
_REMOTE_SCHEMES = ("ssh", "git", "git+ssh", "ssh+git")
MAX_URL_LENGTH = 512
_BREAKS_LINK = frozenset(")[]<>\\")


def _web_path(path: str) -> str:
    """Caminho do repositório: sem barras nas pontas e sem o sufixo ``.git`` (só ele, nunca o ``.github``)."""
    path = path.strip().rstrip("/").removesuffix(".git").strip("/")
    return f"/{path}" if path else ""


def _host(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname else hostname


def _is_plain(text: str) -> bool:
    """Sem controle (``Cc``), formatação (``Cf``), espaço nem caractere que fecha ou quebra um link markdown ou HTML."""
    return not any(
        char.isspace() or char in _BREAKS_LINK or unicodedata.category(char) in ("Cc", "Cf") for char in text
    )


def _build_url(raw: str) -> str:
    """A URL https do repositório, ou ``""`` se ``raw`` é local ou não é um endereço remoto reconhecível."""
    scp = _SCP_LIKE.match(raw)
    if scp and "://" not in raw:
        path = _web_path(scp["path"])
        return f"https://{scp['host']}{path}" if path and _is_plain(path) else ""
    try:
        parts = urlsplit(raw)
        hostname, port = parts.hostname, parts.port
    except ValueError:
        return ""
    if not hostname or parts.scheme not in (*_WEB_SCHEMES, *_REMOTE_SCHEMES):
        return ""
    path = _web_path(parts.path)
    if not path or not _is_plain(hostname) or not _is_plain(path):
        return ""
    if parts.scheme in _WEB_SCHEMES:
        authority = f"{_host(hostname)}:{port}" if port else _host(hostname)
        return f"{parts.scheme}://{authority}{path}"
    return f"https://{_host(hostname)}{path}"


def _web_url(raw: str) -> str:
    url = _build_url(raw)
    return url if len(url) <= MAX_URL_LENGTH else ""


def _fetch_remote(line: str) -> tuple[str, str] | None:
    """``(nome, url)`` de uma linha ``nome<espaço>url<espaço>(fetch)``; ``None`` para qualquer outra.

    Cortes de texto em vez de regex com ``.*?`` entre ``\\s+``: aquela forma era quadrática (50 000 espaços levavam ~4 s).
    """
    line = line.strip()
    if not line.endswith(_FETCH_SUFFIX):
        return None
    head = line[: -len(_FETCH_SUFFIX)]
    if not head[-1:].isspace():
        return None
    parts = head.split(None, 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1].strip()


def parse_remote_web_url(output: str) -> str:
    """URL web do repositório a partir do texto de ``git remote -v``; ``""`` se não houver um remote remoto útil."""
    remotes: list[tuple[str, str]] = []
    for line in output.splitlines():
        remote = _fetch_remote(line)
        if remote:
            remotes.append(remote)
    candidates = [url for name, url in remotes if name == "origin"] or [url for _, url in remotes]
    return _web_url(candidates[0]) if candidates else ""

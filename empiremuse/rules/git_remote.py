"""URL web do repositório a partir da saída de ``git remote -v`` (usada no link do commit).

Parsing por campos: prefere o remote ``origin`` e, na falta dele, o primeiro remote de ``fetch``. A URL vira
``https://host/caminho`` (ssh, scp e ``git://`` viram https), sem usuário, senha, porta ssh, sufixo ``.git`` nem barra
final. Remote local, saída vazia ou ilegível devolvem ``""`` (o chamador cai na configuração ``SOURCE_REPO``).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_FETCH_LINE = re.compile(r"^(?P<name>\S+)\s+(?P<url>\S.*?)\s+\(fetch\)\s*$")
_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.\-]+):(?!//)(?P<path>.+)$")
_WEB_SCHEMES = ("http", "https")
_REMOTE_SCHEMES = ("ssh", "git", "git+ssh", "ssh+git")


def _web_path(path: str) -> str:
    """Caminho do repositório: sem barras nas pontas e sem o sufixo ``.git`` (só ele, nunca o ``.github``)."""
    path = path.strip().rstrip("/").removesuffix(".git").strip("/")
    return f"/{path}" if path else ""


def _host(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname else hostname


def _web_url(raw: str) -> str:
    """A URL https do repositório, ou ``""`` se ``raw`` é local ou não é um endereço remoto reconhecível."""
    scp = _SCP_LIKE.match(raw)
    if scp and "://" not in raw:
        path = _web_path(scp["path"])
        return f"https://{scp['host']}{path}" if path else ""
    try:
        parts = urlsplit(raw)
        hostname, port = parts.hostname, parts.port
    except ValueError:
        return ""
    if not hostname or parts.scheme not in (*_WEB_SCHEMES, *_REMOTE_SCHEMES):
        return ""
    path = _web_path(parts.path)
    if not path:
        return ""
    if parts.scheme in _WEB_SCHEMES:
        authority = f"{_host(hostname)}:{port}" if port else _host(hostname)
        return f"{parts.scheme}://{authority}{path}"
    return f"https://{_host(hostname)}{path}"


def parse_remote_web_url(output: str) -> str:
    """URL web do repositório a partir do texto de ``git remote -v``; ``""`` se não houver um remote remoto útil."""
    remotes: list[tuple[str, str]] = []
    for line in output.splitlines():
        match = _FETCH_LINE.match(line.strip())
        if match:
            remotes.append((match["name"], match["url"]))
    candidates = [url for name, url in remotes if name == "origin"] or [url for _, url in remotes]
    return _web_url(candidates[0]) if candidates else ""

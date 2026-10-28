"""Arte de marca servida de ``assets/brand/`` por uma lista fechada de arquivos."""

from __future__ import annotations

import asyncio
import hashlib
import stat

import tornado.web

from empiremuse.paths import PROJECT_DIR
from empiremuse.panel.handlers.base import PanelHandler

BRAND_DIR = PROJECT_DIR / "assets" / "brand"
BRAND_FILES = {
    "logo.svg": "image/svg+xml",
    "avatar.png": "image/png",
    "favicon.ico": "image/x-icon",
}
BRAND_ROUTE = r"/painel/marca/(logo\.svg|avatar\.png|favicon\.ico)"
BRAND_CACHE_CONTROL = "public, max-age=3600"
ETAG_HEX_LENGTH = 32

# a rota é pública e sem limite de taxa: cada arquivo é lido do disco UMA vez e o resto das requisições usa a memória (e o 304 do ETag)
_cache: dict[str, tuple[bytes, str]] = {}


def _load(name: str) -> tuple[bytes, str]:
    """Bytes e ETag do arquivo da lista fechada; só arquivo regular (nunca link simbólico)."""
    path = BRAND_DIR / name

    if not stat.S_ISREG(path.lstat().st_mode):
        raise FileNotFoundError(name)

    data = path.read_bytes()

    return data, f'"{hashlib.sha256(data).hexdigest()[:ETAG_HEX_LENGTH]}"'


class BrandHandler(PanelHandler):
    async def get(self, name: str) -> None:
        entry = _cache.get(name)

        if entry is None:
            try:
                entry = await asyncio.to_thread(_load, name)
            except OSError:
                raise tornado.web.HTTPError(404)

            entry = _cache.setdefault(name, entry)

        data, etag = entry
        self.set_header("Content-Type", BRAND_FILES[name])
        self.set_header("Cache-Control", BRAND_CACHE_CONTROL)
        self.set_header("Etag", etag)

        if self.check_etag_header():
            self.set_status(304)
            self.finish()
            return

        self.finish(data)

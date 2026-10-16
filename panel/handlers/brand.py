"""Arte de marca servida de ``assets/brand/`` por uma lista fechada de arquivos."""
from __future__ import annotations

import asyncio
from pathlib import Path

from panel.handlers.base import PanelHandler

BRAND_DIR = Path(__file__).resolve().parents[2] / "assets" / "brand"
BRAND_FILES = {
    "logo.svg": "image/svg+xml",
    "avatar.png": "image/png",
}
BRAND_ROUTE = r"/painel/marca/(logo\.svg|avatar\.png)"
BRAND_CACHE_CONTROL = "public, max-age=3600"


class BrandHandler(PanelHandler):
    async def get(self, name: str) -> None:
        data = await asyncio.to_thread((BRAND_DIR / name).read_bytes)
        self.set_header("Content-Type", BRAND_FILES[name])
        self.set_header("Cache-Control", BRAND_CACHE_CONTROL)
        self.finish(data)

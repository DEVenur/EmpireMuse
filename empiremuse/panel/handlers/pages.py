"""Páginas básicas do painel: redirecionamento, índice e saúde."""

from __future__ import annotations

from empiremuse.panel.handlers.base import PanelHandler

INDEX_PATH = "/painel/"


class RedirectToIndexHandler(PanelHandler):
    def get(self) -> None:
        self.redirect(INDEX_PATH, permanent=True)


class IndexHandler(PanelHandler):
    def get(self) -> None:
        self.render_page("index.html")


class HealthHandler(PanelHandler):
    def get(self) -> None:
        self.set_header("Cache-Control", "no-store")
        self.write({"ok": True})

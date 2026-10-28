"""Página de status pública (``GET /``) — o logo da marca (SVG de ~6 MB) nunca vai embutido no HTML.

Embutir em ``data:`` faz cada GET público carregar o arquivo inteiro. A página referencia o logo por URL (rota de marca com cache ou arquivo estático
pequeno) e continua renderizando se o arquivo faltar. Reaproveita o servidor real de ``test_status_page.py``.
"""

import re

import pytest

from empiremuse import web_app
from empiremuse.utils import branding
from tests.panel.test_status_page import READY, get_index, page

pytestmark = pytest.mark.critical


LIMITE_DA_PAGINA = 200_000  # a página sem logo tem poucas dezenas de KB; o logo embutido passa de 8 MB
SRC_DO_LOGO = re.compile(r'<img[^>]+class="logo"[^>]+src="([^"]*)"|<img[^>]+src="([^"]*)"[^>]+class="logo"')


def src_do_logo(corpo: str) -> str | None:
    achado = SRC_DO_LOGO.search(corpo)
    return (achado.group(1) or achado.group(2)) if achado else None


class TestLogoPorUrl:
    def test_the_page_stays_small_and_embeds_no_data_uri(self, monkeypatch):
        resposta = get_index(monkeypatch, bots=READY)

        assert resposta.code == 200
        assert len(resposta.body) < LIMITE_DA_PAGINA, f"{len(resposta.body)} bytes: o logo parece embutido"
        corpo = resposta.body.decode()
        assert "base64," not in corpo and "data:image" not in corpo

    def test_the_logo_is_the_public_raw_url_of_the_small_png_and_never_under_painel(self, monkeypatch):
        corpo = page(monkeypatch, bots=READY)

        src = src_do_logo(corpo)

        assert src == branding.asset_url("logo-256.png")
        assert src.startswith("https://raw.githubusercontent.com/") and src.endswith("/assets/brand/logo-256.png")
        assert "/painel" not in src and "logo.svg" not in corpo

    def test_the_page_still_renders_without_the_logo_when_asset_url_fails(self, monkeypatch):
        def falha(nome):
            raise ValueError(nome)

        monkeypatch.setattr(web_app.branding, "asset_url", falha)

        resposta = get_index(monkeypatch, bots=READY)

        corpo = resposta.body.decode()
        assert resposta.code == 200 and len(resposta.body) < LIMITE_DA_PAGINA
        assert '<img class="logo"' not in corpo and "data:image" not in corpo and "Bot Um" in corpo

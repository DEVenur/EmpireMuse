"""Página de status pública (``GET /``) — o logo da marca (SVG de ~6 MB) nunca vai embutido no HTML.

Embutir em ``data:`` faz cada GET público carregar o arquivo inteiro. A página referencia o logo por URL (rota de marca com cache ou arquivo estático
pequeno) e continua renderizando se o arquivo faltar. Reaproveita o servidor real de ``test_status_page.py``.
"""

import re

import pytest

from empiremuse import paths, web_app
from tests.panel.test_status_page import READY, get_index, page

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def logo_sem_cache_de_outro_teste(monkeypatch):
    """O logo foi guardado em memória por um teste anterior (implementação antiga): cada teste começa sem esse resíduo."""
    monkeypatch.setattr(web_app, "_logo_cache", None, raising=False)


LIMITE_DA_PAGINA = 200_000  # a página sem logo tem poucas dezenas de KB; o logo embutido passa de 8 MB
SRC_DO_LOGO = re.compile(r'<img[^>]+class="logo"[^>]+src="([^"]*)"|<img[^>]+src="([^"]*)"[^>]+class="logo"')


def src_do_logo(corpo: str) -> str | None:
    achado = SRC_DO_LOGO.search(corpo)
    return (achado.group(1) or achado.group(2)) if achado else None


class TestLogoPorUrl:
    def test_a_same_origin_logo_url_is_served_by_the_same_server(self, monkeypatch):
        src = src_do_logo(page(monkeypatch, bots=READY, PANEL_ENABLED=True))

        if src is None or not src.startswith("/"):
            pytest.skip("logo hospedado fora (URL absoluta): nada a servir aqui")

        resposta = get_index(monkeypatch, bots=READY, PANEL_ENABLED=True, path=src)

        assert resposta.code == 200 and resposta.headers["Content-Type"] == "image/png"

    def test_the_page_stays_small_and_embeds_no_data_uri(self, monkeypatch):
        resposta = get_index(monkeypatch, bots=READY)

        assert resposta.code == 200
        assert len(resposta.body) < LIMITE_DA_PAGINA, f"{len(resposta.body)} bytes: o logo parece embutido"
        corpo = resposta.body.decode()
        assert "base64," not in corpo and "data:image" not in corpo

    def test_the_logo_is_referenced_by_a_url_not_by_content(self, monkeypatch):
        corpo = page(monkeypatch, bots=READY)

        src = src_do_logo(corpo)

        assert src and not src.startswith("data:") and len(src) < 300
        assert src.endswith("/logo-256.png"), src  # o PNG pequeno, nunca o logo.svg de 6 MB
        assert src.startswith("/") or src.startswith(("https://",)), src

    def test_the_page_still_renders_when_the_logo_file_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)

        resposta = get_index(monkeypatch, bots=READY)

        assert resposta.code == 200 and len(resposta.body) < LIMITE_DA_PAGINA
        assert b"data:image" not in resposta.body and b"Bot Um" in resposta.body

    def test_the_page_size_does_not_depend_on_the_logo_size(self, monkeypatch, tmp_path):
        normal = len(get_index(monkeypatch, bots=READY).body)
        pasta = tmp_path / "assets" / "brand"
        pasta.mkdir(parents=True)
        (pasta / "logo.svg").write_bytes(
            b"<svg xmlns='http://www.w3.org/2000/svg'>" + b"<!--x-->" * 400_000 + b"</svg>"
        )
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)

        com_logo_grande = len(get_index(monkeypatch, bots=READY).body)

        assert abs(com_logo_grande - normal) < 2_000

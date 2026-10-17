"""Fase 2, Trilha B — página de status `GET /` (IndexHandler de web_app.py) na identidade "Nebulosa".

Contrato: BRIEFING-FASE2.md (Trilha B). Parte VERDE (caracterização do que já existe e deve continuar): 200, mensagem do
pool, bots com falha/pendentes/prontos, convite, "aplicação será reiniciada", app de RPC, prefixo, commit, funciona com o
painel desligado. Parte RED: logo, paleta, link do painel só com o painel ligado, servidor de suporte, crédito GPL-2.0 ao
upstream, lang pt-BR, viewport, acessibilidade, texto externo escapado e nenhum recurso externo novo (nada de CDN).
Interpretações: .qa-fase2-interp.txt. Os testes sobem o servidor real (run_app) numa porta livre e usam HTTP de verdade.
"""

import asyncio
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.websocket

from tests.panel.helpers import local_config, require
from empiremuse.utils import branding

HOSTILE = "<script>alert(1)</script>"
HOSTILE_IMG = "<img src=x onerror=alert(2)>"
NEBULOSA = ("#0b0a1f", "#8b5cf6")
ALLOWED_HOSTS = {
    "discord.com",
    "discordapp.com",
    "cdn.discordapp.com",
    "discord.gg",
    "github.com",
    "raw.githubusercontent.com",
}  # convite, avatar, suporte e repositórios
CDN_MARKERS = (
    "googleapis.com",
    "gstatic.com",
    "jsdelivr",
    "unpkg.com",
    "cdnjs",
    "bootstrapcdn",
    "fontawesome",
    "tailwindcss.com",
    "@import",
)


class _User:
    def __init__(self, bot_id, name):
        self.id, self._name = bot_id, name
        avatar = SimpleNamespace(url=f"https://cdn.discordapp.com/avatars/{bot_id}/avatar.png")
        self.display_avatar = SimpleNamespace(replace=lambda **kwargs: avatar)

    def __str__(self):
        return self._name


def make_bot(bot_id, name, *, ready=True, guilds=3):
    async def wait_until_ready():
        return None

    return SimpleNamespace(
        user=_User(bot_id, name),
        guilds=[object()] * guilds,
        identifier=f"id-{name}",
        config={"INVITE_PERMISSIONS": 332892794064},
        is_ready=lambda: ready,
        wait_until_ready=wait_until_ready,
    )


def make_pool(config, bots=(), failed=None, killing=False, commit=""):
    config = {"ENABLE_RPC_AUTH": False, "DEFAULT_PREFIX": "!", "INVITE_PERMISSIONS": 332892794064, **config}
    return SimpleNamespace(
        bots=list(bots),
        database=None,
        config=config,
        killing_state=killing,
        failed_bots=dict(failed or {}),
        commit=commit,
        remote_git_url="https://github.com/x/y",
    )


def get_index(
    monkeypatch, *, message="", bots=(), failed=None, killing=False, commit="", path="/", ws=False, **overrides
):
    web_app = require("empiremuse.web_app")
    config = local_config(PORT=0, **overrides)
    pool = make_pool(config, bots, failed, killing, commit)
    real = tornado.httpserver.HTTPServer
    seen = {}

    class Recorder(real):
        def listen(self, port, address=""):
            sock, seen["port"] = tornado.testing.bind_unused_port()
            self.add_socket(sock)

    monkeypatch.setattr(web_app.tornado.httpserver, "HTTPServer", Recorder)

    async def main():
        web_app.run_app(pool, message, pool.config)
        if ws:
            connection = await tornado.websocket.websocket_connect(f"ws://127.0.0.1:{seen['port']}/ws")
            connection.close()
            return connection
        client = tornado.httpclient.AsyncHTTPClient()
        try:
            return await client.fetch(
                f"http://127.0.0.1:{seen['port']}{path}", raise_error=False, follow_redirects=False
            )
        finally:
            client.close()

    return asyncio.run(main())


def page(monkeypatch, **kwargs) -> str:
    response = get_index(monkeypatch, **kwargs)
    assert response.code == 200, f"GET / deveria ser 200, veio {response.code}"
    return response.body.decode()


def links(body):
    return re.findall(r'(?:href|src)="([^"]+)"', body)


READY = (make_bot(111, "Bot Um", guilds=7),)


# ============================================================================ caracterização (VERDE)


class TestExistingBehaviourStays:
    def test_ok_html_with_and_without_the_panel_and_without_panel_static(self, monkeypatch):
        for panel in (True, False):
            response = get_index(monkeypatch, PANEL_ENABLED=panel)
            assert response.code == 200 and "text/html" in response.headers["Content-Type"]
            assert "/painel/static" not in response.body.decode(), "a página não pode depender de /painel/static"

    def test_pool_message_is_shown_and_newlines_become_line_breaks(self, monkeypatch):
        body = page(monkeypatch, message="Aviso um\nAviso dois")
        assert "Aviso um" in body and "Aviso dois" in body
        assert re.search(r"Aviso um\s*<\s*/?br\s*/?>\s*Aviso dois", body, re.IGNORECASE)

    def test_restart_notice_replaces_the_page(self, monkeypatch):
        assert "A aplicação será reiniciada em breve" in page(monkeypatch, killing=True, bots=READY)

    def test_ready_bot_has_name_guild_count_avatar_and_invite_with_the_configured_permissions(self, monkeypatch):
        body = page(monkeypatch, bots=READY)
        assert "Bot Um" in body and re.search(r"\b7\b", body)
        assert "https://cdn.discordapp.com/avatars/111/avatar.png" in body
        invite = next((u for u in links(body) if "oauth2/authorize" in u), "").replace("&amp;", "&")
        assert "client_id=111" in invite and "permissions=332892794064" in invite
        assert "applications.commands" in invite

    def test_pending_and_failed_bots_are_reported(self, monkeypatch):
        pending = make_bot(222, "Bot Dois", ready=False)
        body = page(monkeypatch, bots=(pending,), failed={"TOKEN_BOT_9": "Token inválido"})
        assert "id-Bot Dois" in body and "Recarregue a página" in body
        assert "TOKEN_BOT_9" in body and "Token inválido" in body

    def test_rpc_app_link_prefix_and_commit_stay(self, monkeypatch):
        body = page(monkeypatch, commit="abcdef1234567")
        assert branding.RPC_APP_RELEASES_URL in body and "Prefixo padrão: !" in body
        assert "/commit/abcdef1234567" in body and "abcdef1" in body
        assert 'id="url"' in body, "o endereço do relé RPC (ws) continua visível para colar no app"

    def test_rpc_token_hint_only_with_rpc_auth(self, monkeypatch):
        on = page(monkeypatch, ENABLE_RPC_AUTH=True)
        off = page(monkeypatch, ENABLE_RPC_AUTH=False)
        assert "/rich_presence" in on and "/rich_presence" not in off


# ============================================================================ identidade "Nebulosa" (RED)


class TestNebulosaIdentity:
    def test_has_the_brand_logo_without_depending_on_panel_static(self, monkeypatch):
        body = page(monkeypatch, bots=READY, PANEL_ENABLED=False)
        brand_img = any(
            u.startswith("data:image/") or u.startswith(branding.ASSETS_BASE_URL)
            for u in re.findall(r'<img[^>]+src="([^"]+)"', body)
        )
        assert "<svg" in body or brand_img, "a página precisa exibir o logo da marca (SVG embutido ou asset da marca)"
        assert "/painel/static" not in body

    def test_uses_the_nebulosa_palette(self, monkeypatch):
        body = page(monkeypatch, bots=READY).lower()
        css = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", body, re.DOTALL))
        assert all(color in css for color in NEBULOSA), f"paleta Nebulosa ausente do CSS embutido: {NEBULOSA}"

    def test_title_and_main_heading_name_the_bot(self, monkeypatch):
        body = page(monkeypatch, bots=READY)
        assert re.search(r"<title>[^<]*EmpireMuse[^<]*</title>", body)
        assert re.search(r"<h1[^>]*>.*?EmpireMuse.*?</h1>", body, re.DOTALL)

    def test_language_charset_and_responsive_viewport(self, monkeypatch):
        body = page(monkeypatch)
        assert re.search(r'<html[^>]+lang="pt-BR"', body)
        assert re.search(r'<meta[^>]+charset="?utf-8', body, re.IGNORECASE)
        assert re.search(r'<meta[^>]+name="viewport"[^>]+content="[^"]*width=device-width', body)

    def test_is_accessible_landmarks_alt_text_and_no_invalid_image_attributes(self, monkeypatch):
        body = page(monkeypatch, bots=READY)
        assert "<main" in body
        images = re.findall(r"<img\b[^>]*>", body)
        assert images, "o avatar do bot é exibido"
        for image in images:
            assert re.search(r'alt="[^"]+"', image), f"imagem sem texto alternativo: {image}"
            assert "weight=" not in image, "atributo inválido (weight): use width/height"

    def test_is_responsive_by_css(self, monkeypatch):
        body = page(monkeypatch, bots=READY)
        assert "@media" in body or "flex-wrap" in body or "auto-fit" in body or "minmax(" in body


class TestLinks:
    def test_panel_link_only_when_the_panel_is_on(self, monkeypatch):
        assert 'href="/painel/"' in page(monkeypatch, PANEL_ENABLED=True)
        assert "/painel" not in page(monkeypatch, PANEL_ENABLED=False)

    def test_no_panel_link_when_the_panel_config_is_invalid(self, monkeypatch):
        assert "/painel" not in page(monkeypatch, PANEL_ENABLED=True, PANEL_BASE_URL="lixo")

    def test_support_server_link(self, monkeypatch):
        assert branding.SUPPORT_SERVER_URL in links(page(monkeypatch))

    def test_gpl_credit_to_the_upstream_with_a_link(self, monkeypatch):
        body = page(monkeypatch)
        assert "GPL-2.0" in body and branding.UPSTREAM_NAME in body and branding.UPSTREAM_AUTHOR in body
        assert branding.UPSTREAM_URL in links(body)
        assert branding.REPO_URL in links(body), "link do repositório do EmpireMuse"

    def test_external_links_open_safely(self, monkeypatch):
        body = page(monkeypatch, bots=READY)
        for tag in re.findall(r'<a\b[^>]*target="_blank"[^>]*>', body):
            assert "noopener" in tag, f"target=_blank sem rel=noopener: {tag}"


class TestNoNewExternalResources:
    def test_only_known_hosts_and_no_cdn_scripts_fonts_or_styles(self, monkeypatch):
        body = page(monkeypatch, bots=READY, PANEL_ENABLED=True, commit="abcdef1234567")
        lowered = body.lower()
        assert not [m for m in CDN_MARKERS if m in lowered], "nada de CDN/fontes externas"
        assert not re.search(r"<script[^>]+src=", lowered), "nenhum script externo"
        assert not re.search(r"<link[^>]+rel=\"?stylesheet", lowered), "estilos ficam embutidos"
        hosts = {
            urlsplit(u.replace("&amp;", "&")).hostname for u in re.findall(r'(?:href|src)="(https?://[^"]+)"', body)
        }
        assert hosts <= ALLOWED_HOSTS, f"hosts não previstos: {hosts - ALLOWED_HOSTS}"


class TestExternalTextIsEscaped:
    def test_message_bot_names_failures_identifiers_and_prefix_are_escaped(self, monkeypatch):
        pending = make_bot(222, "ok", ready=False)
        pending.identifier = HOSTILE_IMG
        bots = (make_bot(111, HOSTILE, guilds=1), pending)
        body = page(
            monkeypatch,
            message=f"Aviso {HOSTILE}",
            bots=bots,
            failed={HOSTILE_IMG: HOSTILE},
            DEFAULT_PREFIX=HOSTILE_IMG,
        )
        assert "<script>alert(1)" not in body and "<img src=x onerror" not in body, "texto externo sem escape (XSS)"
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert "&lt;img src=x onerror=alert(2)&gt;" in body


# ============================================================================ BAIXO-1: cabeçalhos de segurança de `/`


class TestSecurityHeadersOnIndex:
    """Contrato do MAESTRO (item 8): nosniff, X-Frame-Options DENY (ou frame-ancestors), Referrer-Policy — sem quebrar
    /ws nem o painel. CSP completa não serve: a página usa <style> e <script> embutidos."""

    def test_nosniff_frame_denial_and_referrer_policy(self, monkeypatch):
        headers = get_index(monkeypatch, bots=READY).headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        csp = headers.get("Content-Security-Policy", "")
        assert headers.get("X-Frame-Options") == "DENY" or re.search(r"frame-ancestors\s+'none'", csp), (
            "a página não pode ser embutida em iframe (clickjacking)"
        )
        assert headers.get("Referrer-Policy") in {
            "no-referrer",
            "same-origin",
            "strict-origin",
            "strict-origin-when-cross-origin",
            "origin-when-cross-origin",
        }

    def test_headers_also_present_when_restarting_and_with_the_panel_off(self, monkeypatch):
        for kwargs in ({"killing": True}, {"PANEL_ENABLED": False}):
            headers = get_index(monkeypatch, bots=READY, **kwargs).headers
            assert headers.get("X-Content-Type-Options") == "nosniff", kwargs

    def test_a_csp_if_present_still_allows_the_inline_style_and_script_of_the_page(self, monkeypatch):
        csp = get_index(monkeypatch, bots=READY).headers.get("Content-Security-Policy", "")
        if "script-src" in csp:
            assert "'unsafe-inline'" in csp or "nonce-" in csp or "sha256-" in csp
        if "style-src" in csp:
            assert "'unsafe-inline'" in csp or "nonce-" in csp or "sha256-" in csp

    def test_websocket_relay_still_connects(self, monkeypatch):
        connection = get_index(monkeypatch, ws=True)
        assert connection is not None

    def test_panel_keeps_its_own_stricter_headers(self, monkeypatch):
        from tests.panel.helpers import EXPECTED_SECURITY_HEADERS

        response = get_index(monkeypatch, path="/painel/", PANEL_ENABLED=True)
        for name, want in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == want, name

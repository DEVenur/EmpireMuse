"""Aplicação do painel: rotas, 404 genérico, cabeçalhos, cookie _xsrf e marca."""

import json

import tornado.web
from tornado.testing import AsyncHTTPTestCase

from tests.panel.helpers import (
    BRAND_DIR,
    EXPECTED_CSP,
    EXPECTED_SECURITY_HEADERS,
    ROOT,
    XSRF_META_RE,
    fake_pool,
    https_config,
    load_settings,
    local_config,
    require,
)

HEADER_PATHS = [
    "/painel",
    "/painel/",
    "/painel/saude",
    "/painel/nao-existe",
    "/painel/marca/logo.svg",
    "/painel/marca/avatar.png",
    "/painel/static/vendor/htmx.min.js",
    "/painel/static/nao-existe.css",
]


class _Main(tornado.web.RequestHandler):
    def get(self, *_):
        self.write("main-app")


class PanelTestBase(AsyncHTTPTestCase):
    config_factory = staticmethod(local_config)

    def setUp(self):
        require("panel")
        super().setUp()

    def get_app(self):
        panel = require("panel")
        self.settings = load_settings(self.config_factory())
        self.panel_app = panel.build_panel_app(fake_pool(), self.settings)
        return panel.make_router(tornado.web.Application([(r"/", _Main)]), self.panel_app)

    def get_page(self, path="/painel/"):
        return self.fetch(path, follow_redirects=False)

    @staticmethod
    def assert_all(cases, check):
        """Executa `check(case)` para todos os casos e reporta TODAS as falhas (AsyncHTTPTestCase é unittest:
        parametrize do pytest não injeta argumentos em métodos de TestCase)."""
        failures = []
        for case in cases:
            try:
                check(case)
            except AssertionError as exc:
                failures.append(f"{case!r}: {exc}")
        assert not failures, f"{len(failures)} caso(s) falharam:\n  " + "\n  ".join(failures)


class PanelRoutesTest(PanelTestBase):
    def test_painel_without_slash_redirects_permanently(self):
        response = self.get_page("/painel")
        assert response.code == 301
        assert response.headers["Location"].endswith("/painel/")

    def test_index_page_is_html_with_login_button_and_logo(self):
        response = self.get_page()
        body = response.body.decode()
        assert response.code == 200
        assert response.headers["Content-Type"].startswith("text/html")
        assert "Entrar com Discord" in body
        assert "/painel/login" in body
        assert "/painel/marca/logo.svg" in body

    def test_health_returns_ok_json(self):
        response = self.get_page("/painel/saude")
        assert response.code == 200
        assert response.headers["Content-Type"].startswith("application/json")
        assert json.loads(response.body) == {"ok": True}

    def test_main_app_root_is_untouched(self):
        assert self.get_page("/").body == b"main-app"

    def test_unknown_route_returns_generic_html_404(self):
        response = self.get_page("/painel/nao-existe")
        body = response.body.decode()
        assert response.code == 404
        assert response.headers["Content-Type"].startswith("text/html")
        assert "404" in body
        for leak in ("Traceback", "tornado", 'File "', ROOT.as_posix()):
            assert leak not in body, f"a página de erro vaza detalhes internos: {leak!r}"

    def test_app_runs_without_debug_and_with_xsrf_protection(self):
        assert not self.panel_app.settings.get("debug", False)
        assert self.panel_app.settings.get("xsrf_cookies") is True

    def test_vendored_static_files_are_served(self):
        def check(case):
            path, kind = case
            response = self.get_page(path)
            assert response.code == 200, f"status {response.code}"
            assert kind in response.headers["Content-Type"], response.headers["Content-Type"]

        self.assert_all(
            [("/painel/static/vendor/htmx.min.js", "javascript"), ("/painel/static/vendor/pico.min.css", "css")], check
        )


class PanelSecurityHeadersTest(PanelTestBase):
    def test_security_headers_on_every_response(self):
        def check(path):
            headers = self.get_page(path).headers
            for name, value in EXPECTED_SECURITY_HEADERS.items():
                assert headers.get(name) == value, f"cabeçalho {name} incorreto: {headers.get(name)!r}"

        self.assert_all(HEADER_PATHS, check)

    def test_csp_has_no_unsafe_directives(self):
        csp = self.get_page().headers["Content-Security-Policy"]
        assert csp == EXPECTED_CSP
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp

    def test_html_pages_are_not_cached(self):
        def check(path):
            assert self.get_page(path).headers.get("Cache-Control") == "no-store"

        self.assert_all(["/painel/", "/painel/nao-existe"], check)

    def test_hsts_is_absent_without_https(self):
        assert "Strict-Transport-Security" not in self.get_page().headers


class PanelHttpsTest(PanelTestBase):
    config_factory = staticmethod(https_config)

    def test_hsts_is_sent_when_base_url_is_https(self):
        assert "max-age=31536000" in self.get_page().headers.get("Strict-Transport-Security", "")

    def test_xsrf_cookie_is_secure_when_https(self):
        cookie = _xsrf_cookie(self.get_page())
        assert "secure" in cookie.lower().split("; ")


def _xsrf_cookie(response) -> str:
    cookies = [c for c in response.headers.get_list("Set-Cookie") if c.startswith("_xsrf=")]
    assert cookies, "a página inicial deve definir o cookie _xsrf"
    return cookies[0]


class PanelXsrfTest(PanelTestBase):
    def test_xsrf_cookie_flags_for_local_development(self):
        flags = [part.strip().lower() for part in _xsrf_cookie(self.get_page()).split(";")]
        assert "httponly" in flags
        assert "samesite=lax" in flags
        assert "secure" not in flags, "PANEL_INSECURE_COOKIES=true em localhost não deve marcar Secure"

    def test_index_exposes_xsrf_token_in_meta_tag(self):
        match = XSRF_META_RE.search(self.get_page().body.decode())
        assert match and len(match.group(1)) > 10, '<meta name="xsrf-token" content="..."> ausente ou vazio'

    def test_post_without_token_is_forbidden(self):
        def check(path):
            code = self.fetch(path, method="POST", body="", follow_redirects=False).code
            assert code == 403, f"status {code}"

        self.assert_all(["/painel/", "/painel/saude"], check)

    def test_post_with_valid_token_header_passes_xsrf_check(self):
        page = self.get_page()
        token = XSRF_META_RE.search(page.body.decode()).group(1)
        cookie = _xsrf_cookie(page).split(";")[0]
        response = self.fetch(
            "/painel/", method="POST", body="", follow_redirects=False, headers={"X-XSRFToken": token, "Cookie": cookie}
        )
        assert response.code != 403 and response.code < 500, f"status inesperado: {response.code}"


class PanelBrandTest(PanelTestBase):
    def test_allowed_brand_files_are_served(self):
        def check(case):
            name, mime = case
            response = self.get_page(f"/painel/marca/{name}")
            assert response.code == 200, f"status {response.code}"
            assert response.headers["Content-Type"].startswith(mime), response.headers["Content-Type"]
            assert response.body == (BRAND_DIR / name).read_bytes(), "conteúdo difere de assets/brand/"

        self.assert_all([("logo.svg", "image/svg+xml"), ("avatar.png", "image/png")], check)

    BRAND_BLOCKED_PATHS = [
        "/painel/marca/banner.png",  # existe em assets/brand/, mas fora da lista fechada
        "/painel/marca/",
        "/painel/marca",
        "/painel/marca/LOGO.SVG",
        "/painel/marca/logo.svg/",
        "/painel/marca/logo.svg%00.png",
        "/painel/marca/..%2fanother",
        "/painel/marca/..%2f..%2fempiremuse%2fconfig_loader.py",
        "/painel/marca/%2e%2e/%2e%2e/LICENSE",
        "/painel/marca/..%5c..%5cLICENSE",
        "/painel/marca/../../empiremuse/config_loader.py",
        "/painel/marca/%2e%2e%2f%2e%2e%2fLICENSE",
        "/painel/marca/sub/logo.svg",
    ]

    def test_brand_route_is_a_closed_list_without_path_traversal(self):
        def check(path):
            response = self.get_page(path)
            assert response.code in (404, 301), f"status {response.code}"
            assert b"GNU GENERAL PUBLIC LICENSE" not in response.body
            assert b"DEFAULT_CONFIG" not in response.body

        self.assert_all(self.BRAND_BLOCKED_PATHS, check)

    STATIC_BLOCKED_PATHS = [
        "/painel/static/../../empiremuse/config_loader.py",
        "/painel/static/%2e%2e/%2e%2e/LICENSE",
        "/painel/static/..%2f..%2fempiremuse%2fconfig_loader.py",
    ]

    def test_static_route_blocks_path_traversal(self):
        def check(path):
            response = self.get_page(path)
            assert response.code in (403, 404), f"status {response.code}"
            assert b"GNU GENERAL PUBLIC LICENSE" not in response.body
            assert b"DEFAULT_CONFIG" not in response.body

        self.assert_all(self.STATIC_BLOCKED_PATHS, check)

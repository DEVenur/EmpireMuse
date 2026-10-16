"""Endurecimento do login (Etapa 2, validação): client_id/503, Retry-After, logs sem query string,
revogação mesmo em erro inesperado, cookies sem aspas."""
import logging
from types import SimpleNamespace

import tornado.web

from tests.panel.helpers import COOKIE_SECRET, EXPECTED_SECURITY_HEADERS, OAUTH_SECRET, fake_pool, local_config, require
from tests.panel.helpers_login import ACCESS_TOKEN, CODE, authorize_params, build_app, set_cookie_headers
from tests.panel.test_login_flow import SESSION_COOKIE, LoginBase

PANEL_APP_ID = "111111111111111111"
BOT_USER_ID = "222222222222222222"
CONFIGURED_ID = "999999999999999999"


class ClientIdBase(LoginBase):
    """App SEM cliente OAuth injetado: o client_id é resolvido no primeiro login."""
    pool_bots: list = []
    config_overrides: dict = {}

    def config_factory(self):
        return local_config(**self.config_overrides)

    def get_app(self):
        panel = require("panel")
        self.pool = SimpleNamespace(bots=list(self.pool_bots), database=None)
        settings = require("panel.settings").load_panel_settings(self.config_factory())
        self.settings = settings
        app = panel.build_panel_app(self.pool, settings, clock=self.clock)
        return panel.make_router(tornado.web.Application([]), app)


class ConfiguredClientIdTest(ClientIdBase):
    config_overrides = {"PANEL_OAUTH_CLIENT_ID": CONFIGURED_ID}
    pool_bots = [SimpleNamespace(application_id=PANEL_APP_ID, user=SimpleNamespace(id=BOT_USER_ID))]

    def test_configured_client_id_wins_over_the_pool(self):
        _, params = self.start_login(self.browser())
        assert params["client_id"] == CONFIGURED_ID


class ApplicationIdFallbackTest(ClientIdBase):
    pool_bots = [SimpleNamespace(application_id=PANEL_APP_ID, user=SimpleNamespace(id=BOT_USER_ID))]

    def test_empty_client_id_uses_first_bot_application_id(self):
        _, params = self.start_login(self.browser())
        assert params["client_id"] == PANEL_APP_ID


class UserIdFallbackTest(ClientIdBase):
    pool_bots = [SimpleNamespace(application_id=None, user=SimpleNamespace(id=int(BOT_USER_ID)))]

    def test_without_application_id_falls_back_to_bot_user_id(self):
        _, params = self.start_login(self.browser())
        assert params["client_id"] == BOT_USER_ID


class NoClientIdTest(ClientIdBase):
    def test_login_returns_503_friendly_page_when_no_client_id_is_available(self):
        response = self.browser().get("/painel/login")
        body = response.body.decode()
        assert response.code == 503
        assert response.headers["Content-Type"].startswith("text/html")
        for leak in ("Traceback", "client_id", OAUTH_SECRET, COOKIE_SECRET):
            assert leak not in body
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name

    def test_503_does_not_set_attempt_cookie(self):
        response = self.browser().get("/painel/login")
        assert not set_cookie_headers(response, "painel_login")

    def test_client_id_is_resolved_lazily_once_a_bot_is_ready(self):
        browser = self.browser()
        assert browser.get("/painel/login").code == 503
        self.pool.bots.append(SimpleNamespace(application_id=PANEL_APP_ID, user=None))
        self.clock.advance(61)
        response = browser.get("/painel/login")
        assert response.code == 302 and authorize_params(response.headers["Location"])["client_id"] == PANEL_APP_ID


class RetryAfterTest(LoginBase):
    def test_rate_limited_responses_carry_retry_after_60(self):
        for path in ("/painel/login", "/painel/callback?code=x&state=y"):
            browser = self.browser()
            last = None
            for _ in range(40):
                last = browser.get(path)
                if last.code == 429:
                    break
            assert last.code == 429, path
            assert last.headers.get("Retry-After") == "60", f"{path}: Retry-After={last.headers.get('Retry-After')!r}"


class AccessLogTest(LoginBase):
    def assert_no_oauth_material(self, state):
        text = self.caplog.text
        for secret in (CODE, state, ACCESS_TOKEN, "code=", "state=", OAUTH_SECRET, COOKIE_SECRET):
            assert secret not in text, f"o log vaza {secret!r}"

    def test_access_log_never_contains_the_query_string(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        self.callback(browser, params["state"])
        bad = self.browser()
        self.start_login(bad)
        self.callback(bad, "estado-errado-SEGREDO")
        self.assert_no_oauth_material(params["state"])
        assert "estado-errado-SEGREDO" not in self.caplog.text

    def test_unexpected_error_in_callback_does_not_leak_query_or_token(self):
        async def boom(_token):
            raise RuntimeError("falha inesperada")

        self.fake.fetch_user = boom
        browser = self.browser()
        _, params = self.start_login(browser)
        response = self.callback(browser, params["state"])
        assert response.code == 500 and "Traceback" not in response.body.decode()
        assert self.session_cookie_name() not in browser.cookies
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls, "o token deve ser revogado mesmo com erro inesperado"
        self.assert_no_oauth_material(params["state"])


class RevokeFailureTest(LoginBase):
    def test_revoke_failure_does_not_block_login_and_does_not_leak(self):
        oauth = require("panel.oauth")

        async def failing_revoke(_token):
            raise oauth.DiscordOAuthError("revogação falhou")

        self.fake.revoke = failing_revoke
        browser = self.browser()
        response = self.login(browser)
        assert response.code == 302 and self.session_cookie_name() in browser.cookies
        assert ACCESS_TOKEN not in self.caplog.text and CODE not in self.caplog.text


class CookieFormatTest(LoginBase):
    def test_cookies_are_not_quoted_or_padded(self):
        browser = self.browser()
        start, params = self.start_login(browser)
        done = self.callback(browser, params["state"])
        headers = set_cookie_headers(start, "painel_login") + set_cookie_headers(done, SESSION_COOKIE)
        assert len(headers) == 2
        for header in headers:
            value = header.split(";")[0].split("=", 1)[1]
            assert '"' not in value and "=" not in value, f"valor de cookie com aspas/padding: {value[:40]}"

"""Fluxo de login com Discord (authorization code + state + PKCE) via HTTP, com dublê de DiscordOAuthClient."""

import email.utils
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
import tornado.web
from tornado.testing import AsyncHTTPTestCase

from tests.panel.helpers import (
    COOKIE_SECRET,
    EXPECTED_SECURITY_HEADERS,
    OAUTH_SECRET,
    https_config,
    local_config,
    require,
)
from tests.panel.helpers_login import (
    ACCESS_TOKEN,
    CODE,
    DEFAULT_USER,
    Browser,
    FakeClock,
    authorize_params,
    build_app,
    cookie_attrs,
    make_fake_oauth,
    set_cookie_headers,
)

pytestmark = pytest.mark.critical

SESSION_COOKIE, LOGIN_COOKIE = "painel_sessao", "painel_login"
ATTEMPT_TTL = 10 * 60


class LoginBase(AsyncHTTPTestCase):
    config_factory = staticmethod(local_config)
    fake_kwargs: dict = {}

    @pytest.fixture(autouse=True)
    def _inject(self, caplog, monkeypatch):
        self.caplog, self.monkeypatch = caplog, monkeypatch
        caplog.set_level(logging.DEBUG)

    def setUp(self):
        require("empiremuse.panel"), require("empiremuse.panel.oauth"), require("empiremuse.panel.sessions")
        self.clock = FakeClock()
        super().setUp()

    def get_app(self):
        config = self.config_factory()
        settings = require("empiremuse.panel.settings").load_panel_settings(config)
        self.fake = make_fake_oauth(settings, **self.fake_kwargs)
        self.settings, app = build_app(config, self.clock, self.fake)
        return require("empiremuse.panel").make_router(tornado.web.Application([]), app)

    # ---- ações
    def browser(self, **kw):
        return Browser(self, **kw)

    def start_login(self, browser, next_=None, advance=61):
        self.clock.advance(advance)  # evita esbarrar no rate limit quando há vários logins
        path = "/painel/login" + (f"?next={next_}" if next_ is not None else "")
        response = browser.get(path)
        assert response.code == 302, f"login deveria redirecionar (302), veio {response.code}"
        return response, authorize_params(response.headers["Location"])

    def callback(self, browser, state, code=CODE, **extra):
        query = "&".join(f"{k}={v}" for k, v in {"code": code, "state": state, **extra}.items() if v is not None)
        return browser.get(f"/painel/callback?{query}")

    def login(self, browser, next_=None):
        _, params = self.start_login(browser, next_)
        return self.callback(browser, params["state"])

    def session_cookie_name(self):
        return "__Host-painel_sessao" if self.settings.is_https else SESSION_COOKIE

    def login_cookie_name(self):
        return "__Host-painel_login" if self.settings.is_https else LOGIN_COOKIE

    def index_html(self, browser):
        return browser.get("/painel/").body.decode()


# ============================================================================ início do login


class LoginStartTest(LoginBase):
    def test_redirect_uri_ignores_host_and_forwarded_headers(self):
        hostile = {"Host": "evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"}
        _, params = self.start_login(self.browser(extra_headers=hostile))
        assert params["redirect_uri"] == self.settings.redirect_uri

    def test_login_sets_short_lived_signed_attempt_cookie(self):
        response, _ = self.start_login(self.browser())
        headers = set_cookie_headers(response, LOGIN_COOKIE)
        assert len(headers) == 1, "deve definir exatamente um cookie painel_login"
        attrs = cookie_attrs(headers[0])
        assert attrs.get("httponly") is True and attrs.get("samesite", "").lower() == "lax"
        assert "secure" not in attrs, "localhost (insecure_cookies) não usa Secure"
        value = headers[0].split(";")[0].split("=", 1)[1]
        assert value.startswith("2|1:"), "cookie deve ser assinado (set_signed_cookie)"
        if "max-age" in attrs:
            assert 0 < int(attrs["max-age"]) <= ATTEMPT_TTL
        else:
            expires = email.utils.parsedate_to_datetime(attrs["expires"])
            assert 0 < (expires - datetime.now(timezone.utc)).total_seconds() <= ATTEMPT_TTL + 60

    def test_accepted_next_values_are_preserved_after_login(self):
        accepted = ["/painel/servidores", "/painel/servidor/123/musica", "/painel/a?b=c"]
        failures = []
        for next_ in accepted:
            browser = self.browser()
            response = self.login(browser, next_)
            location = urlsplit(response.headers.get("Location", ""))
            got = location.path + (f"?{location.query}" if location.query else "")
            if response.code != 302 or got != next_:
                failures.append(f"{next_!r} -> {response.code} {response.headers.get('Location')!r}")
        assert not failures, "next válido deveria ser mantido:\n  " + "\n  ".join(failures)


# ============================================================================ callback: sucesso


class CallbackSuccessTest(LoginBase):
    @pytest.mark.smoke
    def test_successful_login_creates_session_and_redirects_home(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code == 302 and urlsplit(response.headers["Location"]).path == "/painel/"
        assert self.session_cookie_name() in browser.cookies
        assert "Olá, Tester Global" in self.index_html(browser)

    def test_attempt_cookie_is_cleared_after_callback(self):
        browser = self.browser()
        self.login(browser)
        assert LOGIN_COOKIE not in browser.cookies

    def test_discord_calls_happen_in_order_and_token_is_revoked(self):
        self.login(self.browser())
        assert self.fake.names() == ["exchange", "user", "guilds", "revoke"]
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls

    def test_unsigned_or_forged_session_cookie_is_ignored(self):
        browser = self.browser()
        for forged in ("atacante-escolheu-isto", "2|1:0|10:1700000000|14:painel_sessao|8:YWJj|" + "0" * 64, ""):
            browser.cookies[SESSION_COOKIE] = forged
            response = browser.get("/painel/")
            assert response.code == 200 and "Entrar com Discord" in response.body.decode(), forged

    def test_forged_cookie_cannot_login_after_fixation_attempt(self):
        browser = self.browser()
        browser.cookies[SESSION_COOKIE] = "fixado-pelo-atacante"
        self.login(browser)
        assert browser.cookies[SESSION_COOKIE] != "fixado-pelo-atacante"
        assert "Olá, Tester Global" in self.index_html(browser)


# ============================================================================ callback: erros


class CallbackErrorTest(LoginBase):
    def assert_friendly_error(self, response, *, status=(400, 403, 429, 500, 502, 503)):
        body = response.body.decode()
        assert response.code in status, f"status {response.code}"
        assert response.headers["Content-Type"].startswith("text/html")
        for leak in ("Traceback", "DiscordOAuthError", 'File "', CODE, ACCESS_TOKEN, OAUTH_SECRET, COOKIE_SECRET):
            assert leak not in body, f"a página de erro vaza {leak!r}"
        issued = [
            h
            for h in response.headers.get_list("Set-Cookie")
            if h.startswith(self.session_cookie_name() + "=") and not h.split("=", 1)[1].startswith(("; ", '"";'))
        ]
        assert not issued, "uma falha de login não pode emitir cookie de sessão"

    def test_callback_with_wrong_missing_or_empty_state_is_rejected(self):
        failures = []
        for state in ("estado-errado", None, ""):
            browser = self.browser()
            self.start_login(browser)
            response = self.callback(browser, state)
            if response.code not in (400, 403) or self.fake.calls:
                failures.append(f"state={state!r}: status {response.code}, chamadas {self.fake.calls}")
        assert not failures, "\n".join(failures)

    def test_attempt_expires_after_10_minutes(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        self.clock.advance(ATTEMPT_TTL + 1)
        self.assert_friendly_error(self.callback(browser, params["state"]))
        assert self.fake.calls == []

    def test_attempt_is_single_use(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        stolen_cookie = browser.cookies[LOGIN_COOKIE]
        assert self.callback(browser, params["state"]).code == 302
        replay = self.browser()
        replay.cookies[LOGIN_COOKIE] = stolen_cookie
        self.assert_friendly_error(self.callback(replay, params["state"]))
        assert self.fake.names().count("exchange") == 1, "o código só pode ser trocado uma vez"

    def test_error_pages_have_security_headers_and_no_store(self):
        response = self.callback(self.browser(), "qualquer")
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"


class UserReadFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "user"}

    def test_failed_user_read_still_revokes_token_and_creates_no_session(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code >= 400
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls, "o token deve ser revogado mesmo se a leitura falhar"
        assert self.session_cookie_name() not in browser.cookies


# ============================================================================ segredos


class NoSecretLeakTest(LoginBase):
    def _scan(self, texts, label):
        for secret in (ACCESS_TOKEN, CODE, OAUTH_SECRET, COOKIE_SECRET):
            leaked = [t[:80] for t in texts if secret in t]
            assert not leaked, f"{label} vaza {secret!r}: {leaked}"

    def test_tokens_and_secrets_never_reach_logs_cookies_or_html(self):
        browser = self.browser()
        responses = []
        _, params = self.start_login(browser)
        responses.append(self.callback(browser, params["state"]))
        responses.append(browser.get("/painel/"))
        self._scan([self.caplog.text], "log")
        self._scan(browser.all_set_cookie_headers, "cookies")
        self._scan([r.body.decode() for r in responses] + [str(r.headers) for r in responses], "resposta HTTP")


class NoSecretLeakOnFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "user"}

    def test_failure_paths_do_not_log_token_or_code(self):
        browser = self.browser()
        response = self.login(browser)
        for secret in (ACCESS_TOKEN, CODE, OAUTH_SECRET, COOKIE_SECRET):
            assert secret not in self.caplog.text, f"log vaza {secret!r}"
            assert secret not in response.body.decode()


# ============================================================================ página inicial logada


class IndexStateTest(LoginBase):
    def test_anonymous_index_shows_login_button_only(self):
        body = self.index_html(self.browser())
        assert "Entrar com Discord" in body and "/painel/logout" not in body and "Olá," not in body

    def test_falls_back_to_username_when_there_is_no_global_name(self):
        self.fake.user = {**DEFAULT_USER, "global_name": None, "avatar": None}
        browser = self.browser()
        self.login(browser)
        body = self.index_html(browser)
        assert "Olá, tester" in body and "avatars/1001/None" not in body


# ============================================================================ HTTPS


class HttpsCookiesTest(LoginBase):
    config_factory = staticmethod(https_config)

    def test_https_uses_host_prefixed_secure_cookies(self):
        browser = self.browser()
        start, params = self.start_login(browser)
        attempt = set_cookie_headers(start, "__Host-painel_login")
        assert len(attempt) == 1, "com https o cookie da tentativa é __Host-painel_login"
        assert params["redirect_uri"] == "https://painel.example.com/painel/callback"
        done = self.callback(browser, params["state"])
        session = set_cookie_headers(done, "__Host-painel_sessao")
        assert len(session) == 1, "com https o cookie de sessão é __Host-painel_sessao"
        for header in attempt + session:
            attrs = cookie_attrs(header)
            assert attrs.get("secure") is True and attrs.get("httponly") is True
            assert attrs.get("path") == "/" and "domain" not in attrs, "requisitos do prefixo __Host-"
            assert attrs.get("samesite", "").lower() == "lax"
        assert not set_cookie_headers(done, "painel_sessao"), "não definir também o nome sem prefixo"

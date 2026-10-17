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
    XSRF_META_RE,
    https_config,
    local_config,
    require,
)
from tests.panel.helpers_login import (
    ACCESS_TOKEN,
    AUTHORIZE_PARAM_KEYS,
    CLIENT_ID,
    CODE,
    DEFAULT_USER,
    GATE,
    Browser,
    FakeClock,
    authorize_params,
    build_app,
    cookie_attrs,
    make_fake_oauth,
    s256,
    set_cookie_headers,
)

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
    def test_login_redirects_to_discord_with_exact_parameters(self):
        response, params = self.start_login(self.browser())
        location = response.headers["Location"]
        assert location.startswith(GATE + "?")
        assert set(params) == AUTHORIZE_PARAM_KEYS
        assert params["response_type"] == "code" and params["client_id"] == CLIENT_ID
        assert params["scope"] == "identify guilds" and params["prompt"] == "none"
        assert params["code_challenge_method"] == "S256"
        assert params["redirect_uri"] == "http://localhost:8080/painel/callback"
        assert len(params["state"]) >= 16 and len(params["code_challenge"]) >= 43

    def test_redirect_uri_ignores_host_and_forwarded_headers(self):
        hostile = {"Host": "evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"}
        _, params = self.start_login(self.browser(extra_headers=hostile))
        assert params["redirect_uri"] == self.settings.redirect_uri

    def test_each_login_has_fresh_state_and_challenge(self):
        _, first = self.start_login(self.browser())
        _, second = self.start_login(self.browser())
        assert first["state"] != second["state"] and first["code_challenge"] != second["code_challenge"]

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

    def test_login_response_has_security_headers(self):
        response, _ = self.start_login(self.browser())
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name

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

    def test_rejected_next_values_fall_back_to_panel_home(self):
        rejected = [
            "https://evil.example/painel/",
            "//evil.example/painel/",
            "/\\evil.example",
            "/painel\\x",
            "/painel//evil.example",
            "/outro/caminho",
            "painel/servidores",
            "javascript:alert(1)",
            "/painel",
            "",
            "/",
            "http://localhost:8080/painel/x",
            "/painel/..\\x",
        ]
        failures = []
        for next_ in rejected:
            browser = self.browser()
            response = self.login(browser, next_)
            location = urlsplit(response.headers.get("Location", ""))
            if response.code != 302 or location.netloc or location.path != "/painel/":
                failures.append(f"{next_!r} -> {response.code} {response.headers.get('Location')!r}")
        assert not failures, "next inválido deveria cair em /painel/:\n  " + "\n  ".join(failures)


# ============================================================================ callback: sucesso


class CallbackSuccessTest(LoginBase):
    def test_successful_login_creates_session_and_redirects_home(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code == 302 and urlsplit(response.headers["Location"]).path == "/painel/"
        assert self.session_cookie_name() in browser.cookies
        assert "Olá, Tester Global" in self.index_html(browser)

    def test_session_cookie_attributes_for_localhost(self):
        browser = self.browser()
        response = self.login(browser)
        header = set_cookie_headers(response, SESSION_COOKIE)[0]
        attrs = cookie_attrs(header)
        assert attrs.get("httponly") is True and attrs.get("samesite", "").lower() == "lax"
        assert attrs.get("path") == "/" and "secure" not in attrs
        value = header.split(";")[0].split("=", 1)[1]
        assert value.startswith("2|1:"), "o cookie de sessão deve ser assinado"
        assert DEFAULT_USER["id"] not in value and DEFAULT_USER["username"] not in value

    def test_attempt_cookie_is_cleared_after_callback(self):
        browser = self.browser()
        self.login(browser)
        assert LOGIN_COOKIE not in browser.cookies

    def test_pkce_verifier_sent_to_discord_matches_the_challenge_in_the_url(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        self.callback(browser, params["state"])
        exchange = next(c for c in self.fake.calls if c[0] == "exchange")
        assert exchange[1] == CODE and s256(exchange[2]) == params["code_challenge"]

    def test_discord_calls_happen_in_order_and_token_is_revoked(self):
        self.login(self.browser())
        assert self.fake.names() == ["exchange", "user", "guilds", "revoke"]
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls

    def test_new_session_id_on_every_login_prevents_fixation(self):
        first, second = self.browser(), self.browser()
        self.login(first)
        second.cookies[SESSION_COOKIE] = first.cookies[SESSION_COOKIE]  # reaproveita cookie anterior
        self.login(second)
        assert second.cookies[SESSION_COOKIE] != first.cookies[SESSION_COOKIE]

    def test_unsigned_or_forged_session_cookie_is_ignored(self):
        browser = self.browser()
        for forged in ("atacante-escolheu-isto", "2|1:0|10:1700000000|14:painel_sessao|8:YWJj|" + "0" * 64, ""):
            browser.cookies[SESSION_COOKIE] = forged
            response = browser.get("/painel/")
            assert response.code == 200 and "Entrar com Discord" in response.body.decode(), forged

    def test_tampered_session_cookie_is_rejected(self):
        browser = self.browser()
        self.login(browser)
        value = browser.cookies[SESSION_COOKIE]
        browser.cookies[SESSION_COOKIE] = value[:-1] + ("A" if value[-1] != "A" else "B")
        assert "Entrar com Discord" in self.index_html(browser)

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

    def test_callback_without_attempt_cookie_is_rejected_without_calling_discord(self):
        _, params = self.start_login(self.browser())
        response = self.callback(self.browser(), params["state"])  # outro "navegador": sem cookie
        self.assert_friendly_error(response)
        assert self.fake.calls == []

    def test_callback_with_wrong_missing_or_empty_state_is_rejected(self):
        failures = []
        for state in ("estado-errado", None, ""):
            browser = self.browser()
            self.start_login(browser)
            response = self.callback(browser, state)
            if response.code not in (400, 403) or self.fake.calls:
                failures.append(f"state={state!r}: status {response.code}, chamadas {self.fake.calls}")
        assert not failures, "\n".join(failures)

    def test_callback_without_code_is_rejected(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        response = self.callback(browser, params["state"], code=None)
        self.assert_friendly_error(response)
        assert self.fake.calls == []

    def test_attempt_expires_after_10_minutes(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        self.clock.advance(ATTEMPT_TTL + 1)
        self.assert_friendly_error(self.callback(browser, params["state"]))
        assert self.fake.calls == []

    def test_attempt_still_valid_just_before_expiry(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        self.clock.advance(ATTEMPT_TTL - 5)
        assert self.callback(browser, params["state"]).code == 302

    def test_attempt_is_single_use(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        stolen_cookie = browser.cookies[LOGIN_COOKIE]
        assert self.callback(browser, params["state"]).code == 302
        replay = self.browser()
        replay.cookies[LOGIN_COOKIE] = stolen_cookie
        self.assert_friendly_error(self.callback(replay, params["state"]))
        assert self.fake.names().count("exchange") == 1, "o código só pode ser trocado uma vez"

    def test_access_denied_shows_friendly_page_without_calling_discord(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        response = browser.get(f"/painel/callback?error=access_denied&state={params['state']}")
        assert response.code < 500 and response.headers["Content-Type"].startswith("text/html")
        assert self.fake.calls == [] and self.session_cookie_name() not in browser.cookies
        assert "Traceback" not in response.body.decode()

    def test_error_pages_have_security_headers_and_no_store(self):
        response = self.callback(self.browser(), "qualquer")
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"


class ExchangeFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "exchange"}

    def test_failed_exchange_shows_friendly_error_and_creates_no_session(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code >= 400 and "Traceback" not in response.body.decode()
        assert self.session_cookie_name() not in browser.cookies
        assert "revoke" not in self.fake.names(), "sem token não há o que revogar"
        assert "Entrar com Discord" in self.index_html(browser)


class UserReadFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "user"}

    def test_failed_user_read_still_revokes_token_and_creates_no_session(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code >= 400
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls, "o token deve ser revogado mesmo se a leitura falhar"
        assert self.session_cookie_name() not in browser.cookies


class GuildsReadFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "guilds"}

    def test_failed_guilds_read_still_revokes_token_and_creates_no_session(self):
        browser = self.browser()
        response = self.login(browser)
        assert response.code >= 400
        assert ("revoke", ACCESS_TOKEN) in self.fake.calls
        assert self.session_cookie_name() not in browser.cookies
        assert self.fake.names() == ["exchange", "user", "guilds", "revoke"]


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

    def test_nothing_secret_is_logged_even_on_failures(self):
        for state in ("errado", "outro"):
            self.callback(self.browser(), state)
        self._scan([self.caplog.text], "log")


class NoSecretLeakOnFailureTest(LoginBase):
    fake_kwargs = {"fail_at": "user"}

    def test_failure_paths_do_not_log_token_or_code(self):
        browser = self.browser()
        response = self.login(browser)
        for secret in (ACCESS_TOKEN, CODE, OAUTH_SECRET, COOKIE_SECRET):
            assert secret not in self.caplog.text, f"log vaza {secret!r}"
            assert secret not in response.body.decode()


# ============================================================================ guildas e usuário na sessão


class GuildFilterTest(LoginBase):
    RAW = [
        {"id": "1", "name": "Dono", "icon": "ic1", "owner": True, "permissions": "0"},
        {"id": "2", "name": "Admin", "icon": None, "owner": False, "permissions": "8"},
        {"id": "3", "name": "Gerente", "icon": None, "owner": False, "permissions": "32"},
        {"id": "4", "name": "Os dois", "icon": None, "owner": False, "permissions": "40"},
        {"id": "5", "name": "Membro", "icon": None, "owner": False, "permissions": "1024"},
        {"id": "6", "name": "Canais", "icon": None, "owner": False, "permissions": "16"},
        {"id": "7", "name": "Grande admin", "icon": None, "owner": False, "permissions": str(2**44 | 8)},
        {"id": "8", "name": "Grande sem", "icon": None, "owner": False, "permissions": str(2**44)},
        {"id": "9", "name": "Zero", "icon": None, "owner": False, "permissions": "0"},
    ]
    fake_kwargs = {"guilds": RAW}

    def test_only_owner_administrator_or_manage_guild_are_stored(self):
        sessions = require("empiremuse.panel.sessions")
        recorded = {}
        original = sessions.SessionStore.create

        def recording_create(store, user, guilds):
            recorded["user"], recorded["guilds"] = user, tuple(guilds)
            return original(store, user, guilds)

        self.monkeypatch.setattr(sessions.SessionStore, "create", recording_create)
        self.login(self.browser())
        assert [g.id for g in recorded["guilds"]] == ["1", "2", "3", "4", "7"]
        first = recorded["guilds"][0]
        assert (first.name, first.icon, first.owner, first.permissions) == ("Dono", "ic1", True, 0)
        assert recorded["guilds"][1].permissions == 8 and isinstance(recorded["guilds"][1].permissions, int)
        assert recorded["guilds"][4].permissions == 2**44 | 8
        user = recorded["user"]
        assert (user.id, user.username, user.global_name, user.avatar) == (
            DEFAULT_USER["id"],
            DEFAULT_USER["username"],
            DEFAULT_USER["global_name"],
            DEFAULT_USER["avatar"],
        )


# ============================================================================ página inicial logada


class IndexStateTest(LoginBase):
    def test_anonymous_index_shows_login_button_only(self):
        body = self.index_html(self.browser())
        assert "Entrar com Discord" in body and "/painel/logout" not in body and "Olá," not in body

    def test_logged_in_index_greets_user_with_avatar_and_logout_form(self):
        browser = self.browser()
        self.login(browser)
        body = self.index_html(browser)
        assert "Olá, Tester Global" in body
        assert "https://cdn.discordapp.com/avatars/1001/abc123hash.png?size=64" in body
        assert "Entrar com Discord" not in body
        assert 'action="/painel/logout"' in body and 'method="post"' in body.lower()
        assert 'name="_xsrf"' in body, "o formulário de logout precisa do token _xsrf"
        assert XSRF_META_RE.search(body)

    def test_falls_back_to_username_when_there_is_no_global_name(self):
        self.fake.user = {**DEFAULT_USER, "global_name": None, "avatar": None}
        browser = self.browser()
        self.login(browser)
        body = self.index_html(browser)
        assert "Olá, tester" in body and "avatars/1001/None" not in body

    def test_user_names_are_html_escaped(self):
        self.fake.user = {**DEFAULT_USER, "global_name": "<script>alert(1)</script>"}
        browser = self.browser()
        self.login(browser)
        body = self.index_html(browser)
        assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


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

    def test_https_login_and_session_work_end_to_end(self):
        browser = self.browser()
        _, params = self.start_login(browser)
        assert self.callback(browser, params["state"]).code == 302
        assert "Olá, Tester Global" in self.index_html(browser)

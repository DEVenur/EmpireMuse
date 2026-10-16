"""Sessões via HTTP: logout, TTL/ociosidade com relógio injetado, limite por usuário e rate limit."""
import re

from tests.panel.helpers import XSRF_META_RE, https_config, local_config
from tests.panel.test_login_flow import LoginBase

MINUTE, HOUR = 60, 3600


def xsrf_headers(browser):
    page = browser.get("/painel/")
    token = XSRF_META_RE.search(page.body.decode()).group(1)
    return {"X-XSRFToken": token}


# ============================================================================ logout

class LogoutTest(LoginBase):
    def logged_in(self):
        browser = self.browser()
        self.login(browser)
        return browser

    def test_logout_with_xsrf_destroys_session_and_redirects_home(self):
        browser = self.logged_in()
        old_cookie = browser.cookies[self.session_cookie_name()]
        response = browser.post("/painel/logout", headers=xsrf_headers(browser))
        assert response.code == 302 and response.headers["Location"].endswith("/painel/")
        assert self.session_cookie_name() not in browser.cookies, "o cookie de sessão deve ser apagado"
        assert "Entrar com Discord" in self.index_html(browser)
        replay = self.browser()
        replay.cookies[self.session_cookie_name()] = old_cookie
        assert "Entrar com Discord" in self.index_html(replay), "o id antigo não pode voltar a funcionar"

    def test_logout_without_xsrf_token_is_forbidden_and_keeps_session(self):
        browser = self.logged_in()
        browser.get("/painel/")  # obtém o cookie _xsrf, mas não envia o token
        assert browser.post("/painel/logout").code == 403
        assert "Olá, Tester Global" in self.index_html(browser)

    def test_logout_with_wrong_xsrf_token_is_forbidden(self):
        browser = self.logged_in()
        browser.get("/painel/")
        assert browser.post("/painel/logout", headers={"X-XSRFToken": "token-invalido"}).code == 403
        assert "Olá, Tester Global" in self.index_html(browser)

    def test_logout_via_get_does_not_log_out(self):
        browser = self.logged_in()
        assert browser.get("/painel/logout").code in (404, 405)
        assert "Olá, Tester Global" in self.index_html(browser)

    def test_logout_form_in_page_works_with_form_field_token(self):
        browser = self.logged_in()
        body = browser.get("/painel/").body.decode()
        token = re.search(r'name="_xsrf"\s+value="([^"]+)"', body) or re.search(r'value="([^"]+)"\s+name="_xsrf"', body)
        assert token, "formulário de logout sem campo _xsrf"
        response = browser.post("/painel/logout", body=f"_xsrf={token.group(1)}",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert response.code == 302 and "Entrar com Discord" in self.index_html(browser)

    def test_logout_when_anonymous_is_harmless(self):
        browser = self.browser()
        response = browser.post("/painel/logout", headers=xsrf_headers(browser))
        assert response.code in (302, 303) and response.headers["Location"].endswith("/painel/")


class LogoutHttpsTest(LogoutTest):
    config_factory = staticmethod(https_config)


# ============================================================================ TTL e ociosidade

class SessionExpiryTest(LoginBase):
    config_factory = staticmethod(lambda: local_config(PANEL_SESSION_TTL_HOURS=2, PANEL_SESSION_IDLE_MINUTES=30))

    def logged_in_page(self, browser):
        return "Olá, Tester Global" in self.index_html(browser)

    def test_session_expires_after_idle_timeout(self):
        browser = self.browser()
        self.login(browser)
        self.clock.advance(31 * MINUTE)
        assert not self.logged_in_page(browser)

    def test_activity_renews_idle_timeout(self):
        browser = self.browser()
        self.login(browser)
        for _ in range(3):
            self.clock.advance(29 * MINUTE)
            assert self.logged_in_page(browser), "atividade dentro da janela deve manter a sessão"

    def test_session_expires_at_absolute_ttl_despite_activity(self):
        browser = self.browser()
        self.login(browser)
        for _ in range(4):  # 4 x 29 min = 1h56 de atividade contínua (sempre dentro da ociosidade de 30 min)
            self.clock.advance(29 * MINUTE)
            assert self.logged_in_page(browser)
        self.clock.advance(29 * MINUTE)  # 2h25 desde o login: passou das 2h absolutas
        assert not self.logged_in_page(browser), "passou do TTL absoluto: deve pedir novo login"

    def test_expired_session_cookie_is_not_resurrected_by_a_new_request(self):
        browser = self.browser()
        self.login(browser)
        self.clock.advance(40 * MINUTE)
        assert not self.logged_in_page(browser)
        self.clock.advance(1)
        assert not self.logged_in_page(browser)


# ============================================================================ limite de sessões por usuário

class SessionLimitTest(LoginBase):
    def test_sixth_login_of_same_user_evicts_the_oldest_session(self):
        browsers = [self.browser() for _ in range(6)]
        for browser in browsers:
            self.login(browser)
        assert "Entrar com Discord" in self.index_html(browsers[0]), "a sessão mais antiga deve ser removida"
        for browser in browsers[1:]:
            assert "Olá, Tester Global" in self.index_html(browser)


# ============================================================================ rate limit

def first_429(statuses):
    return next((i for i, code in enumerate(statuses, start=1) if code == 429), None)


class RateLimitTest(LoginBase):
    LIMIT_PROBE = 40  # bem acima do exemplo do contrato (10/min)

    def hammer(self, path, **kwargs):
        browser = self.browser(**kwargs)
        return [browser.get(path).code for _ in range(self.LIMIT_PROBE)]

    def test_login_endpoint_is_rate_limited_per_ip(self):
        statuses = self.hammer("/painel/login")
        position = first_429(statuses)
        assert position is not None, "deveria haver 429 após muitas tentativas de login em 1 minuto"
        assert position > 3, f"limite agressivo demais (429 na tentativa {position})"
        assert all(code == 302 for code in statuses[:3])

    def test_callback_endpoint_is_rate_limited_per_ip(self):
        statuses = self.hammer("/painel/callback?code=x&state=y")
        position = first_429(statuses)
        assert position is not None, "deveria haver 429 após muitas chamadas ao callback em 1 minuto"
        assert position > 3

    def test_limit_resets_after_the_window(self):
        self.hammer("/painel/login")
        self.clock.advance(120)
        assert self.browser().get("/painel/login").code == 302

    def test_rate_limited_response_is_friendly_html(self):
        browser = self.browser()
        for _ in range(self.LIMIT_PROBE):
            response = browser.get("/painel/login")
            if response.code == 429:
                break
        assert response.code == 429
        assert response.headers["Content-Type"].startswith("text/html")
        assert "Traceback" not in response.body.decode()

    def test_forwarded_for_header_is_ignored_without_trust_proxy(self):
        browser = self.browser()
        codes = [browser.get("/painel/login", headers={"X-Forwarded-For": f"203.0.113.{i}"}).code
                 for i in range(1, self.LIMIT_PROBE + 1)]
        assert first_429(codes) is not None, "X-Forwarded-For não pode burlar o limite sem PANEL_TRUST_PROXY"

    def test_limit_applies_to_each_ip_independently_of_login_success(self):
        statuses = self.hammer("/painel/login")
        assert first_429(statuses) is not None
        # outro endpoint do painel (página inicial) não é afetado pelo limite de login
        assert self.browser().get("/painel/").code == 200


class RateLimitTrustProxyTest(LoginBase):
    config_factory = staticmethod(lambda: https_config(PANEL_TRUST_PROXY=True))

    def get_httpserver_options(self):
        return {"xheaders": True}  # como web_app.run_app faz com PANEL_TRUST_PROXY=true

    def test_distinct_forwarded_ips_have_separate_counters_when_proxy_is_trusted(self):
        browser = self.browser()
        codes = [browser.get("/painel/login", headers={"X-Forwarded-For": f"203.0.113.{i}"}).code
                 for i in range(1, 31)]
        assert 429 not in codes, "com PANEL_TRUST_PROXY o IP real vem de X-Forwarded-For"

    def test_same_forwarded_ip_is_still_limited_when_proxy_is_trusted(self):
        browser = self.browser()
        codes = [browser.get("/painel/login", headers={"X-Forwarded-For": "203.0.113.9"}).code
                 for _ in range(40)]
        assert first_429(codes) is not None

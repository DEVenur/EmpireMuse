"""Infraestrutura dos testes da Etapa 2 (login com Discord e sessões): dublês, relógio, 'navegador' com cookies.

Contrato: BRIEFING-PAINEL-E2.md. Nada de rede real: o cliente OAuth é um subclasse de DiscordOAuthClient que
sobrescreve só os métodos de rede (authorize_url continua sendo o real, que é puro).
"""

import base64
import hashlib
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from tests.panel.helpers import fake_pool, load_settings, require

CODE = "code-SEGREDO-xyz789"
ACCESS_TOKEN = "token-SEGREDO-abc123"
CLIENT_ID = "123456789012345678"
DEFAULT_USER = {"id": "1001", "username": "tester", "global_name": "Tester Global", "avatar": "abc123hash"}
DEFAULT_GUILDS = [{"id": "1", "name": "Dono", "icon": None, "owner": True, "permissions": "0"}]
GATE = "https://discord.com/oauth2/authorize"
AUTHORIZE_PARAM_KEYS = {
    "response_type",
    "client_id",
    "scope",
    "state",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "prompt",
}


class FakeClock:
    """Relógio injetável (substitui time.monotonic)."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_fake_oauth(settings, *, user=None, guilds=None, fail_at=None, token=ACCESS_TOKEN):
    """DiscordOAuthClient com a rede substituída. `fail_at` ∈ {None,'exchange','user','guilds'}; registra `calls`."""
    oauth = require("empiremuse.panel.oauth")

    class FakeOAuthClient(oauth.DiscordOAuthClient):
        def __init__(self):
            super().__init__(settings, CLIENT_ID)
            self.calls = []
            self.user = dict(DEFAULT_USER if user is None else user)
            self.guilds = list(DEFAULT_GUILDS if guilds is None else guilds)
            self.fail_at = fail_at

        async def exchange_code(self, code, code_verifier):
            self.calls.append(("exchange", code, code_verifier))
            if self.fail_at == "exchange":
                raise oauth.DiscordOAuthError("falha simulada na troca do código")
            return token

        async def fetch_user(self, access_token):
            self.calls.append(("user", access_token))
            if self.fail_at == "user":
                raise oauth.DiscordOAuthError("falha simulada ao ler o usuário")
            return dict(self.user)

        async def fetch_guilds(self, access_token):
            self.calls.append(("guilds", access_token))
            if self.fail_at == "guilds":
                raise oauth.DiscordOAuthError("falha simulada ao ler os servidores")
            return list(self.guilds)

        async def revoke(self, access_token):
            self.calls.append(("revoke", access_token))

        def names(self):
            return [call[0] for call in self.calls]

    return FakeOAuthClient()


def build_app(settings_config: dict, clock, fake):
    panel = require("empiremuse.panel")
    settings = load_settings(settings_config)
    return settings, panel.build_panel_app(fake_pool(), settings, oauth_client=fake, clock=clock)


class Browser:
    """Mantém cookies entre requisições (sem seguir redirecionamentos)."""

    def __init__(self, case, extra_headers=None):
        self.case = case
        self.cookies = {}
        self.extra_headers = dict(extra_headers or {})
        self.all_set_cookie_headers = []

    def request(self, path, method="GET", headers=None, **kwargs):
        merged = {**self.extra_headers, **(headers or {})}
        if self.cookies:
            merged["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if method == "POST" and "body" not in kwargs:
            kwargs["body"] = ""
        response = self.case.fetch(path, method=method, headers=merged, follow_redirects=False, **kwargs)
        self._absorb(response)
        return response

    def get(self, path, **kwargs):
        return self.request(path, "GET", **kwargs)

    def post(self, path, **kwargs):
        return self.request(path, "POST", **kwargs)

    def _absorb(self, response):
        for header in response.headers.get_list("Set-Cookie"):
            self.all_set_cookie_headers.append(header)
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                if morsel.value == "" or morsel["max-age"] == "0":
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value


def set_cookie_headers(response, name):
    return [h for h in response.headers.get_list("Set-Cookie") if h.startswith(name + "=")]


def cookie_attrs(header: str) -> dict:
    """'nome=valor; HttpOnly; Path=/' -> {'httponly': True, 'path': '/'} (chaves em minúsculas)."""
    attrs = {}
    for part in header.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        attrs[key.lower()] = value or True
    return attrs


def authorize_params(location: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query, keep_blank_values=True).items()}


def fake_pool_with_bots():
    return SimpleNamespace(bots=[], database=None)

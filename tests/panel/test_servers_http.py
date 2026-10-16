"""Rotas /painel/servidores e /painel/servidores/<gid> (Etapa 3): autorização no servidor, lista, convites, 404 genérico."""
import html
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import tornado.web

from tests.panel.helpers import COOKIE_SECRET, EXPECTED_SECURITY_HEADERS, OAUTH_SECRET, require
from tests.panel.helpers_login import DEFAULT_USER, make_fake_oauth
from tests.panel.helpers_servers import (INVITE_PERMISSIONS, USER_ID, FakeBot, FakeGuild, FakePool, raw_guild)
from tests.panel.test_login_flow import LoginBase

INVITE_BASE = "https://discord.com/oauth2/authorize"
INVITE_KEYS = {"client_id", "scope", "permissions", "guild_id", "disable_guild_select"}
NOT_FOUND_TEXT = "Servidor não encontrado ou você não tem permissão para gerenciá-lo."
CATEGORIES = ["Player", "Canal de pedidos", "DJ", "Aparência", "Links", "Geral"]
UID = int(USER_ID)


def normalize(body: str) -> str:
    """Remove tokens XSRF (aleatórios por requisição) para comparar páginas."""
    body = re.sub(r'(name="xsrf-token"\s+content=")[^"]*', r"\1X", body)
    return re.sub(r'(name="_xsrf"\s+value=")[^"]*', r"\1X", body)


def visible_text(body: str) -> str:
    """Texto visível: sem <head> (meta xsrf), sem tags nem atributos (campos ocultos com token aleatório)."""
    body = re.sub(r"<head>.*?</head>", "", body, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


def invites(body: str):
    """Lista de dicts de parâmetros de todos os convites (href para discord.com/oauth2/authorize) da página."""
    found = []
    for href in re.findall(r'href="(https://discord\.com/oauth2/authorize[^"]*)"', body):
        parts = urlsplit(html.unescape(href))
        found.append({"base": f"{parts.scheme}://{parts.netloc}{parts.path}",
                      "params": {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}})
    return found


class World:
    """Dois bots (Um=1, Dois=2) e servidores: 100 (bot 1), 200 (bot 2), 300 (nenhum), 400 (bot 1; falta o 2),
    600 (bot 1 mas usuário SEM permissão no bot), 700 (nenhum bot), 500 (fora da sessão: OAuth sem permissão)."""

    def __init__(self):
        self.guilds = {
            "100": FakeGuild("100", "Alfa", owner_id=999, icon_hash="icon100"),
            "200": FakeGuild("200", "Beta", owner_id=999),
            "400": FakeGuild("400", "Delta", owner_id=999),
            "600": FakeGuild("600", "Rebaixado", owner_id=999),
            "500": FakeGuild("500", "Fora", owner_id=999),
        }
        for gid in ("100", "200", "400"):
            self.guilds[gid].add_member(UID, administrator=True)
        self.guilds["600"].add_member(UID)  # membro comum no bot (OAuth ainda diz admin)
        self.guilds["500"].add_member(UID, administrator=True)
        self.bot1 = FakeBot(1, "Bot Um", guilds=[self.guilds[g] for g in ("100", "400", "600", "500")])
        self.bot2 = FakeBot(2, "Bot Dois", guilds=[self.guilds["200"]])
        self.pool = FakePool([self.bot1, self.bot2])
        self.raw = [
            raw_guild(100, "Alfa", icon="icon100", permissions="8"), raw_guild(200, "Beta", permissions="32"),
            raw_guild(300, "Gama", permissions="8"), raw_guild(400, "Delta", permissions="8"),
            raw_guild(600, "Rebaixado", permissions="8"), raw_guild(700, "SemBot", permissions="8"),
            raw_guild(500, "Fora", owner=False, permissions="1024"),   # filtrado no login
        ]


class ServersBase(LoginBase):
    raw_override = None

    def get_app(self):
        panel = require("panel")
        settings = require("panel.settings").load_panel_settings(self.config_factory())
        self.settings, self.world = settings, World()
        self.pool = self.world.pool
        raw = self.world.raw if self.raw_override is None else self.raw_override
        self.fake = make_fake_oauth(settings, guilds=raw)
        app = panel.build_panel_app(self.pool, settings, oauth_client=self.fake, clock=self.clock)
        return panel.make_router(tornado.web.Application([]), app)

    def logged_in(self):
        browser = self.browser()
        assert self.login(browser).code == 302
        return browser

    def page(self, path, browser=None):
        return (browser or self.logged_in()).get(path)


# ============================================================================ acesso anônimo

class AnonymousTest(ServersBase):
    def test_anonymous_is_redirected_to_login_with_next(self):
        failures = []
        for path in ("/painel/servidores", "/painel/servidores/100", "/painel/servidores/999", "/painel/servidores/abc"):
            response = self.browser().get(path)
            location = urlsplit(response.headers.get("Location", ""))
            ok = (response.code == 302 and location.path == "/painel/login"
                  and parse_qs(location.query).get("next") == [path])
            if not ok:
                failures.append(f"{path}: {response.code} {response.headers.get('Location')!r}")
        assert not failures, "anônimo deveria ir para /painel/login?next=<caminho>:\n  " + "\n  ".join(failures)

    def test_login_with_next_returns_to_the_servers_page(self):
        browser = self.browser()
        response = self.login(browser, next_="/painel/servidores")
        assert response.code == 302 and urlsplit(response.headers["Location"]).path == "/painel/servidores"

    def test_expired_session_is_redirected_to_login(self):
        browser = self.logged_in()
        self.clock.advance(61 * 60 + 1)
        assert browser.get("/painel/servidores").code == 302

    def test_anonymous_request_makes_no_discord_calls(self):
        response = self.browser().get("/painel/servidores/100")
        assert response.code == 302, "anônimo deveria ser redirecionado ao login"
        assert self.pool.api_calls() == 0


# ============================================================================ lista

class ServerListTest(ServersBase):
    def test_list_shows_session_guilds_sorted_by_name(self):
        response = self.page("/painel/servidores")
        body = response.body.decode()
        assert response.code == 200 and response.headers["Content-Type"].startswith("text/html")
        positions = [body.index(name) for name in ("Alfa", "Beta", "Delta", "Gama", "Rebaixado", "SemBot")]
        assert positions == sorted(positions), "cartões fora de ordem alfabética"
        assert ">Fora<" not in body and "Fora" not in body, "servidor fora de session.guilds não pode aparecer"

    def test_configure_links_only_for_guilds_with_a_pool_bot(self):
        body = self.page("/painel/servidores").body.decode()
        configure = set(re.findall(r'href="/painel/servidores/(\d+)"', body))
        assert configure == {"100", "200", "400", "600"}, f"links Configurar: {sorted(configure)}"
        assert "Configurar" in body

    def test_invites_exist_only_for_guilds_missing_a_pool_bot_with_exact_parameters(self):
        body = self.page("/painel/servidores").body.decode()
        found = invites(body)
        by_guild = {}
        for invite in found:
            assert invite["base"] == INVITE_BASE
            params = invite["params"]
            assert set(params) == INVITE_KEYS, f"parâmetros do convite: {sorted(params)}"
            assert params["scope"] == "bot applications.commands"
            assert params["permissions"] == str(INVITE_PERMISSIONS)
            assert params["disable_guild_select"] == "true"
            by_guild.setdefault(params["guild_id"], []).append(params["client_id"])
        assert {g: sorted(c) for g, c in by_guild.items()} == {
            "100": ["2"], "200": ["1"], "300": ["1", "2"], "400": ["2"], "600": ["2"], "700": ["1", "2"],
        }, "convite só para cada bot do pool AUSENTE do servidor"
        assert "Adicionar" in body

    def test_invite_labels_name_the_bot(self):
        body = self.page("/painel/servidores").body.decode()
        assert "Bot Um" in body and "Bot Dois" in body

    def test_guild_icon_url_or_no_icon(self):
        body = self.page("/painel/servidores").body.decode()
        assert "https://cdn.discordapp.com/icons/100/icon100.png?size=64" in body
        assert "icons/200/" not in body and "icons/200/None" not in body

    def test_list_warns_that_refreshing_requires_login_again(self):
        text = re.sub(r"<[^>]+>", " ", self.page("/painel/servidores").body.decode()).lower()
        assert re.search(r"sair.{0,80}entr", text, re.S), "falta o aviso: para atualizar a lista, sair e entrar de novo"

    def test_navigation_links_to_my_servers_from_index_and_list(self):
        browser = self.logged_in()
        for path in ("/painel/", "/painel/servidores"):
            body = browser.get(path).body.decode()
            assert 'href="/painel/servidores"' in body and "Meus servidores" in body, path

    def test_list_has_security_headers_and_is_not_cached(self):
        response = self.page("/painel/servidores")
        assert response.code == 200, "a lista de servidores deve existir"
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"

    def test_list_does_not_leak_secrets(self):
        response = self.page("/painel/servidores")
        assert response.code == 200, "a lista de servidores deve existir"
        for secret in (OAUTH_SECRET, COOKIE_SECRET):
            assert secret not in response.body.decode()


class ServerListEmptyTest(ServersBase):
    raw_override = []

    def test_empty_state_has_message_and_no_invites(self):
        body = self.page("/painel/servidores").body.decode()
        assert "Você não gerencia nenhum servidor" in body
        assert invites(body) == []


class ServerListEscapingTest(ServersBase):
    raw_override = [raw_guild(100, "<script>alert(1)</script>Alfa", permissions="8"),
                    raw_guild(300, "<img src=x onerror=alert(2)>", permissions="8")]

    def test_guild_and_bot_names_are_html_escaped(self):
        self.world_bot_name = "<b>Bot</b>"
        self.pool.bots[1].user.name = "<i>Bot Dois</i>"
        body = self.page("/painel/servidores").body.decode()
        for raw in ("<script>alert(1)</script>", "<img src=x onerror=alert(2)>", "<i>Bot Dois</i>"):
            assert raw not in body, f"nome sem escape: {raw}"
        assert "&lt;script&gt;" in body


class OtherUserIsolationTest(ServersBase):
    def test_user_only_sees_and_opens_their_own_session_guilds(self):
        self.fake.user = {**DEFAULT_USER, "id": "2002", "username": "outro", "global_name": "Outro"}
        self.fake.guilds = [raw_guild(200, "Beta", permissions="32")]
        self.world.guilds["100"].add_member(2002, administrator=True)  # admin no bot, mas 100 não está na sessão
        browser = self.logged_in()
        response = browser.get("/painel/servidores")
        body = response.body.decode()
        assert response.code == 200 and "Beta" in body
        assert set(re.findall(r'href="/painel/servidores/(\d+)"', body)) == {"200"}
        assert "Alfa" not in body and "Delta" not in body
        assert browser.get("/painel/servidores/100").code == 404


# ============================================================================ detalhe / autorização

class ServerDetailTest(ServersBase):
    def test_authorized_detail_shows_guild_bots_links_to_real_categories_and_coming_soon_for_the_rest(self):
        response = self.page("/painel/servidores/100")
        body = response.body.decode()
        assert response.code == 200 and "Alfa" in body and "Bot Um" in body
        for category in CATEGORIES:
            assert category in body, f"categoria ausente: {category}"
        hrefs = set(re.findall(r'href="(/painel/servidores/100/[a-z]+)(?:\?[^"]*)?"', body))
        assert hrefs == {f"/painel/servidores/100/{c}" for c in ("player", "dj", "aparencia", "geral", "links", "canal")}
        assert 'aria-disabled="true"' not in body, "nenhuma categoria fica desabilitada depois da E4c"
        assert not re.findall(r"em breve", body, re.I)
        found = invites(body)
        assert [i["params"]["client_id"] for i in found] == ["2"], "convite G-19 só do bot ausente (Bot Dois)"
        assert "Bot Dois" in body, "o convite nomeia o bot ausente"

    def test_detail_has_security_headers_and_is_not_cached(self):
        response = self.page("/painel/servidores/100")
        assert response.code == 200, "o detalhe do servidor deve existir"
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"

    def test_detail_lists_every_ready_bot_present_in_the_guild(self):
        self.world.guilds["100"].add_member(UID, administrator=True)
        self.world.bot2.guilds[100] = self.world.guilds["100"]
        body = self.page("/painel/servidores/100").body.decode()
        assert "Bot Um" in body and "Bot Dois" in body

    def test_owner_and_manage_guild_can_open_the_detail(self):
        self.world.guilds["100"].members[UID] = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False, manage_guild=True))
        assert self.page("/painel/servidores/100").code == 200
        self.world.guilds["200"].owner_id = UID
        self.world.guilds["200"].members[UID] = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False, manage_guild=False))
        assert self.page("/painel/servidores/200").code == 200

    def test_detail_html_escapes_the_guild_name(self):
        self.world.guilds["100"].name = "<script>alert(1)</script>"
        body = self.page("/painel/servidores/100").body.decode()
        assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body

    def test_extra_path_segments_are_a_generic_404(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200, "a rota base do detalhe deve existir"
        for path in ("/painel/servidores/100/extra", "/painel/servidores/100/../200", "/painel/servidores/100%2f.."):
            assert browser.get(path).code == 404, path


class NotFoundIsGenericTest(ServersBase):
    CASES = {
        "id válido fora da sessão": "999",
        "id não numérico": "abc",
        "id gigante": "9" * 25,
        "sem permissão no bot (rebaixado)": "600",
        "sem bot do pool": "700",
        "sem bot (convite apenas)": "300",
        "fora da sessão mas com bot e admin": "500",
    }

    def test_all_denials_are_the_same_404_page(self):
        browser = self.logged_in()
        pages = {}
        for label, gid in self.CASES.items():
            response = browser.get(f"/painel/servidores/{gid}")
            assert response.code == 404, f"{label}: status {response.code}"
            assert response.headers["Content-Type"].startswith("text/html"), label
            body = response.body.decode()
            assert NOT_FOUND_TEXT in body, f"{label}: texto da mensagem ausente"
            visible = visible_text(body)
            for leak in ("Traceback", "tornado", "GuildAccessDenied", gid if gid.isdigit() and len(gid) < 6 else "\0"):
                assert leak not in visible or leak == "\0", f"{label}: vaza {leak!r}"
            pages[label] = (visible, response.headers.get("Content-Type"),
                            {n: response.headers.get(n) for n in EXPECTED_SECURITY_HEADERS})
        distinct = {key: page for key, page in pages.items()}
        reference_label, reference = next(iter(distinct.items()))
        different = [label for label, page in distinct.items() if page != reference]
        assert not different, f"respostas 404 diferentes de '{reference_label}': {different}"

    def test_denied_ids_outside_the_session_make_no_discord_calls(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200, "a rota do detalhe deve existir"
        before = self.pool.api_calls()
        for gid in ("999", "abc", "9" * 25, "500"):
            browser.get(f"/painel/servidores/{gid}")
        assert self.pool.api_calls() == before, "ids fora de session.guilds não podem gerar chamadas ao bot/Discord"

    def test_not_found_has_security_headers(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200, "a rota do detalhe deve existir"
        response = browser.get("/painel/servidores/999")
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name


class ServerCacheAndRevocationTest(ServersBase):
    def test_second_read_within_30_seconds_uses_the_decision_cache(self):
        browser = self.logged_in()
        guild = self.world.guilds["100"]
        browser.get("/painel/servidores/100")
        first = guild.calls["get_member"]
        self.clock.advance(10)
        assert browser.get("/painel/servidores/100").code == 200
        assert guild.calls["get_member"] == first

    def test_revoked_role_is_noticed_after_the_cache_window(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200
        self.world.guilds["100"].members[UID].guild_permissions.administrator = False
        self.clock.advance(31)
        assert browser.get("/painel/servidores/100").code == 404

    def test_user_who_left_the_guild_loses_access_after_the_cache_window(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200
        del self.world.guilds["100"].members[UID]
        self.clock.advance(31)
        assert browser.get("/painel/servidores/100").code == 404

    def test_bot_removed_from_the_guild_makes_it_not_found(self):
        browser = self.logged_in()
        assert browser.get("/painel/servidores/100").code == 200
        self.world.bot1.guilds.pop(100)
        self.clock.advance(31)
        assert browser.get("/painel/servidores/100").code == 404

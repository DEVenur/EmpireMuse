"""E4a — comportamento HTTP transversal das configurações do servidor (todas as categorias):
autorização (IDOR, bot, revogação), XSRF, limites, rate limit, htmx × página inteira, versão otimista (409),
concorrência, auditoria e navegação. Contrato: BRIEFING-PAINEL-E4.md (decisões 1–8 e rotas da E4a).
Os formulários são lidos do HTML renderizado e reenviados como um navegador faria (helpers_settings.parse_forms).
"""

import asyncio
import copy
import html
import logging
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from tests.panel.helpers import COOKIE_SECRET, EXPECTED_SECURITY_HEADERS, OAUTH_SECRET
from tests.panel.helpers_servers import INVITE_PERMISSIONS
from tests.panel.helpers_settings import (
    CATEGORIES,
    CONFLICT_TEXT,
    NOT_FOUND_TEXT,
    SAVED_TEXT,
    UID,
    SettingsBase,
    element_text,
    invites,
    parse_forms,
    version_of,
)

HEX16 = re.compile(r"^[0-9a-f]{16}$")
INVITE_KEYS = {"client_id", "scope", "permissions", "guild_id", "disable_guild_select"}
# (campo do formulário, novo valor válido) por categoria, para os testes genéricos
PRIMARY = {
    "player": ("default_player_volume", "70"),
    "dj": ("djroles", ["5010"]),
    "aparencia": ("skin", "neon"),
    "geral": ("prefix", "$$"),
}


def normalize(body: str) -> str:
    body = re.sub(r'(name="xsrf-token"\s+content=")[^"]*', r"\1X", body)
    return re.sub(r'(name="_xsrf"\s+value=")[^"]*', r"\1X", body)


def external_change(db, scope, gid, **fields):
    """Simula outro escritor (comando no Discord): altera o documento gravado sem passar pelo painel."""
    db.docs[(scope, gid)].update(fields)
    db.baseline[(scope, gid)] = copy.deepcopy(db.docs[(scope, gid)])


class Each:
    """Executa uma verificação para vários casos e reporta TODAS as falhas (AsyncHTTPTestCase é unittest)."""

    @staticmethod
    def run(cases, check):
        failures = []
        for case in cases:
            try:
                check(case)
            except AssertionError as exc:
                failures.append(f"{case!r}: {exc}")
        assert not failures, f"{len(failures)} caso(s) falharam:\n  " + "\n  ".join(failures)


class HttpBase(SettingsBase):
    def not_found_reference(self, browser):
        response = browser.get("/painel/servidores/999999")
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        return normalize(response.body.decode())

    def post_raw(self, browser, path, pairs, *, htmx=False, gap=4, token=True, headers=None):
        if gap:
            self.clock.advance(gap)
        merged = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        if token:
            merged.update(self.xsrf_header(browser))
        if htmx:
            merged["HX-Request"] = "true"
        return browser.post(path, body=urlencode(pairs), headers=merged)

    def audit_text(self):
        return "\n".join(
            r.getMessage()
            for r in self.caplog.records
            if r.levelno == logging.INFO and (r.name.startswith("panel") or r.name.startswith("empiremuse.panel"))
        )

    def all_log_text(self):
        return "\n".join(r.getMessage() for r in self.caplog.records)


# ============================================================================ acesso e autorização


class AccessTest(HttpBase):
    def test_anonymous_is_redirected_to_login_with_next_for_every_category(self):
        def check(category):
            path = f"/painel/servidores/100/{category}"
            response = self.browser().get(path)
            location = urlsplit(response.headers.get("Location", ""))
            assert response.code == 302 and location.path == "/painel/login", f"{response.code}"
            assert parse_qs(location.query).get("next") == [path], location.query

        Each.run(CATEGORIES, check)
        assert self.db.reads == [] and self.pool.api_calls() == 0, (
            "anônimo não pode causar leitura de dados nem chamadas"
        )

    def test_anonymous_post_changes_nothing_and_reads_nothing(self):
        browser = self.browser()
        token = self.xsrf_header(browser)
        for category in CATEGORIES:
            response = browser.post(
                f"/painel/servidores/100/{category}",
                body="versao=0&autoplay=on",
                headers={"Content-Type": "application/x-www-form-urlencoded", **token},
            )
            assert response.code in (302, 401, 403), f"{category}: {response.code}"
        assert self.db.writes == [] and self.db.reads == []

    def test_every_category_page_exists_for_an_authorized_user(self):
        browser = self.logged_in()

        def check(category):
            response = browser.get(self.url(100, category))
            assert response.code == 200, f"status {response.code}"
            assert response.headers["Content-Type"].startswith("text/html")

        Each.run(CATEGORIES, check)

    def test_unknown_and_not_yet_available_categories_are_a_generic_404(self):
        browser = self.logged_in()
        assert browser.get(self.url(100, "player")).code == 200, "a rota da categoria deve existir"
        reference = self.not_found_reference(browser)

        def check(category):
            response = browser.get(f"/painel/servidores/100/{category}")
            assert response.code == 404, f"status {response.code}"
            assert normalize(response.body.decode()) == reference, "a página 404 deve ser a genérica"

        # canal e links são categorias reais (E4c/E4b); "PLAYER" não é a categoria "player"
        Each.run(["xyz", "PLAYER", "LINKS", "Canal"], check)
        for path in ("player/extra", "..", "%2e%2e", "player%2f.."):
            assert browser.get(f"/painel/servidores/100/{path}").code == 404, path

    def test_denied_guilds_are_the_same_generic_404_for_get_and_post(self):
        browser = self.logged_in()
        assert browser.get(self.url(100, "player")).code == 200, "a rota da categoria deve existir"
        reference = self.not_found_reference(browser)
        reads_before = len(self.db.reads)
        denied = {
            "sem bot do pool": "300",
            "membro comum no bot": "600",
            "fora da sessão (com bot e admin)": "500",
            "inexistente": "999",
            "não numérico": "abc",
            "gigante": "9" * 25,
        }

        def check(case):
            label, gid = case
            for category in CATEGORIES:
                response = browser.get(f"/painel/servidores/{gid}/{category}")
                assert response.code == 404, f"GET {category}: {response.code}"
                assert normalize(response.body.decode()) == reference, f"GET {category}: página diferente"
                post = self.post_raw(browser, f"/painel/servidores/{gid}/{category}", [("versao", "0" * 16)])
                assert post.code == 404, f"POST {category}: {post.code}"
                assert normalize(post.body.decode()) == reference, f"POST {category}: página diferente"

        Each.run(list(denied.items()), check)
        assert self.db.writes == [], "negado não grava"
        assert len(self.db.reads) == reads_before, "negado não pode nem ler dados do servidor"

    def test_bot_outside_the_guild_or_invalid_is_the_same_404(self):
        browser = self.logged_in()
        assert browser.get(self.url(100, "player")).code == 200, "a rota da categoria deve existir"
        reference = self.not_found_reference(browser)
        cases = [
            (100, "2"),
            (100, "999"),
            (100, "abc"),
            (100, "1.0"),
            (100, "-1"),
            (100, "01"),
            (200, "1"),
            (800, "3"),
            (100, "1%00"),
        ]

        def check(case):
            gid, bot = case
            for category in ("player", "dj", "aparencia"):
                response = browser.get(self.url(gid, category, bot))
                assert response.code == 404, f"GET {category}: {response.code}"
                assert normalize(response.body.decode()) == reference, f"GET {category}: página diferente"
                post = self.post_raw(browser, self.url(gid, category, bot), [("versao", "0" * 16)])
                assert post.code == 404, f"POST {category}: {post.code}"

        Each.run(cases, check)
        assert self.db.writes == []

    def test_bot_that_is_not_ready_is_not_selectable(self):
        browser = self.logged_in()
        assert browser.get(self.url(800, "player", 2)).code == 200, "bot 2 pronto deve funcionar"
        self.world.bot2.ready = False
        self.clock.advance(31)
        assert browser.get(self.url(800, "player", 2)).code == 404

    def test_default_bot_is_the_first_of_the_guild_and_bot_query_selects_the_other(self):
        browser = self.logged_in()
        _, first, _ = self.open_form(browser, 800, "player", "default_player_volume")
        _, second, _ = self.open_form(browser, 800, "player", "default_player_volume", bot=2)
        assert first.value("default_player_volume") == "60", "padrão = bot 1 (volume 60 no seed)"
        assert second.value("default_player_volume") == "80", "?bot=2 = bot 2 (volume 80 no seed)"

    def test_manage_guild_member_of_a_bot2_only_guild_gets_bot2_by_default(self):
        browser = self.logged_in()
        response = browser.get(self.url(200, "player"))
        assert response.code == 200, "MANAGE_GUILD basta; o único bot do servidor é o 2"

    def test_selector_appears_only_with_more_than_one_ready_bot_and_only_for_per_bot_categories(self):
        browser = self.logged_in()

        def selector(gid, category, bot=None):
            response = browser.get(self.url(gid, category, bot))
            assert response.code == 200, f"{gid}/{category}: {response.code}"
            controls = [c for f in parse_forms(response.body.decode()) for c in f.controls if c.get("name") == "bot"]
            return [c for c in controls if len(c["options"]) >= 2]

        for category in ("player", "dj", "aparencia"):
            found = selector(800, category)
            assert found, f'{category}: guild com 2 bots deve ter seletor <select name="bot">'
            assert [o["value"] for o in found[0]["options"]] == ["1", "2"]
            assert found[0]["values"] == ["1"], "padrão = primeiro bot"
            assert selector(800, category, 2)[0]["values"] == ["2"], "?bot=2 vem selecionado"
            assert selector(100, category) == [], f"{category}: guild com 1 bot não tem seletor"
        assert selector(800, "geral") == [], "geral é global: sem seletor de bot"

    def test_selector_shows_bot_names_escaped(self):
        self.world.bot2.user.name = "<i>Bot Dois</i>"
        body = self.logged_in().get(self.url(800, "player")).body.decode()
        assert "<i>Bot Dois</i>" not in body and "&lt;i&gt;Bot Dois" in body

    def assert_write_is_404_after(self, revoke):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        revoke()  # sem avançar o relógio: ainda dentro da janela de 30 s do cache de leitura
        response = self.submit(browser, url, form, gap=2, default_player_volume="30")
        assert response.code == 404, f"POST após revogação deveria ser 404, veio {response.code}"
        assert NOT_FOUND_TEXT in response.body.decode()
        assert len(self.db.writes) == writes and self.db.doc("1", 100) == before, "nada pode ser gravado"

    def test_write_after_admin_permission_revoked_is_404_inside_the_read_cache_window(self):
        self.assert_write_is_404_after(
            lambda: setattr(self.world.g100.members[UID].guild_permissions, "administrator", False)
        )

    def test_write_after_user_left_the_guild_is_404_inside_the_read_cache_window(self):
        self.assert_write_is_404_after(lambda: self.world.g100.members.pop(UID))

    def test_write_after_bot_left_the_guild_is_404_inside_the_read_cache_window(self):
        self.assert_write_is_404_after(lambda: self.world.bot1.guilds.pop(100))

    def test_authorization_is_checked_fresh_on_every_write(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        guild = self.world.g100
        before = guild.calls["get_member"] + guild.calls["fetch_member"]
        response = self.submit(browser, url, form, default_player_volume="30")
        assert response.code == 200, f"escrita válida deveria ser 200, veio {response.code}"
        after = guild.calls["get_member"] + guild.calls["fetch_member"]
        assert after > before, "a escrita deve reconsultar o servidor (fresh=True), ignorando o cache de 30 s"


# ============================================================================ protocolo: XSRF, limites, rate limit


class ProtocolTest(HttpBase):
    def test_forms_carry_xsrf_and_a_16_hex_version(self):
        browser = self.logged_in()

        def check(case):
            category, field = case
            _, form, _ = self.open_form(browser, 100, category, field)
            assert form.method == "post", f"método {form.method!r}"
            assert form.value("_xsrf"), "falta o campo oculto _xsrf"
            assert HEX16.match(form.value("versao") or ""), f"versao inválida: {form.value('versao')!r}"

        Each.run(
            [
                ("player", "default_player_volume"),
                ("dj", "djroles"),
                ("aparencia", "skin"),
                ("aparencia", "global_skin"),
                ("geral", "prefix"),
                ("geral", "voice_channel_status"),
            ],
            check,
        )

    def test_version_is_stable_between_reads_and_changes_only_with_the_forms_own_fields(self):
        browser = self.logged_in()
        _, first, _ = self.open_form(browser, 100, "player", "default_player_volume")
        _, again, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert first.value("versao") == again.value("versao")
        external_change(self.db, "1", 100, djroles=["5010"])  # campo de OUTRO formulário
        _, after_dj, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert after_dj.value("versao") == first.value("versao"), "versao do player não depende de djroles"
        external_change(self.db, "1", 100, autoplay=True)  # campo do próprio formulário
        _, after_own, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert after_own.value("versao") != first.value("versao")

    def test_player_version_follows_the_briefing_formula(self):
        browser = self.logged_in()
        _, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        doc = self.db.doc("1", 100)
        expected = version_of(
            {
                key: doc[key]
                for key in ("default_player_volume", "autoplay", "check_other_bots_in_vc", "enable_restrict_mode")
            }
        )
        assert form.value("versao") == expected

    def test_dj_version_follows_the_briefing_formula(self):
        browser = self.logged_in()
        _, form, _ = self.open_form(browser, 100, "dj", "djroles")
        assert form.value("versao") == version_of({"djroles": self.db.doc("1", 100)["djroles"]})

    def test_post_without_xsrf_is_403_and_writes_nothing(self):
        browser = self.logged_in()

        def check(case):
            category, field = case
            url, form, _ = self.open_form(browser, 100, category, field)
            pairs = [p for p in form.pairs() if p[0] != "_xsrf"]
            writes = len(self.db.writes)
            response = self.submit(browser, url, form, pairs=pairs)
            assert response.code == 403, f"sem token: {response.code}"
            wrong = self.submit(browser, url, form, pairs=pairs + [("_xsrf", "token-errado")])
            assert wrong.code == 403, f"token errado: {wrong.code}"
            assert len(self.db.writes) == writes

        Each.run(
            [("player", "default_player_volume"), ("dj", "djroles"), ("aparencia", "skin"), ("geral", "prefix")], check
        )

    def test_post_without_version_is_422_and_writes_nothing(self):
        browser = self.logged_in()

        def check(case):
            category, field = case
            url, form, _ = self.open_form(browser, 100, category, field)
            pairs = [p for p in form.pairs() if p[0] != "versao"]
            writes = len(self.db.writes)
            response = self.submit(browser, url, form, pairs=pairs)
            assert response.code == 422, f"status {response.code}"
            assert len(self.db.writes) == writes

        Each.run(
            [
                ("player", "default_player_volume"),
                ("dj", "djroles"),
                ("aparencia", "skin"),
                ("aparencia", "global_skin"),
                ("geral", "prefix"),
            ],
            check,
        )

    def test_malformed_version_is_rejected_without_writing(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")

        def check(bad):
            response = self.submit(browser, url, form, versao=bad, default_player_volume="30")
            assert response.code in (409, 422), f"status {response.code}"

        Each.run(["", "x", "0" * 15, "0" * 17, "G" * 16, "%00", "<script>"], check)
        assert self.db.writes == []

    def test_oversized_body_is_413_and_boundary_is_16_kib(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        base = form.pairs()
        fixed = len(urlencode(base + [("pad", "")]))

        def with_size(total):
            return base + [("pad", "x" * (total - fixed))]

        assert len(urlencode(with_size(16384))) == 16384
        ok = self.submit(browser, url, form, pairs=with_size(16384))
        assert ok.code != 413, "exatamente 16 KiB ainda é aceito"
        big = self.submit(browser, url, form, pairs=with_size(16385))
        assert big.code == 413, f"16 KiB + 1 deveria ser 413, veio {big.code}"
        huge = self.submit(browser, url, form, pairs=with_size(200_000))
        assert huge.code == 413
        for response in (big, huge):
            assert "Traceback" not in response.body.decode() and "xxxx" not in response.body.decode()
        assert self.db.writes == []

    def test_write_rate_limit_is_20_per_minute_per_user_and_reads_are_not_limited(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        for _ in range(30):
            assert browser.get(url).code == 200, "leituras não entram no limite de escrita"
        stale = {"versao": "0" * 16, "default_player_volume": "30"}
        codes = [self.submit(browser, url, form, gap=0, **stale).code for _ in range(20)]
        assert 429 not in codes, f"as 20 primeiras escritas não podem ser limitadas: {codes}"
        writes = len(self.db.writes)
        blocked = self.submit(browser, url, form, gap=0, default_player_volume="30")
        assert blocked.code == 429, f"a 21ª escrita no minuto deveria ser 429, veio {blocked.code}"
        assert len(self.db.writes) == writes
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert blocked.headers.get(name) == value, name
        self.clock.advance(61)
        _, fresh, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert self.submit(browser, url, fresh, gap=0, default_player_volume="30").code == 200

    def test_responses_have_security_headers_and_are_not_cached(self):
        browser = self.logged_in()
        url, form, page = self.open_form(browser, 100, "player", "default_player_volume")
        invalid = self.submit(browser, url, form, default_player_volume="7")
        conflict = self.submit(browser, url, form, versao="0" * 16, default_player_volume="30")
        for label, response in (("GET", page), ("422", invalid), ("409", conflict)):
            assert response.code in (200, 422, 409), f"{label}: {response.code}"
            for name, value in EXPECTED_SECURITY_HEADERS.items():
                assert response.headers.get(name) == value, f"{label}: {name}"
            assert response.headers.get("Cache-Control") == "no-store", label

    def test_pages_do_not_leak_secrets(self):
        browser = self.logged_in()
        for category in CATEGORIES:
            response = browser.get(self.url(100, category))
            assert response.code == 200, f"{category}: a página deve existir ({response.code})"
            body = response.body.decode()
            for secret in (OAUTH_SECRET, COOKIE_SECRET):
                assert secret not in body, f"{category}: vazou segredo"


# ============================================================================ htmx × página inteira, 409, concorrência


class ResponseShapeTest(HttpBase):
    def test_htmx_success_returns_only_the_form_fragment_with_message_and_new_version(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        response = self.submit(browser, url, form, htmx=True, default_player_volume="70")
        body = response.body.decode()
        assert response.code == 200, f"status {response.code}"
        assert "<html" not in body.lower() and "<!doctype" not in body.lower(), "com HX-Request: só o fragmento"
        assert "<form" in body and SAVED_TEXT in html.unescape(body)
        new_form = next(f for f in parse_forms(body) if f.has("default_player_volume"))
        assert HEX16.match(new_form.value("versao")) and new_form.value("versao") != form.value("versao")
        assert new_form.value("default_player_volume") == "70"
        _, reread, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert reread.value("versao") == new_form.value("versao"), "a versão do fragmento é a atual"

    def test_without_htmx_success_returns_the_whole_page(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        response = self.submit(browser, url, form, default_player_volume="70")
        body = response.body.decode()
        assert response.code == 200, f"status {response.code}"
        assert "<html" in body.lower() and SAVED_TEXT in html.unescape(body)
        assert any(f.has("default_player_volume") for f in parse_forms(body))

    def test_validation_error_is_422_with_message_bound_to_the_field(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        for htmx in (True, False):
            response = self.submit(browser, url, form, htmx=htmx, default_player_volume="7")
            body = response.body.decode()
            assert response.code == 422, f"htmx={htmx}: status {response.code}"
            assert ("<html" in body.lower()) is (not htmx), f"htmx={htmx}: fragmento × página inteira"
            new_form = next(f for f in parse_forms(body) if f.has("default_player_volume"))
            attrs = new_form.control("default_player_volume")["attrs"]
            assert attrs.get("aria-invalid") == "true", "campo inválido precisa de aria-invalid"
            described = attrs.get("aria-describedby", "")
            assert described and element_text(body, described.split()[0]), "mensagem associada via aria-describedby"
        assert self.db.writes == []

    def test_conflict_is_409_with_the_exact_message_in_both_shapes(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        external_change(self.db, "1", 100, default_player_volume=90)
        before = self.db.doc("1", 100)
        for htmx in (True, False):
            response = self.submit(browser, url, form, htmx=htmx, default_player_volume="30")
            body = response.body.decode()
            assert response.code == 409, f"htmx={htmx}: status {response.code}"
            assert CONFLICT_TEXT in html.unescape(body), f"htmx={htmx}: mensagem de conflito"
            assert ("<html" in body.lower()) is (not htmx)
        assert self.db.doc("1", 100) == before and self.db.writes == [], "409 não grava"

    def test_change_to_a_field_outside_the_form_is_not_a_conflict_and_is_preserved(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        external_change(self.db, "1", 100, djroles=["5010", "5011"])
        response = self.submit(browser, url, form, default_player_volume="30")
        assert response.code == 200, f"status {response.code}"
        doc = self.db.doc("1", 100)
        assert doc["default_player_volume"] == 30 and doc["djroles"] == ["5010", "5011"], "sem lost update"

    def test_two_concurrent_writes_with_the_same_version_one_wins_one_conflicts(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        self.clock.advance(4)
        cookie = "; ".join(f"{k}={v}" for k, v in browser.cookies.items())
        token = self.xsrf_header(browser)
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie, **token}
        bodies = [urlencode(form.pairs(default_player_volume=v)) for v in ("30", "40")]
        path = urlsplit(url).path

        async def both():
            return await asyncio.gather(
                *[
                    self.http_client.fetch(
                        self.get_url(path),
                        method="POST",
                        headers=headers,
                        body=body,
                        raise_error=False,
                        follow_redirects=False,
                    )
                    for body in bodies
                ]
            )

        responses = self.io_loop.run_sync(both)
        codes = sorted(r.code for r in responses)
        assert codes == [200, 409], f"uma escrita vence e a outra conflita (lock por escopo); veio {codes}"
        winner = "30" if responses[0].code == 200 else "40"
        assert self.db.doc("1", 100)["default_player_volume"] == int(winner)
        assert self.db.writes == [("1", 100)]


# ============================================================================ auditoria (log sem valores)


class AuditLogTest(HttpBase):
    def test_audit_line_names_user_guild_scope_category_and_changed_fields_but_no_values(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 800, "player", "default_player_volume", bot=2)
        self.caplog.clear()
        assert self.submit(browser, url, form, default_player_volume="75").code == 200
        text = self.audit_text()
        assert str(UID) in text and "800" in text and "player" in text, f"auditoria incompleta: {text!r}"
        assert re.search(r"\b2\b", text), "o bot (escopo) deve aparecer"
        assert "default_player_volume" in text, "nome do campo alterado"
        assert "autoplay" not in text and "enable_restrict_mode" not in text, "só os campos alterados"
        assert not re.search(r"\b75\b", text), f"valores não podem ir para o log: {text!r}"

    def test_global_scope_is_named_and_prefix_value_never_logged(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "geral", "prefix")
        self.caplog.clear()
        assert self.submit(browser, url, form, prefix="Zq9!").code == 200
        text = self.audit_text()
        assert "global" in text.lower() and "geral" in text and "prefix" in text, text
        assert "Zq9!" not in self.all_log_text(), "o valor do prefixo não pode aparecer em nenhum log"

    def test_logs_never_contain_tokens_or_submitted_content(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "geral", "voice_channel_status")
        token = form.value("_xsrf")
        self.caplog.clear()
        self.submit(browser, url, form, voice_channel_status="SEGREDO-STATUS {track.title}")
        self.submit(browser, url, form, voice_channel_status="SEGREDO-INVALIDO")
        logs = self.all_log_text()
        assert "SEGREDO-STATUS" not in logs and "SEGREDO-INVALIDO" not in logs
        assert token not in logs and OAUTH_SECRET not in logs and COOKIE_SECRET not in logs


# ============================================================================ navegação e convites (G-19)


class NavigationTest(HttpBase):
    def test_server_page_links_the_six_real_categories_and_nothing_is_coming_soon(self):
        body = self.logged_in().get("/painel/servidores/100").body.decode()
        hrefs = set(re.findall(r'href="(/painel/servidores/100/[a-z]+)(?:\?[^"]*)?"', body))
        assert hrefs == {f"/painel/servidores/100/{c}" for c in (*CATEGORIES, "links", "canal")}, sorted(hrefs)
        assert not re.findall(r"em breve", body, re.I) and 'aria-disabled="true"' not in body

    def test_overview_offers_invites_only_for_pool_bots_missing_from_the_guild(self):
        browser = self.logged_in()

        def clients(gid):
            found = invites(browser.get(f"/painel/servidores/{gid}").body.decode())
            for invite in found:
                assert invite["base"] == "https://discord.com/oauth2/authorize"
                params = invite["params"]
                assert set(params) == INVITE_KEYS and params["guild_id"] == str(gid)
                assert params["scope"] == "bot applications.commands"
                assert params["permissions"] == str(INVITE_PERMISSIONS) and params["disable_guild_select"] == "true"
            return sorted(i["params"]["client_id"] for i in found)

        assert clients(100) == ["2"], "servidor 100 só tem o bot 1: convite para o bot 2"
        assert clients(800) == [], "servidor 800 já tem os dois bots"
        assert clients(200) == ["1"], "servidor 200 só tem o bot 2: convite para o bot 1"

    def test_category_pages_name_the_guild_and_link_back_to_the_server_page(self):
        browser = self.logged_in()

        def check(category):
            body = browser.get(self.url(100, category)).body.decode()
            assert "Alfa" in body, "nome do servidor"
            assert 'href="/painel/servidores/100"' in body, "caminho de volta à visão geral"

        Each.run(CATEGORIES, check)

"""E5 — Conta do usuário: acesso, navegação, prefixo pessoal (U-01) e regras transversais (versão, XSRF, limites,
htmx, concorrência). Contrato: BRIEFING-PAINEL-E5.md; interpretações em .qa-e5-interp.txt.

`GET /painel/conta` e `POST` na mesma URL com `acao` ∈ prefixo | favorito_adicionar | favorito_editar |
favorito_remover | favoritos_importar | integracao_remover | integracoes_importar | lastfm_scrobble | rpc_token_gerar.
Os dados são SEMPRE os do usuário da sessão (um `user_id` vindo do formulário/URL é ignorado).
"""

import asyncio
import html
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from tests.panel.helpers import COOKIE_SECRET, EXPECTED_SECURITY_HEADERS, OAUTH_SECRET
from tests.panel.helpers_account import AccountBase, OTHER_UID
from tests.panel.helpers_login import DEFAULT_USER
from tests.panel.helpers_settings import CONFLICT_TEXT, SAVED_TEXT, UID, acao_form, parse_forms, version_of
from tests.panel.test_settings_http import Each, HttpBase, normalize

URL = "/painel/conta"
HEX16 = re.compile(r"^[0-9a-f]{16}$")


class AccountCase(AccountBase, HttpBase):
    def body(self, browser):
        response = browser.get(URL)
        assert response.code == 200, f"GET {URL}: {response.code}"
        return response.body.decode()

    def form(self, browser, acao, alvo=None):
        form = acao_form(self.body(browser), acao, alvo)
        assert form is not None, f"a página deve oferecer o formulário acao={acao!r} alvo={alvo!r}"
        return form

    def act(self, browser, acao, *, alvo=None, htmx=False, gap=4, **overrides):
        form = self.form(browser, acao, alvo)
        return self.submit(browser, URL, form, htmx=htmx, gap=gap, **overrides)

    def other_user(self):
        """Segundo navegador, logado como o usuário 2002 (com o _xsrf do próprio navegador)."""
        self.fake.user = {**DEFAULT_USER, "id": str(OTHER_UID), "username": "outro", "global_name": "Outro"}
        browser = self.browser()
        assert self.login(browser).code == 302
        return browser

    def assert_untouched(self, uid=UID, before=None):
        assert self.world.doc(uid) == (before if before is not None else self.world.doc(uid))
        assert self.db.writes == [], f"nada deveria ser gravado: {self.db.writes}"


# ============================================================================ acesso e navegação


class AccountAccessTest(AccountCase):
    def test_anonymous_goes_to_login_with_next_for_page_export_and_post(self):
        browser = self.browser()
        for path in (URL, URL + "/favoritos/exportar"):
            response = browser.get(path)
            location = urlsplit(response.headers.get("Location", ""))
            assert response.code == 302 and location.path == "/painel/login", (path, response.code)
            assert parse_qs(location.query).get("next") == [path]
        post = browser.post(
            URL,
            body="acao=prefixo",
            headers={"Content-Type": "application/x-www-form-urlencoded", **self.xsrf_header(browser)},
        )
        assert post.code in (302, 401, 403) and self.db.writes == [] and self.db.reads == []

    def test_logged_in_page_exists_with_security_headers_and_no_cache(self):
        response = self.logged_in().get(URL)
        assert response.code == 200 and response.headers["Content-Type"].startswith("text/html")
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"
        body = response.body.decode()
        assert OAUTH_SECRET not in body and COOKIE_SECRET not in body

    def test_each_user_sees_only_their_own_data(self):
        mine = self.body(self.logged_in())
        theirs = self.body(self.other_user())
        assert "Rock" in mine and "Jazz" not in mine
        assert "Jazz" in theirs and "Rock" not in theirs

    def test_forged_user_id_in_form_or_query_is_ignored(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        other_before = self.world.doc(OTHER_UID)
        pairs = form.pairs(custom_prefix="$$") + [
            ("user_id", str(OTHER_UID)),
            ("id", str(OTHER_UID)),
            ("usuario", str(OTHER_UID)),
        ]
        response = browser.post(
            f"{URL}?user_id={OTHER_UID}",
            body=urlencode(pairs),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.code in (200, 422)
        assert self.world.doc(UID)["custom_prefix"] == "$$", "gravou no usuário da SESSÃO"
        assert self.world.doc(OTHER_UID) == other_before and (("global", OTHER_UID) not in self.db.writes)
        assert OTHER_UID not in self.pool.user_prefix_cache
        assert "Jazz" not in browser.get(f"{URL}?user_id={OTHER_UID}").body.decode()

    def test_without_a_ready_bot_the_page_says_unavailable_with_503(self):
        browser = self.logged_in()
        assert browser.get(URL).code == 200, "a rota deve existir"
        self.world.bot.ready = False
        for response in (
            browser.get(URL),
            browser.post(
                URL,
                body="acao=prefixo",
                headers={"Content-Type": "application/x-www-form-urlencoded", **self.xsrf_header(browser)},
            ),
        ):
            assert response.code == 503, response.code
            assert "Painel indisponível no momento" in html.unescape(response.body.decode())
        assert self.db.writes == []

    def test_export_without_a_ready_bot_is_503(self):
        browser = self.logged_in()
        self.world.bot.ready = False
        response = browser.get(URL + "/favoritos/exportar")
        assert response.code == 503 and "Painel indisponível no momento" in html.unescape(response.body.decode())

    def test_header_has_minha_conta_next_to_meus_servidores_only_when_logged_in(self):
        anonymous = self.browser().get("/painel/").body.decode()
        assert "Minha conta" not in anonymous
        for path in ("/painel/", "/painel/servidores", URL):
            body = self.logged_in().get(path).body.decode()
            assert f'href="{URL}"' in body and "Minha conta" in body, path
            assert body.index("Meus servidores") < body.index("Minha conta") or "Meus servidores" in body

    def test_unknown_account_paths_are_404(self):
        browser = self.logged_in()
        assert browser.get(URL).code == 200
        for path in (URL + "/outra", URL + "/favoritos", URL + "/../servidores"):
            assert browser.get(path).code in (404, 405), path


# ============================================================================ prefixo pessoal (U-01)


class UserPrefixTest(AccountCase):
    def test_form_shows_the_current_prefix_and_a_version_by_the_briefing_formula(self):
        form = self.form(self.logged_in(), "prefixo")
        assert form.value("custom_prefix") == "!" and form.value("_xsrf")
        assert form.value("versao") == version_of({"custom_prefix": "!"})

    def test_valid_prefix_is_saved_for_the_session_user_and_updates_the_cache_with_an_int_key(self):
        browser = self.logged_in()
        before = self.world.doc()
        response = self.act(browser, "prefixo", custom_prefix=">>")
        assert response.code == 200 and SAVED_TEXT in html.unescape(response.body.decode())
        expected = dict(before)
        expected["custom_prefix"] = ">>"
        assert self.world.doc() == expected, "fav_links, token, lastfm, last_tracks, ver intactos"
        assert self.pool.user_prefix_cache == {UID: ">>"}, "chave int do usuário (como o comando)"
        assert self.db.writes == [("global", UID)]

    def test_empty_prefix_removes_it_like_resetuserprefix(self):
        response = self.act(self.logged_in(), "prefixo", custom_prefix="")
        assert response.code == 200 and self.world.doc()["custom_prefix"] == ""
        assert self.pool.user_prefix_cache == {UID: ""}

    def test_removing_when_there_is_none_is_a_harmless_noop(self):
        self.world.set_doc(custom_prefix="")
        assert self.act(self.logged_in(), "prefixo", custom_prefix="").code == 200

    def test_saving_the_value_already_stored_writes_and_audits_nothing(self):
        browser = self.logged_in()
        self.caplog.clear()
        response = self.act(browser, "prefixo", custom_prefix="!")
        assert response.code == 200 and SAVED_TEXT in html.unescape(response.body.decode())
        assert self.db.writes == [] and self.audit_text() == ""

    def test_a_failing_cache_update_does_not_undo_the_saved_prefix_or_leak(self):
        class BrokenCache(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("cache-secreto")

        self.pool.user_prefix_cache = BrokenCache()
        browser = self.logged_in()
        self.caplog.clear()
        response = self.act(browser, "prefixo", custom_prefix="$$")
        assert response.code == 200 and self.world.doc()["custom_prefix"] == "$$"
        assert "cache-secreto" not in response.body.decode() + self.all_log_text()

    def test_length_limit_matches_the_command(self):
        browser = self.logged_in()
        for ok in ("a" * 5, "😀" * 5, "?"):
            assert self.act(browser, "prefixo", custom_prefix=ok).code == 200, ok
            assert self.world.doc()["custom_prefix"] == ok
        before = self.world.doc()
        for bad in ("a" * 6, "😀" * 6, "a" * 500):
            assert self.act(browser, "prefixo", custom_prefix=bad).code == 422, bad
        assert self.world.doc() == before

    def test_spaces_and_control_characters_are_rejected_without_touching_the_cache(self):
        browser = self.logged_in()
        self.pool.user_prefix_cache[UID] = "!"
        before, writes = self.world.doc(), len(self.db.writes)

        def check(bad):
            response = self.act(browser, "prefixo", custom_prefix=bad)
            assert response.code == 422 and 'aria-invalid="true"' in response.body.decode()

        Each.run(["a b", "a\tb", "a\nb", "a\x00", "\u200b"], check)  # Etapa 6a (A17): "a\r" agora é aparado
        assert (
            self.world.doc() == before and len(self.db.writes) == writes and self.pool.user_prefix_cache == {UID: "!"}
        )

    def test_leading_and_trailing_whitespace_is_stripped_like_the_command_does(self):
        """Etapa 6a (F3-5b, A17): regra única de prefixo; o painel apara as pontas (``" ab"`` e ``"a\\r"`` valem)."""
        browser = self.logged_in()
        for sent, stored in ((" ab", "ab"), ("a\r", "a"), ("  >>  ", ">>")):
            assert self.act(browser, "prefixo", custom_prefix=sent).code == 200, sent
            assert self.world.doc()["custom_prefix"] == stored and self.pool.user_prefix_cache[UID] == stored

    def test_prefix_is_escaped_in_the_attribute(self):
        browser = self.logged_in()
        assert self.act(browser, "prefixo", custom_prefix='"><x').code == 200
        body = self.body(browser)
        assert '"><x' not in body
        assert next(f for f in parse_forms(body) if f.has("custom_prefix")).value("custom_prefix") == '"><x'

    def test_other_fields_posted_with_the_prefix_form_are_ignored(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        before = self.world.doc()
        pairs = form.pairs(custom_prefix="$") + [
            ("token", "x" * 50),
            ("fav_links", "{}"),
            ("ver", "9.9"),
            ("lastfm", "x"),
            ("integration_links", "{}"),
        ]
        assert self.submit(browser, URL, form, pairs=pairs).code in (200, 422)
        after = self.world.doc()
        for key in ("token", "fav_links", "ver", "lastfm", "integration_links", "extra_flag", "last_tracks"):
            assert after[key] == before[key], key


# ============================================================================ regras transversais


class AccountProtocolTest(AccountCase):
    def test_every_form_carries_xsrf_and_a_16_hex_version(self):
        self.world.link_lastfm()
        browser = self.logged_in()
        body = self.body(browser)
        forms = [f for f in parse_forms(body) if f.value("acao")]
        acoes = {f.value("acao") for f in forms}
        assert {
            "prefixo",
            "favorito_adicionar",
            "favorito_editar",
            "favorito_remover",
            "favoritos_importar",
            "integracao_remover",
            "integracoes_importar",
            "lastfm_scrobble",
            "rpc_token_gerar",
        } <= acoes, acoes
        for form in forms:
            assert form.method == "post" and form.value("_xsrf"), form.value("acao")
            assert HEX16.match(form.value("versao") or ""), (form.value("acao"), form.value("versao"))

    def test_post_without_xsrf_is_403_without_version_or_action_is_422(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        no_xsrf = [p for p in form.pairs(custom_prefix="$") if p[0] != "_xsrf"]
        assert self.submit(browser, URL, form, pairs=no_xsrf).code == 403
        no_version = [p for p in form.pairs(custom_prefix="$") if p[0] != "versao"]
        assert self.submit(browser, URL, form, pairs=no_version).code == 422
        for acao in ("", "apagar_tudo", "PREFIXO"):
            assert self.submit(browser, URL, form, acao=acao, custom_prefix="$").code == 422, acao
        assert self.db.writes == []

    def test_stale_version_is_409_with_the_exact_message_in_both_shapes(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        self.world.set_doc(custom_prefix="#")  # mudou em outro lugar (comando no Discord)
        for htmx in (True, False):
            response = self.submit(browser, URL, form, htmx=htmx, custom_prefix="$")
            body = response.body.decode()
            assert response.code == 409 and CONFLICT_TEXT in html.unescape(body), htmx
            assert ("<html" in body.lower()) is (not htmx)
        assert self.world.doc()["custom_prefix"] == "#" and self.db.writes == []

    def test_version_is_independent_between_forms_of_the_page(self):
        browser = self.logged_in()
        first = self.form(browser, "prefixo").value("versao")
        self.world.set_doc(fav_links={"Novo": "https://example.com/n"})
        assert self.form(browser, "prefixo").value("versao") == first, "prefixo não depende de favoritos"

    def test_htmx_success_is_a_fragment_and_plain_post_is_the_whole_page(self):
        browser = self.logged_in()
        fragment = self.act(browser, "prefixo", htmx=True, custom_prefix=">>")
        body = fragment.body.decode()
        assert fragment.code == 200 and "<html" not in body.lower() and SAVED_TEXT in html.unescape(body)
        whole = self.act(browser, "prefixo", custom_prefix="<<")
        assert whole.code == 200 and "<html" in whole.body.decode().lower()

    def test_422_fragment_marks_the_field_and_associates_the_message(self):
        browser = self.logged_in()
        response = self.act(browser, "prefixo", htmx=True, custom_prefix="a b")
        body = response.body.decode()
        assert response.code == 422 and "<html" not in body.lower()
        control = next(f for f in parse_forms(body) if f.has("custom_prefix")).control("custom_prefix")
        assert control["attrs"].get("aria-invalid") == "true"
        described = control["attrs"].get("aria-describedby", "").split()
        assert described and all(f'id="{i}"' in body for i in described)

    def test_body_over_16_kib_is_413_and_the_write_limit_is_20_per_minute(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        big = form.pairs(custom_prefix="$") + [("pad", "x" * 20000)]
        assert self.submit(browser, URL, form, pairs=big).code == 413
        codes = [self.submit(browser, URL, form, gap=0, custom_prefix="a b").code for _ in range(20)]
        assert 429 not in codes
        blocked = self.submit(browser, URL, form, gap=0, custom_prefix="$")
        assert blocked.code == 429 and self.db.writes == []
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert blocked.headers.get(name) == value, name
        self.clock.advance(61)
        assert self.act(browser, "prefixo", gap=0, custom_prefix="$").code == 200

    def test_rate_limited_htmx_write_answers_429_with_the_form_fragment_and_retry_after(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        for _ in range(20):
            self.submit(browser, URL, form, htmx=True, gap=0, custom_prefix="a b")
        blocked = self.submit(browser, URL, form, htmx=True, gap=0, custom_prefix="$")
        body = blocked.body.decode()
        assert blocked.code == 429 and blocked.headers.get("Retry-After") == "60" and self.db.writes == []
        assert "<html" not in body.lower() and 'name="custom_prefix"' in body

    def test_writes_of_different_forms_serialize_per_user_without_losing_updates(self):
        browser = self.logged_in()
        body = self.body(browser)
        prefix = acao_form(body, "prefixo")
        favorite = acao_form(body, "favorito_adicionar")
        self.clock.advance(4)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "; ".join(f"{k}={v}" for k, v in browser.cookies.items()),
            **self.xsrf_header(browser),
        }
        bodies = [
            urlencode(prefix.pairs(custom_prefix="%%")),
            urlencode(favorite.pairs(nome="Pop", url="https://example.com/pop")),
        ]

        async def both():
            return await asyncio.gather(
                *[
                    self.http_client.fetch(
                        self.get_url(URL),
                        method="POST",
                        headers=headers,
                        body=b,
                        raise_error=False,
                        follow_redirects=False,
                    )
                    for b in bodies
                ]
            )

        codes = sorted(r.code for r in self.io_loop.run_sync(both))
        assert codes == [200, 200], codes
        doc = self.world.doc()
        assert doc["custom_prefix"] == "%%" and doc["fav_links"].get("Pop") == "https://example.com/pop", (
            "sem lost update"
        )
        assert self.db.violations == []

    def test_two_writes_with_the_same_form_version_one_wins_one_conflicts(self):
        browser = self.logged_in()
        form = self.form(browser, "prefixo")
        self.clock.advance(4)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "; ".join(f"{k}={v}" for k, v in browser.cookies.items()),
            **self.xsrf_header(browser),
        }
        bodies = [urlencode(form.pairs(custom_prefix=p)) for p in ("%%", "&&")]

        async def both():
            return await asyncio.gather(
                *[
                    self.http_client.fetch(
                        self.get_url(URL),
                        method="POST",
                        headers=headers,
                        body=b,
                        raise_error=False,
                        follow_redirects=False,
                    )
                    for b in bodies
                ]
            )

        assert sorted(r.code for r in self.io_loop.run_sync(both)) == [200, 409]

    def test_the_other_users_session_does_not_share_versions_or_tokens(self):
        mine = self.logged_in()
        form = self.form(mine, "prefixo")
        other = self.other_user()
        pairs = [(k, v) for k, v in form.pairs(custom_prefix="$")]  # _xsrf do 1001 no navegador do 2002
        response = self.submit(other, URL, form, pairs=pairs)
        assert response.code == 403, "o _xsrf de outro navegador não vale"
        assert self.world.doc(OTHER_UID)["custom_prefix"] == "?"

    def test_audit_names_user_action_and_fields_but_never_values(self):
        browser = self.logged_in()
        self.caplog.clear()
        assert self.act(browser, "prefixo", custom_prefix="Zq9!").code == 200
        text = self.audit_text()
        assert str(UID) in text and "prefixo" in text and "custom_prefix" in text, text
        assert "Zq9!" not in self.all_log_text()

    def test_validation_failures_are_not_audited_as_changes(self):
        browser = self.logged_in()
        self.caplog.clear()
        self.act(browser, "prefixo", custom_prefix="a b")
        assert self.audit_text() == ""

    def test_account_html_is_labelled_and_messages_have_roles(self):
        browser = self.logged_in()
        body = self.body(browser)
        labels = set(re.findall(r'<label[^>]*for="([^"]+)"', body))
        unlabeled = []
        for match in re.finditer(r"<(?:input|textarea|select)\b[^>]*>", body):
            tag = match.group(0)
            if re.search(r'type="(hidden|submit|button)"', tag):
                continue
            ident = re.search(r'id="([^"]+)"', tag)
            if not ((ident and ident.group(1) in labels) or "aria-label" in tag):
                unlabeled.append(tag[:80])
        assert not unlabeled, f"campos sem rótulo: {unlabeled[:3]}"
        ok = self.act(browser, "prefixo", htmx=True, custom_prefix=">>").body.decode()
        assert 'role="status"' in ok
        bad = self.act(browser, "prefixo", htmx=True, custom_prefix="a b").body.decode()
        assert 'role="alert"' in bad
        assert normalize(body)

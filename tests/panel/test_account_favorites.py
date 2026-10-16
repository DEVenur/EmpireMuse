"""E5 — Favoritos (U-02) e Integrações (U-03) da conta. Regras do CÓDIGO (interactions.py: FavModalAdd/FavModalImport
nos modos fav_manager e integrations_manager; music.py: /fav add) onde ele difere do briefing (ver .qa-e5-interp.txt).

Favoritos: `fav_links` = {nome: url} (texto). Adicionar: nome 2–25, URL 10–200 extraída com URL_REG.findall()[0].
Importar: nome ≤ USER_FAV_MAX_NAME_LENGTH, URL ≤ USER_FAV_MAX_URL_LENGTH e URL_REG.match (grava só o match).
Limite MAX_USER_FAVS (0 = ilimitado; dono do bot isento), lido de bot.config a cada requisição.
Integrações: `integration_links`; remover e importar (sem requisição externa); adicionar por URL fica fora da v1.
"""
import html
import json
import re

from tests.panel.helpers import EXPECTED_SECURITY_HEADERS
from tests.panel.helpers_account import OTHER_UID
from tests.panel.helpers_settings import UID, acao_form, acao_forms, parse_forms, version_of
from tests.panel.test_account_page import URL, AccountCase
from tests.panel.test_settings_http import Each

BASE = "https://example.com/"


def full(count, prefix="F"):
    return {f"{prefix}{i:02d}": f"{BASE}{i}" for i in range(count)}


class FavoritesBase(AccountCase):
    def favs(self):
        return self.world.doc()["fav_links"]

    def add(self, browser, nome, url, **kw):
        return self.act(browser, "favorito_adicionar", nome=nome, url=url, **kw)

    def do_import(self, browser, payload, **kw):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return self.act(browser, "favoritos_importar", dados=raw, **kw)


# ============================================================================ leitura

class FavoritesReadTest(FavoritesBase):
    def test_lists_names_and_urls_of_the_session_user_with_a_list_wide_version(self):
        self.world.set_doc(fav_links={"Rock": BASE + "rock", "Jazz": BASE + "jazz"})
        body = self.body(self.logged_in())
        assert "Rock" in body and BASE + "rock" in body and "Jazz" in body
        versions = {f.value("versao") for f in parse_forms(body)
                    if (f.value("acao") or "").startswith("favorit")}
        assert versions == {version_of({"fav_links": self.favs()})}, versions

    def test_count_and_limit_are_shown(self):
        text = html.unescape(re.sub(r"<[^>]+>", " ", self.body(self.logged_in())))
        assert re.search(r"\b1 de 10\b", text), "contagem 'N de MAX_USER_FAVS' (limite da config)"
        self.world.config["MAX_USER_FAVS"] = 0
        text = html.unescape(re.sub(r"<[^>]+>", " ", self.body(self.logged_in())))
        assert re.search(r"ilimitad", text, re.I)

    def test_forms_exist_per_link_and_for_add_and_import(self):
        body = self.body(self.logged_in())
        assert acao_form(body, "favorito_adicionar").has("nome") and acao_form(body, "favorito_adicionar").has("url")
        assert acao_form(body, "favorito_editar", "Rock") and acao_form(body, "favorito_remover", "Rock")
        assert acao_form(body, "favoritos_importar").has("dados")

    def test_names_and_urls_are_escaped(self):
        self.world.set_doc(fav_links={"<b>x</b>": BASE + "?a=<s>&b=1"})
        body = self.body(self.logged_in())
        assert "<b>x</b>" not in body and "<s>" not in body and "&lt;b&gt;x&lt;/b&gt;" in body

    def test_dangerous_urls_never_become_href_and_external_links_are_noopener(self):
        self.world.set_doc(fav_links={"a": "javascript:alert(1)", "b": "data:text/html,x", "c": "HTTP://UP.example",
                                      "d": "https://ok.example/x", "e": '//evil.example/x', "f": 'https://q.example/"onmouseover="x'})
        body = self.body(self.logged_in())
        hrefs = [html.unescape(h) for h in re.findall(r'<a\b[^>]*href="([^"]*)"', body)]
        assert not [h for h in hrefs if re.match(r"\s*(javascript|data|vbscript):", h, re.I) or h.startswith("//")]
        assert 'onmouseover="x' not in body
        for tag in re.findall(r'<a\b[^>]*href="https?://ok\.example/x"[^>]*>', body):
            assert "noopener" in tag and "noreferrer" in tag


# ============================================================================ adicionar / editar / remover

class FavoritesWriteTest(FavoritesBase):
    def test_valid_add_writes_only_the_new_entry_as_name_to_url_text(self):
        browser = self.logged_in()
        before = self.world.doc()
        response = self.add(browser, "Pop", BASE + "pop")
        assert response.code == 200
        expected = dict(before)
        expected["fav_links"] = {**before["fav_links"], "Pop": BASE + "pop"}
        assert self.world.doc() == expected and self.db.writes == [("global", UID)]
        assert isinstance(self.favs()["Pop"], str), "valor é a URL em texto (não objeto)"

    def test_url_is_extracted_with_url_reg_like_the_command(self):
        browser = self.logged_in()
        cases = {"A1": ("  https://example.com/a  ", "https://example.com/a"),
                 "B2": ("veja https://example.com/b agora", "https://example.com/b"),
                 "C3": ("javascript:alert(1)//https://example.com/c", "https://example.com/c")}
        for name, (sent, expected) in cases.items():
            assert self.add(browser, name, sent).code == 200, name
            assert self.favs()[name] == expected

    def test_add_boundaries_follow_the_modal(self):
        browser = self.logged_in()
        url200 = BASE + "a" * (200 - len(BASE))
        assert self.add(browser, "N" * 25, url200).code == 200 and self.favs()["N" * 25] == url200
        assert self.add(browser, "Ab", BASE + "min").code == 200

    def test_invalid_add_is_422_on_the_field_and_writes_nothing(self):
        browser = self.logged_in()
        before = self.world.doc()
        cases = {"nome 1": ("a", BASE + "x"), "nome 26": ("n" * 26, BASE + "x"), "nome vazio": ("", BASE + "x"),
                 "nome espaços": ("   ", BASE + "x"), "duplicado": ("Rock", BASE + "x"),
                 "controle": ("a\nb", BASE + "x"), "url ftp": ("Ok", "ftp://example.com/x"),
                 "url javascript": ("Ok", "javascript:alert(1)"), "sem esquema": ("Ok", "example.com/x"),
                 "url curta": ("Ok", "http://a"), "url 201": ("Ok", BASE + "a" * (201 - len(BASE)))}

        def check(item):
            label, (nome, url) = item
            response = self.add(browser, nome, url)
            assert response.code == 422 and 'aria-invalid="true"' in response.body.decode(), response.code

        Each.run(list(cases.items()), check)
        assert self.world.doc() == before and self.db.writes == []

    def test_edit_changes_the_url_but_never_the_name_or_position(self):
        self.world.set_doc(fav_links={"Primeiro": BASE + "1", "Rock": BASE + "rock", "Ultimo": BASE + "3"})
        browser = self.logged_in()
        assert self.act(browser, "favorito_editar", alvo="Rock", url=BASE + "novo").code == 200
        assert list(self.favs()) == ["Primeiro", "Rock", "Ultimo"] and self.favs()["Rock"] == BASE + "novo"

    def test_edit_of_an_unknown_name_and_invalid_urls_are_422(self):
        browser = self.logged_in()
        before = self.world.doc()
        form = self.form(browser, "favorito_editar", "Rock")
        assert self.submit(browser, URL, form, nome="Fantasma", url=BASE + "z").code == 422
        browser2 = self.logged_in()
        for url in ("javascript:alert(1)", "", "ftp://x.example/a", BASE + "a" * 250):
            assert self.act(browser2, "favorito_editar", alvo="Rock", url=url).code == 422, url
        assert self.world.doc() == before

    def test_remove_deletes_only_that_entry_and_unknown_names_are_422(self):
        self.world.set_doc(fav_links={"Rock": BASE + "r", "Jazz": BASE + "j"})
        browser = self.logged_in()
        assert self.act(browser, "favorito_remover", alvo="Rock").code == 200
        assert self.favs() == {"Jazz": BASE + "j"}
        before = self.world.doc()
        assert self.act(browser, "favorito_remover", alvo="Jazz", nome="jazz").code == 422, "nomes são exatos"
        assert self.act(browser, "favorito_remover", alvo="Jazz", nome="Fantasma").code == 422
        assert self.world.doc() == before

    def test_writes_never_touch_other_fields_or_the_other_user(self):
        other_before = self.world.doc(OTHER_UID)
        before = self.world.doc()
        self.add(self.logged_in(), "Pop", BASE + "pop")
        after = self.world.doc()
        for key in ("custom_prefix", "token", "lastfm", "integration_links", "last_tracks", "ver", "extra_flag"):
            assert after[key] == before[key], key
        assert self.world.doc(OTHER_UID) == other_before


# ============================================================================ limite MAX_USER_FAVS e dono

class FavoritesLimitTest(FavoritesBase):
    def test_adding_a_new_name_is_refused_at_the_limit(self):
        self.world.set_doc(fav_links=full(10))
        browser = self.logged_in()
        before = self.world.doc()
        response = self.add(browser, "Extra", BASE + "x")
        assert response.code == 422 and self.world.doc() == before
        assert self.act(browser, "favorito_editar", alvo="F03", url=BASE + "novo").code == 200, "editar não consome vaga"

    def test_limit_is_read_from_the_config_on_every_request(self):
        self.world.set_doc(fav_links=full(10))
        browser = self.logged_in()
        assert self.add(browser, "Extra", BASE + "x").code == 422
        self.world.config["MAX_USER_FAVS"] = 11
        assert self.add(browser, "Extra", BASE + "x").code == 200

    def test_zero_means_unlimited(self):
        self.world.config["MAX_USER_FAVS"] = 0
        self.world.set_doc(fav_links=full(40))
        assert self.add(self.logged_in(), "Extra", BASE + "x").code == 200 and len(self.favs()) == 41

    def test_the_bot_owner_is_exempt_from_the_limit(self):
        self.world.owner_ids.add(UID)
        self.world.set_doc(fav_links=full(10))
        browser = self.logged_in()
        assert self.add(browser, "Extra", BASE + "x").code == 200
        assert self.do_import(browser, full(15, "G")).code == 200 and len(self.favs()) == 26

    def test_a_non_owner_with_the_same_data_is_refused(self):
        self.world.owner_ids.add(OTHER_UID)       # só o outro usuário é dono
        self.world.set_doc(fav_links=full(10))
        assert self.add(self.logged_in(), "Extra", BASE + "x").code == 422


# ============================================================================ importar / exportar

class FavoritesImportExportTest(FavoritesBase):
    def test_valid_import_merges_and_overwrites_same_names(self):
        browser = self.logged_in()
        before = self.world.doc()
        payload = {"Rock": BASE + "novo", "Pop": BASE + "pop"}
        assert self.do_import(browser, payload).code == 200
        expected = dict(before)
        expected["fav_links"] = {"Rock": BASE + "novo", "Pop": BASE + "pop"}
        assert self.world.doc() == expected and self.db.writes == [("global", UID)]

    def test_import_stores_only_the_url_reg_match_and_normalizes_names(self):
        browser = self.logged_in()
        payload = {"  Lixo  ": "https://example.com/ <img src=x onerror=alert(1)>", "Dois": "https://example.com/b?x=1 depois"}
        assert self.do_import(browser, payload).code == 200
        assert self.favs()["Lixo"] == "https://example.com/" and self.favs()["Dois"] == "https://example.com/b?x=1"
        assert "  Lixo  " not in self.favs()

    def test_invalid_payloads_are_422_and_write_nothing(self):
        browser = self.logged_in()
        before = self.world.doc()
        cases = {
            "json inválido": "{nao", "lista": [BASE + "a"], "vazio": {}, "valor não é texto": {"Aa": 5},
            "valor é objeto": {"Aa": {"url": BASE + "a"}}, "url inválida": {"Aa": "ftp://x.example/a"},
            "url javascript": {"Aa": "javascript:alert(1)"}, "url maior que USER_FAV_MAX_URL_LENGTH (90)": {"Aa": BASE + "a" * 80},
            "nome maior que USER_FAV_MAX_NAME_LENGTH (35)": {"n" * 36: BASE + "a"}, "nome 1 caractere": {"x": BASE + "a"},
            "nome só espaços": {"   ": BASE + "a"}, "nome com quebra": {"a\nb": BASE + "a"},
            "'> fav:' não escapa da validação": {"> fav: x": "javascript:alert(1)"},
            "colisão após strip": {" Aa": BASE + "a", "Aa ": BASE + "b"},
        }

        def check(item):
            label, payload = item
            response = self.do_import(browser, payload)
            assert response.code == 422 and 'aria-invalid="true"' in response.body.decode(), response.code

        Each.run(list(cases.items()), check)
        assert self.world.doc() == before and self.db.writes == []

    def test_import_limits_are_read_from_the_config_per_request(self):
        browser = self.logged_in()
        payload = {"Aa": BASE + "a" * 80}                      # 100 caracteres
        assert self.do_import(browser, payload).code == 422
        self.world.config["USER_FAV_MAX_URL_LENGTH"] = 120
        assert self.do_import(browser, payload).code == 200
        assert self.do_import(browser, {"x" * 40: BASE + "a"}).code == 422
        self.world.config["USER_FAV_MAX_NAME_LENGTH"] = 40
        assert self.do_import(browser, {"x" * 40: BASE + "a"}).code == 200

    def test_import_space_rule_counts_overwritten_names_as_free(self):
        self.world.set_doc(fav_links=full(9))
        browser = self.logged_in()
        before = self.world.doc()
        assert self.do_import(browser, {"N1": BASE + "1", "N2": BASE + "2"}).code == 422, "9 + 2 novos > 10"
        assert self.world.doc() == before
        assert self.do_import(browser, {"F00": BASE + "novo", "N1": BASE + "1"}).code == 200, "F00 já existe: 9 + 1 = 10"
        assert len(self.favs()) == 10

    def test_import_file_larger_than_the_limit_is_422(self):
        assert self.do_import(self.logged_in(), full(11, "G")).code == 422

    def test_export_is_the_import_format_as_an_attachment(self):
        self.world.set_doc(fav_links={"Rock": BASE + "r", "Jazz": BASE + "j"})
        response = self.logged_in().get(URL + "/favoritos/exportar")
        assert response.code == 200
        assert json.loads(response.body) == {"Rock": BASE + "r", "Jazz": BASE + "j"}
        assert response.headers["Content-Type"].startswith("application/json")
        assert response.headers["Content-Disposition"].lower().startswith("attachment")
        assert response.headers.get("Cache-Control") == "no-store"
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert self.db.writes == []

    def test_export_returns_only_the_session_users_data(self):
        other = self.other_user()
        assert json.loads(other.get(URL + "/favoritos/exportar").body) == {"Jazz": "https://example.com/jazz"}

    def test_export_then_import_round_trips_without_changes(self):
        browser = self.logged_in()
        exported = browser.get(URL + "/favoritos/exportar").body.decode()
        before = self.world.doc()
        assert self.do_import(browser, exported).code == 200 and self.world.doc() == before

    def test_stale_version_is_409_for_every_favorite_action(self):
        browser = self.logged_in()
        body = self.body(browser)
        forms = {"favorito_adicionar": (acao_form(body, "favorito_adicionar"), {"nome": "Pop", "url": BASE + "p"}),
                 "favorito_editar": (acao_form(body, "favorito_editar", "Rock"), {"url": BASE + "e"}),
                 "favorito_remover": (acao_form(body, "favorito_remover", "Rock"), {}),
                 "favoritos_importar": (acao_form(body, "favoritos_importar"), {"dados": json.dumps({"Aa": BASE + "a"})})}
        self.world.set_doc(fav_links={"Rock": BASE + "r", "Mudou": BASE + "m"})
        before = self.world.doc()
        for acao, (form, over) in forms.items():
            assert self.submit(browser, URL, form, **over).code == 409, acao
        assert self.world.doc() == before


# ============================================================================ integrações

class IntegrationsTest(FavoritesBase):
    def integrations(self):
        return self.world.doc()["integration_links"]

    def do_import(self, browser, payload, **kw):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return self.act(browser, "integracoes_importar", dados=raw, **kw)

    def test_lists_titles_and_urls_escaped_and_offers_remove_and_import_but_not_add_by_url(self):
        self.world.set_doc(integration_links={"<i>Canal</i>": {"url": BASE + "c"}, "Texto": BASE + "t"})
        body = self.body(self.logged_in())
        assert "<i>Canal</i>" not in body and "&lt;i&gt;Canal&lt;/i&gt;" in body and BASE + "t" in body
        assert acao_form(body, "integracao_remover", "Texto") and acao_form(body, "integracoes_importar")
        assert acao_form(body, "integracao_adicionar") is None, "adicionar por URL fica fora da v1"

    def test_remove_deletes_only_that_title_and_unknown_is_422(self):
        self.world.set_doc(integration_links={"A1": {"url": BASE + "a"}, "B2": {"url": BASE + "b"}})
        browser = self.logged_in()
        assert self.act(browser, "integracao_remover", alvo="A1").code == 200
        assert list(self.integrations()) == ["B2"]
        before = self.world.doc()
        assert self.act(browser, "integracao_remover", alvo="B2", nome="Fantasma").code == 422
        assert self.world.doc() == before

    def test_adding_by_url_is_an_unknown_action(self):
        browser = self.logged_in()
        form = self.form(browser, "integracoes_importar")
        before = self.world.doc()
        assert self.submit(browser, URL, form, acao="integracao_adicionar", nome="X", url=BASE + "x").code == 422
        assert self.world.doc() == before

    def test_import_accepts_the_commands_format_and_the_panels_own_export_shape(self):
        browser = self.logged_in()
        payload = {"Por texto": BASE + "t", "Por objeto": {"url": BASE + "o", "avatar": "https://example.com/av.png"}}
        assert self.do_import(browser, payload).code == 200
        stored = self.integrations()
        assert stored["Por texto"]["url"] == BASE + "t" and stored["Por objeto"]["url"] == BASE + "o"
        assert stored["Por objeto"].get("avatar") == "https://example.com/av.png"
        assert stored["Meu canal"] == {"url": "https://example.com/canal", "avatar": "https://example.com/a.png"}

    def test_import_stores_only_the_url_match_and_never_calls_the_outside(self):
        browser = self.logged_in()
        payload = {"Spotify": "https://open.spotify.com/user/alguem texto depois",
                   "Deezer": "https://www.deezer.com/br/profile/123", "Youtube": "https://www.youtube.com/@canal"}
        assert self.do_import(browser, payload).code == 200
        assert self.integrations()["Spotify"]["url"] == "https://open.spotify.com/user/alguem"
        assert self.world.external_calls == [], "nenhuma requisição externa (Spotify/Deezer/YouTube)"

    def test_invalid_import_is_422_and_writes_nothing(self):
        browser = self.logged_in()
        before = self.world.doc()
        cases = {"json inválido": "{x", "lista": [BASE], "vazio": {}, "url inválida": {"Aa": "ftp://x.example/a"},
                 "url javascript": {"Aa": "javascript:alert(1)"}, "url > 150": {"Aa": BASE + "a" * 140},
                 "título > 90": {"t" * 91: BASE + "a"}, "título vazio": {"   ": BASE + "a"},
                 "valor sem url": {"Aa": {"avatar": BASE + "a.png"}}, "avatar inválido": {"Aa": {"url": BASE + "a", "avatar": "javascript:x"}},
                 "valor número": {"Aa": 5}, "'> itg:' não escapa da validação": {"> itg: x": "javascript:alert(1)"}}

        def check(item):
            label, payload = item
            assert self.do_import(browser, payload).code == 422, label

        Each.run(list(cases.items()), check)
        assert self.world.doc() == before and self.db.writes == []

    def test_limit_max_user_integrations_with_owner_exemption_and_zero_unlimited(self):
        self.world.config["MAX_USER_INTEGRATIONS"] = 2
        browser = self.logged_in()
        before = self.world.doc()
        assert self.do_import(browser, {"A1": BASE + "1", "B2": BASE + "2"}).code == 422, "1 existente + 2 novas > 2"
        assert self.do_import(browser, {"Meu canal": BASE + "novo", "B2": BASE + "2"}).code == 200, "sobrescrever é grátis"
        assert self.do_import(browser, {"C3": BASE + "3"}).code == 422
        self.world.owner_ids.add(UID)
        assert self.do_import(browser, {"C3": BASE + "3", "D4": BASE + "4", "E5": BASE + "5"}).code == 200
        self.world.owner_ids.clear()
        self.world.config["MAX_USER_INTEGRATIONS"] = 0
        assert self.do_import(browser, {f"X{i}": BASE + str(i) for i in range(30)}).code == 200
        assert before["integration_links"]["Meu canal"]

    def test_version_follows_the_briefing_formula_and_stale_is_409(self):
        browser = self.logged_in()
        form = self.form(browser, "integracoes_importar")
        assert form.value("versao") == version_of({"integration_links": self.integrations()})
        self.world.set_doc(integration_links={"Outro": {"url": BASE + "o"}})
        assert self.submit(browser, URL, form, dados=json.dumps({"Aa": BASE + "a"})).code == 409

    def test_integrations_writes_keep_the_other_fields(self):
        before = self.world.doc()
        self.do_import(self.logged_in(), {"Aa": BASE + "a"})
        after = self.world.doc()
        for key in ("custom_prefix", "fav_links", "token", "lastfm", "last_tracks", "ver", "extra_flag"):
            assert after[key] == before[key], key

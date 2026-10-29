"""E5 — Favoritos (U-02) e Integrações (U-03) da conta. Regras do CÓDIGO (interactions.py: FavModalAdd/FavModalImport
nos modos fav_manager e integrations_manager; music.py: /fav add) onde ele difere do briefing (ver .qa-e5-interp.txt).

Favoritos: `fav_links` = {nome: url} (texto). Adicionar: nome 2–25, URL 10–200 extraída com URL_REG.findall()[0].
Importar: nome ≤ USER_FAV_MAX_NAME_LENGTH, URL ≤ USER_FAV_MAX_URL_LENGTH e URL_REG.match (grava só o match).
Limite MAX_USER_FAVS (0 = ilimitado; dono do bot isento), lido de bot.config a cada requisição.
Integrações: `integration_links`; remover e importar (sem requisição externa); adicionar por URL fica fora da v1.
"""

import json

from tests.panel.helpers_settings import UID, acao_form, version_of
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

    def test_invalid_add_is_422_on_the_field_and_writes_nothing(self):
        browser = self.logged_in()
        before = self.world.doc()
        cases = {
            "nome 1": ("a", BASE + "x"),
            "nome 26": ("n" * 26, BASE + "x"),
            "nome vazio": ("", BASE + "x"),
            "nome espaços": ("   ", BASE + "x"),
            "duplicado": ("Rock", BASE + "x"),
            "controle": ("a\nb", BASE + "x"),
            "url ftp": ("Ok", "ftp://example.com/x"),
            "url javascript": ("Ok", "javascript:alert(1)"),
            "sem esquema": ("Ok", "example.com/x"),
            "url curta": ("Ok", "http://a"),
            "url 201": ("Ok", BASE + "a" * (201 - len(BASE))),
        }

        def check(item):
            label, (nome, url) = item
            response = self.add(browser, nome, url)
            assert response.code == 422 and 'aria-invalid="true"' in response.body.decode(), response.code

        Each.run(list(cases.items()), check)
        assert self.world.doc() == before and self.db.writes == []

    def test_remove_deletes_only_that_entry_and_unknown_names_are_422(self):
        self.world.set_doc(fav_links={"Rock": BASE + "r", "Jazz": BASE + "j"})
        browser = self.logged_in()
        assert self.act(browser, "favorito_remover", alvo="Rock").code == 200
        assert self.favs() == {"Jazz": BASE + "j"}
        before = self.world.doc()
        assert self.act(browser, "favorito_remover", alvo="Jazz", nome="jazz").code == 422, "nomes são exatos"
        assert self.act(browser, "favorito_remover", alvo="Jazz", nome="Fantasma").code == 422
        assert self.world.doc() == before


# ============================================================================ limite MAX_USER_FAVS e dono


class FavoritesLimitTest(FavoritesBase):
    def test_zero_means_unlimited(self):
        self.world.config["MAX_USER_FAVS"] = 0
        self.world.set_doc(fav_links=full(40))
        assert self.add(self.logged_in(), "Extra", BASE + "x").code == 200 and len(self.favs()) == 41


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

    def test_import_limits_are_read_from_the_config_per_request(self):
        browser = self.logged_in()
        payload = {"Aa": BASE + "a" * 80}  # 100 caracteres
        assert self.do_import(browser, payload).code == 422
        self.world.config["USER_FAV_MAX_URL_LENGTH"] = 120
        assert self.do_import(browser, payload).code == 200
        assert self.do_import(browser, {"x" * 40: BASE + "a"}).code == 422
        self.world.config["USER_FAV_MAX_NAME_LENGTH"] = 40
        # Etapa 3 (F3-5b, D2): o teto é min(configuração, 25); subir a configuração para 40 não libera nomes de 26+
        assert self.do_import(browser, {"x" * 40: BASE + "a"}).code == 422
        assert self.do_import(browser, {"x" * 26: BASE + "a"}).code == 422
        assert self.do_import(browser, {"x" * 25: BASE + "a"}).code == 200

    def test_export_returns_only_the_session_users_data(self):
        other = self.other_user()
        assert json.loads(other.get(URL + "/favoritos/exportar").body) == {"Jazz": "https://example.com/jazz"}


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

    def test_import_accepts_the_commands_format_and_the_panels_own_export_shape(self):
        browser = self.logged_in()
        payload = {"Por texto": BASE + "t", "Por objeto": {"url": BASE + "o", "avatar": "https://example.com/av.png"}}
        assert self.do_import(browser, payload).code == 200
        stored = self.integrations()
        assert stored["Por texto"]["url"] == BASE + "t" and stored["Por objeto"]["url"] == BASE + "o"
        assert stored["Por objeto"].get("avatar") == "https://example.com/av.png"
        assert stored["Meu canal"] == {"url": "https://example.com/canal", "avatar": "https://example.com/a.png"}

    def test_version_follows_the_briefing_formula_and_stale_is_409(self):
        browser = self.logged_in()
        form = self.form(browser, "integracoes_importar")
        assert form.value("versao") == version_of({"integration_links": self.integrations()})
        self.world.set_doc(integration_links={"Outro": {"url": BASE + "o"}})
        assert self.submit(browser, URL, form, dados=json.dumps({"Aa": BASE + "a"})).code == 409

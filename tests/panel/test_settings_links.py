"""E4b — Links fixos do servidor (G-16): listar, adicionar, editar, remover, importar, exportar.

Regras extraídas do CÓDIGO (utils/music/interactions.py: FavModalAdd/FavModalImport/FavMenuView, modo
guild_fav_manager) onde ele diverge do briefing; ver .qa-e4b-interp.txt. Escopo: bot (`player_controller.fav_links`).
"""
import copy
import html
import json
import re

from tests.panel.helpers import EXPECTED_SECURITY_HEADERS
from tests.panel.helpers_settings import (CONFLICT_TEXT, NOT_FOUND_TEXT, SAVED_TEXT, UID, acao_form, acao_forms,
                                          parse_forms)
from tests.panel.test_settings_http import Each, HttpBase, external_change

HEX16 = re.compile(r"^[0-9a-f]{16}$")
MAX_LINKS = 25
BASE_URL = "https://example.com/"


def link(url="https://example.com/x", description=""):
    return {"url": url, "description": description}


def set_links(db, bot, gid, links):
    doc = db.doc(bot, gid)
    doc["player_controller"]["fav_links"] = links
    external_change(db, bot, gid, player_controller=doc["player_controller"])


def full_list(count=MAX_LINKS):
    return {f"L{i:02d}": link(f"{BASE_URL}{i}", f"d{i}") for i in range(count)}


class LinksBase(HttpBase):
    def links_url(self, gid, bot=None):
        return self.url(gid, "links", bot)

    def body_of(self, browser, gid, bot=None):
        response = browser.get(self.links_url(gid, bot))
        assert response.code == 200, f"GET {self.links_url(gid, bot)} deveria ser 200, veio {response.code}"
        return response.body.decode()

    def act(self, browser, gid, acao, *, alvo=None, bot=None, htmx=False, **overrides):
        """GET da página, escolhe o formulário `acao` (do link `alvo`, se houver) e envia com `overrides`."""
        url = self.links_url(gid, bot)
        form = acao_form(self.body_of(browser, gid, bot), acao, alvo)
        assert form is not None, f"a página não oferece o formulário acao={acao!r} alvo={alvo!r}"
        return self.submit(browser, url, form, htmx=htmx, **overrides)

    def stored(self, bot="1", gid=100):
        return self.db.doc(bot, gid)["player_controller"]["fav_links"]

    def add(self, browser, nome, url, descricao="", gid=100, bot=None, htmx=False):
        return self.act(browser, gid, "adicionar", bot=bot, htmx=htmx, nome=nome, url=url, descricao=descricao)

    def assert_untouched(self, before, writes):
        assert self.db.doc("1", 100) == before and len(self.db.writes) == writes, "nada deveria ser gravado"


# ============================================================================ leitura

class LinksReadTest(LinksBase):
    def test_lists_name_url_description_count_and_a_list_wide_version(self):
        body = self.body_of(self.logged_in(), 100)
        assert "Fixo" in body and "https://example.com/x" in body
        assert re.search(r"\b1 de 25\b", html.unescape(re.sub(r"<[^>]+>", " ", body))), "contagem 'N de 25'"
        versions = {f.value("versao") for f in parse_forms(body) if f.value("acao")}
        assert len(versions) == 1 and HEX16.match(next(iter(versions))), f"versao única da lista: {versions}"

    def test_each_bot_has_its_own_list(self):
        browser = self.logged_in()
        first, second = self.body_of(browser, 800), self.body_of(browser, 800, bot=2)
        assert "example.com/um" in first and "example.com/dois" not in first
        assert "example.com/dois" in second and "do bot 2" in second and "example.com/um" not in second

    def test_bot_selector_only_with_two_bots(self):
        browser = self.logged_in()
        def selects(gid):
            return [c for f in parse_forms(self.body_of(browser, gid)) for c in f.controls
                    if c.get("name") == "bot" and len(c["options"]) >= 2]
        assert selects(800) and not selects(100)

    def test_forms_exist_for_add_import_and_per_link_edit_and_remove(self):
        body = self.body_of(self.logged_in(), 100)
        assert acao_form(body, "adicionar") and acao_form(body, "importar")
        assert acao_form(body, "editar", "Fixo") and acao_form(body, "remover", "Fixo")
        assert acao_form(body, "adicionar").has("nome") and acao_form(body, "adicionar").has("url")
        assert acao_form(body, "adicionar").has("descricao") and acao_form(body, "importar").has("dados")
        assert acao_form(body, "adicionar").value("_xsrf")

    def test_values_from_discord_and_users_are_escaped(self):
        set_links(self.db, "1", 100, {"<b>x</b>": link("https://example.com/?a=<s>&b=1", "<i>d</i>")})
        body = self.body_of(self.logged_in(), 100)
        for raw in ("<b>x</b>", "<s>", "<i>d</i>"):
            assert raw not in body, f"sem escape: {raw}"
        assert "&lt;b&gt;x&lt;/b&gt;" in body

    def test_urls_become_links_only_for_http_and_https_with_rel_noopener_noreferrer(self):
        set_links(self.db, "1", 100, {"a": link("javascript:alert(1)"), "b": link("data:text/html,x"),
                                     "c": link("HTTP://UPPER.example/"), "d": link("https://ok.example/x"),
                                     "e": link("//evil.example/x"), "f": link("vbscript:x")})
        body = self.body_of(self.logged_in(), 100)
        hrefs = re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>', body)
        bad = [h for h in hrefs if re.match(r"\s*(javascript|data|vbscript):", html.unescape(h), re.I)
               or html.unescape(h).startswith("//")]
        assert not bad, f"href perigoso: {bad}"
        for tag in re.findall(r'<a\b[^>]*href="https?://ok\.example/x"[^>]*>', body):
            assert "noopener" in tag and "noreferrer" in tag, tag

    def test_without_a_request_channel_the_page_explains_and_hides_add_and_import(self):
        browser = self.logged_in()
        for channel in (None, "9999"):  # não configurado / configurado mas o bot não o enxerga
            doc = self.db.doc("1", 100)
            doc["player_controller"]["channel"] = channel
            external_change(self.db, "1", 100, player_controller=doc["player_controller"])
            body = self.body_of(browser, 100)
            assert "Configure o canal de pedidos primeiro" in html.unescape(body), channel
            assert acao_form(body, "adicionar") is None and acao_form(body, "importar") is None, channel
            assert "Fixo" in body, "a lista continua visível"

    def test_page_has_security_headers_and_is_not_cached(self):
        response = self.logged_in().get(self.links_url(100))
        assert response.code == 200
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"


# ============================================================================ adicionar

class LinksAddTest(LinksBase):
    def test_valid_add_writes_only_the_new_entry(self):
        browser = self.logged_in()
        before = self.db.doc("1", 100)
        response = self.add(browser, "Rock", "https://example.com/rock", "Clássicos")
        assert response.code == 200 and SAVED_TEXT in html.unescape(response.body.decode())
        expected = copy.deepcopy(before)
        expected["player_controller"]["fav_links"]["Rock"] = link("https://example.com/rock", "Clássicos")
        assert self.db.doc("1", 100) == expected, "canal, message_id, skin, ver e demais campos intactos"
        assert list(self.stored()) == ["Fixo", "Rock"] and self.db.writes == [("1", 100)]

    def test_description_is_optional(self):
        assert self.add(self.logged_in(), "Sem desc", "https://example.com/s").code == 200
        assert self.stored()["Sem desc"] == link("https://example.com/s", "")

    def test_url_is_extracted_like_the_command_does(self):
        browser = self.logged_in()
        cases = {"A1": ("  https://example.com/a  ", "https://example.com/a"),
                 "B2": ("veja https://example.com/b agora", "https://example.com/b"),
                 "C3": ("javascript:alert(1)//https://example.com/c", "https://example.com/c")}
        for name, (sent, expected) in cases.items():
            assert self.add(browser, name, sent).code == 200, name
            assert self.stored()[name]["url"] == expected

    def test_boundaries_follow_the_modal_not_the_user_favs_config(self):
        browser = self.logged_in()
        long_url = BASE_URL + "a" * (250 - len(BASE_URL))
        assert len(long_url) == 250
        assert self.add(browser, "N" * 25, long_url, "d" * 50).code == 200, "nome 25, url 250, descrição 50"
        assert self.add(browser, "Ab", "https://example.com/min", "abc").code == 200, "nome 2, descrição 3"
        stored = self.stored()
        assert stored["N" * 25]["url"] == long_url and stored["Ab"]["description"] == "abc"

    def test_invalid_input_is_422_on_the_field_and_writes_nothing(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        ok = BASE_URL + "novo"
        cases = {
            "nome 1 caractere": ("a", ok, ""), "nome 26": ("n" * 26, ok, ""), "nome vazio": ("", ok, ""),
            "nome só espaços": ("   ", ok, ""), "nome duplicado": ("Fixo", ok, ""),
            "url ftp": ("Ok", "ftp://example.com/x", ""), "url javascript": ("Ok", "javascript:alert(1)", ""),
            "url sem esquema": ("Ok", "example.com/x", ""), "url só esquema": ("Ok", "http://", ""),
            "url vazia": ("Ok", "", ""), "url 251": ("Ok", BASE_URL + "a" * (251 - len(BASE_URL)), ""),
            "descrição 51": ("Ok", ok, "d" * 51), "descrição 2": ("Ok", ok, "ab"),
        }

        def check(item):
            label, (nome, url, desc) = item
            response = self.add(browser, nome, url, desc)
            assert response.code == 422, f"status {response.code}"
            assert 'aria-invalid="true"' in response.body.decode(), "campo inválido sem aria-invalid"

        Each.run(list(cases.items()), check)
        self.assert_untouched(before, writes)

    def test_adding_to_a_full_list_is_422(self):
        set_links(self.db, "1", 100, full_list())
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        assert self.add(self.logged_in(), "Extra", BASE_URL + "extra").code == 422
        self.assert_untouched(before, writes)

    def test_add_is_refused_without_a_request_channel(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "adicionar")
        doc = self.db.doc("1", 100)
        doc["player_controller"]["channel"] = None
        external_change(self.db, "1", 100, player_controller=doc["player_controller"])
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        stale = self.submit(browser, url, form, nome="Rock", url=BASE_URL + "r")
        assert stale.code in (409, 422), f"status {stale.code}"
        self.assert_untouched(before, writes)

    def test_second_bot_add_changes_only_that_bots_document(self):
        before1 = self.db.doc("1", 800)
        assert self.add(self.logged_in(), "Novo", BASE_URL + "n", gid=800, bot=2).code == 200
        assert "Novo" in self.stored("2", 800) and self.db.doc("1", 800) == before1

    def test_other_fields_in_the_post_are_ignored(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "adicionar")
        before = self.db.doc("1", 100)
        pairs = form.pairs(nome="Rock", url=BASE_URL + "r") + [
            ("player_controller.channel", "1"), ("djroles", "5001"), ("autoplay", "on"), ("ver", "9.9"),
            ("fav_links", "{}")]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("1", 100)
        for key in ("djroles", "autoplay", "ver", "extra_flag"):
            assert after[key] == before[key], key
        assert after["player_controller"]["channel"] == "7777" and "Fixo" in after["player_controller"]["fav_links"]


# ============================================================================ editar / remover

class LinksEditRemoveTest(LinksBase):
    def test_edit_updates_url_and_description_keeping_name_and_position(self):
        set_links(self.db, "1", 100, {"Primeiro": link("https://example.com/1", "a"), "Fixo": link(), "Ultimo": link()})
        browser = self.logged_in()
        response = self.act(browser, 100, "editar", alvo="Fixo", url="https://example.com/novo", descricao="nova")
        assert response.code == 200, f"status {response.code}"
        assert list(self.stored()) == ["Primeiro", "Fixo", "Ultimo"], "ordem e nomes preservados"
        assert self.stored()["Fixo"] == link("https://example.com/novo", "nova")
        assert self.stored()["Primeiro"] == link("https://example.com/1", "a")

    def test_edit_cannot_rename_and_unknown_names_are_422(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "editar", "Fixo")
        renamed = self.submit(browser, url, form, pairs=form.pairs(url=BASE_URL + "z") + [("novo_nome", "Outro")])
        assert renamed.code in (200, 422)
        assert list(self.stored()) == ["Fixo"], "renomear = remover + adicionar; o nome nunca muda por editar"
        self.db.writes.clear()
        form = acao_form(self.body_of(browser, 100), "editar", "Fixo")   # versão atual (409 vem antes de 422)
        ghost = self.submit(browser, url, form, nome="Inexistente", url=BASE_URL + "z")
        assert ghost.code == 422 and "Inexistente" not in self.stored() and not self.db.writes

    def test_edit_validates_like_add(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)

        def check(item):
            label, over = item
            response = self.act(browser, 100, "editar", alvo="Fixo", **over)
            assert response.code == 422, f"status {response.code}"

        Each.run([("url javascript", {"url": "javascript:alert(1)"}), ("url vazia", {"url": ""}),
                  ("url 251", {"url": BASE_URL + "a" * 240}), ("descrição 51", {"descricao": "d" * 51}),
                  ("descrição 2", {"descricao": "ab"})], check)
        self.assert_untouched(before, writes)

    def test_edit_still_works_when_the_list_is_full(self):
        set_links(self.db, "1", 100, full_list())   # descrições gravadas têm 2 caracteres ("d3"): fora de 3–50
        browser = self.logged_in()
        # só o que MUDOU é validado: reenviar a descrição já gravada (mesmo curta) é aceito
        response = self.act(browser, 100, "editar", alvo="L03", url=BASE_URL + "novo")
        assert response.code == 200 and self.stored()["L03"] == link(BASE_URL + "novo", "d3")
        assert self.act(browser, 100, "editar", alvo="L03", descricao="novo texto").code == 200
        assert self.stored()["L03"]["description"] == "novo texto" and len(self.stored()) == MAX_LINKS
        assert self.act(browser, 100, "editar", alvo="L03", descricao="x").code == 422, "descrição ALTERADA segue 3–50"

    def test_remove_deletes_only_that_entry(self):
        set_links(self.db, "1", 100, {"Fixo": link(), "Outro": link("https://example.com/o", "o")})
        before = self.db.doc("1", 100)
        response = self.act(self.logged_in(), 100, "remover", alvo="Fixo")
        assert response.code == 200
        expected = copy.deepcopy(before)
        del expected["player_controller"]["fav_links"]["Fixo"]
        assert self.db.doc("1", 100) == expected

    def test_removing_the_last_link_leaves_an_empty_dict(self):
        assert self.act(self.logged_in(), 100, "remover", alvo="Fixo").code == 200
        assert self.stored() == {}

    def test_remove_unknown_or_differently_cased_names_is_422(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        for nome in ("fixo", "Inexistente", ""):
            assert self.act(browser, 100, "remover", alvo="Fixo", nome=nome).code == 422, nome
        self.assert_untouched(before, writes)

    def test_remove_works_without_a_request_channel_like_the_command(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "remover", "Fixo")
        doc = self.db.doc("1", 100)
        doc["player_controller"]["channel"] = None
        external_change(self.db, "1", 100, player_controller=doc["player_controller"])
        form = acao_form(self.body_of(browser, 100), "remover", "Fixo")
        assert form is not None, "remover não depende do canal (o comando permite)"
        assert self.submit(browser, url, form).code == 200 and self.stored() == {}


# ============================================================================ importar / exportar

class LinksImportExportTest(LinksBase):
    def do_import(self, browser, payload, gid=100, bot=None, htmx=False):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return self.act(browser, gid, "importar", dados=raw, bot=bot, htmx=htmx)

    def test_valid_import_merges_and_overwrites_same_names(self):
        browser = self.logged_in()
        before = self.db.doc("1", 100)
        payload = {"Fixo": link("https://example.com/novo", "reescrito"), "Rock": link("https://example.com/r", "r")}
        response = self.do_import(browser, payload)
        assert response.code == 200, f"status {response.code}"
        expected = copy.deepcopy(before)
        expected["player_controller"]["fav_links"].update(payload)
        assert self.db.doc("1", 100) == expected and self.db.writes == [("1", 100)]

    def test_invalid_payloads_are_422_and_write_nothing(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        good = link("https://example.com/ok", "ok")
        cases = {
            "json inválido": "{nao é json", "lista em vez de objeto": [good], "valor não é objeto": {"A1": "https://x.com/a"},
            "sem descrição": {"A1": {"url": "https://example.com/a"}}, "sem url": {"A1": {"description": "x"}},
            "url não é texto": {"A1": {"url": 5, "description": ""}},
            "url inválida": {"A1": link("ftp://example.com/a")}, "url javascript": {"A1": link("javascript:alert(1)")},
            "url maior que USER_FAV_MAX_URL_LENGTH (90)": {"A1": link(BASE_URL + "a" * 80)},
            "descrição 51": {"A1": link(BASE_URL + "a", "d" * 51)}, "nome 26": {"n" * 26: good},
            "26 itens": {f"I{i:02d}": good for i in range(26)}, "vazio": {},
            "'> fav:' não escapa da validação": {"> fav: x": link("javascript:alert(1)")},
        }

        def check(item):
            label, payload = item
            response = self.do_import(browser, payload)
            assert response.code == 422, f"status {response.code}"
            assert 'aria-invalid="true"' in response.body.decode(), "campo dados sem aria-invalid"

        Each.run(list(cases.items()), check)
        self.assert_untouched(before, writes)

    def test_url_limit_is_read_from_the_bot_config_at_request_time(self):
        browser = self.logged_in()
        payload = {"A1": link(BASE_URL + "a" * 80)}  # 100 caracteres
        assert self.do_import(browser, payload).code == 422
        self.world.config["USER_FAV_MAX_URL_LENGTH"] = 120
        assert self.do_import(browser, payload).code == 200

    def test_space_rule_counts_overwritten_names_as_free(self):
        browser = self.logged_in()
        set_links(self.db, "1", 100, full_list(24))
        extra = {"N1": link(BASE_URL + "1"), "N2": link(BASE_URL + "2")}
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        assert self.do_import(browser, extra).code == 422, "24 + 2 novos > 25"
        self.assert_untouched(before, writes)
        overwrite = {"L00": link(BASE_URL + "novo", "x"), "N1": link(BASE_URL + "1")}
        assert self.do_import(browser, overwrite).code == 200, "L00 já existe: só 1 vaga nova (24 + 1 = 25)"
        assert len(self.stored()) == MAX_LINKS

    def test_import_is_refused_without_a_request_channel(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "importar")
        doc = self.db.doc("1", 100)
        doc["player_controller"]["channel"] = None
        external_change(self.db, "1", 100, player_controller=doc["player_controller"])
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        response = self.submit(browser, url, form, dados=json.dumps({"A1": link(BASE_URL + "a")}))
        assert response.code in (409, 422)
        self.assert_untouched(before, writes)

    def test_export_is_the_import_format_as_an_attachment(self):
        browser = self.logged_in()
        response = browser.get(f"/painel/servidores/100/links/exportar")
        assert response.code == 200, f"status {response.code}"
        assert json.loads(response.body) == self.stored()
        assert response.headers["Content-Type"].startswith("application/json")
        assert response.headers["Content-Disposition"].lower().startswith("attachment")
        assert response.headers.get("Cache-Control") == "no-store"
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert self.db.writes == [], "exportar não grava"

    def test_export_then_import_round_trips_without_changes(self):
        browser = self.logged_in()
        exported = browser.get("/painel/servidores/100/links/exportar").body.decode()
        before = self.db.doc("1", 100)
        assert self.do_import(browser, exported).code == 200
        assert self.db.doc("1", 100) == before

    def test_export_follows_the_chosen_bot_and_the_same_authorization_rules(self):
        browser = self.logged_in()
        assert json.loads(browser.get("/painel/servidores/800/links/exportar?bot=2").body) == self.stored("2", 800)
        assert json.loads(browser.get("/painel/servidores/800/links/exportar").body) == self.stored("1", 800)
        reference = browser.get("/painel/servidores/999999/links").code
        assert reference == 404
        for path in ("/painel/servidores/300/links/exportar", "/painel/servidores/600/links/exportar",
                     "/painel/servidores/500/links/exportar", "/painel/servidores/100/links/exportar?bot=2",
                     "/painel/servidores/100/links/exportar?bot=abc"):
            response = browser.get(path)
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), path

    def test_export_requires_login(self):
        response = self.browser().get("/painel/servidores/100/links/exportar")
        assert response.code == 302 and response.headers["Location"].startswith("/painel/login")

    def test_export_of_a_hostile_name_is_inert_json(self):
        set_links(self.db, "1", 100, {"</script><b>": link("https://example.com/a", "<i>")})
        response = self.logged_in().get("/painel/servidores/100/links/exportar")
        assert response.code == 200 and json.loads(response.body) == self.stored()
        assert response.headers["Content-Type"].startswith("application/json")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


# ============================================================================ transversal: acesso, versão, htmx, efeitos, log

class LinksProtocolTest(LinksBase):
    def test_anonymous_and_denied_guilds(self):
        assert self.browser().get(self.links_url(100)).code == 302
        browser = self.logged_in()
        assert browser.get(self.links_url(100)).code == 200, "a rota deve existir"
        reference = browser.get("/painel/servidores/999999/links").body.decode()
        for gid, bot in ((300, None), (600, None), (500, None), (100, 2), (100, "abc"), (800, 3)):
            response = browser.get(self.links_url(gid, bot))
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), (gid, bot)

    def test_post_without_xsrf_is_403_and_without_version_or_action_is_422(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "adicionar")
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        no_xsrf = [p for p in form.pairs(nome="Rock", url=BASE_URL + "r") if p[0] != "_xsrf"]
        assert self.submit(browser, url, form, pairs=no_xsrf).code == 403
        no_version = [p for p in form.pairs(nome="Rock", url=BASE_URL + "r") if p[0] != "versao"]
        assert self.submit(browser, url, form, pairs=no_version).code == 422
        for acao in ("", "hackear", "limpar"):
            assert self.submit(browser, url, form, acao=acao, nome="Rock", url=BASE_URL + "r").code == 422, acao
        no_action = [p for p in form.pairs(nome="Rock", url=BASE_URL + "r") if p[0] != "acao"]
        assert self.submit(browser, url, form, pairs=no_action).code == 422
        self.assert_untouched(before, writes)

    def test_stale_version_is_409_for_every_action_and_writes_nothing(self):
        browser = self.logged_in()
        url = self.links_url(100)
        body = self.body_of(browser, 100)
        forms = {"adicionar": (acao_form(body, "adicionar"), {"nome": "Rock", "url": BASE_URL + "r"}),
                 "editar": (acao_form(body, "editar", "Fixo"), {"url": BASE_URL + "e"}),
                 "remover": (acao_form(body, "remover", "Fixo"), {}),
                 "importar": (acao_form(body, "importar"), {"dados": json.dumps({"A1": link(BASE_URL + "i")})})}
        external_change(self.db, "1", 100, autoplay=False)  # não é da lista: não conflita
        set_links(self.db, "1", 100, {"Fixo": link(), "Mudou": link(BASE_URL + "m")})
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        for acao, (form, over) in forms.items():
            for htmx in (True, False):
                response = self.submit(browser, url, form, htmx=htmx, **over)
                assert response.code == 409, f"{acao} htmx={htmx}: {response.code}"
                assert CONFLICT_TEXT in html.unescape(response.body.decode())
        self.assert_untouched(before, writes)

    def test_htmx_returns_a_fragment_and_plain_post_the_whole_page(self):
        browser = self.logged_in()
        fragment = self.add(browser, "Rock", BASE_URL + "r", htmx=True)
        body = fragment.body.decode()
        assert fragment.code == 200 and "<html" not in body.lower() and SAVED_TEXT in html.unescape(body)
        assert "Rock" in body, "o fragmento traz a lista atualizada"
        whole = self.add(browser, "Pop", BASE_URL + "p")
        assert whole.code == 200 and "<html" in whole.body.decode().lower()
        bad = self.add(browser, "", BASE_URL + "p", htmx=True)
        assert bad.code == 422 and "<html" not in bad.body.decode().lower()

    def test_write_after_permission_revoked_is_404_inside_the_cache_window(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "remover", "Fixo")
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        self.world.g100.members[UID].guild_permissions.administrator = False
        self.world.g100.members[UID].guild_permissions.manage_guild = False
        response = self.submit(browser, url, form, gap=2)
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        self.assert_untouched(before, writes)

    def test_two_concurrent_adds_with_the_same_version_one_wins(self):
        import asyncio
        from urllib.parse import urlencode, urlsplit
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "adicionar")
        self.clock.advance(4)
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Cookie": "; ".join(f"{k}={v}" for k, v in browser.cookies.items()), **self.xsrf_header(browser)}
        bodies = [urlencode(form.pairs(nome=n, url=BASE_URL + n)) for n in ("Aa", "Bb")]

        async def both():
            return await asyncio.gather(*[
                self.http_client.fetch(self.get_url(url), method="POST", headers=headers, body=b,
                                       raise_error=False, follow_redirects=False) for b in bodies])

        codes = sorted(r.code for r in self.io_loop.run_sync(both))
        assert codes == [200, 409], codes
        assert len(self.stored()) == 2 and self.db.writes == [("1", 100)]

    def test_audit_names_the_category_and_field_but_never_values(self):
        browser = self.logged_in()
        self.caplog.clear()
        assert self.add(browser, "SegredoNome", "https://example.com/segredo-url", "segredo-desc").code == 200
        text = self.audit_text()
        assert str(UID) in text and "100" in text and "links" in text and "fav_links" in text, text
        logs = self.all_log_text()
        for value in ("SegredoNome", "segredo-url", "segredo-desc"):
            assert value not in logs, f"valor no log: {value}"


class LinksEffectsTest(LinksBase):
    """Efeito do comando ao mudar fav_links: process_idle_embed(bot, guild, guild_data) (interactions.py:644) —
    atualiza o embed ocioso do canal de pedidos (no-op se há player ativo). Guild 200 (bot 2) não tem player."""

    def recorder(self):
        from utils.music import interactions
        calls = []

        async def fake(bot, guild, guild_data):
            calls.append((bot, guild, copy.deepcopy(guild_data)))

        self.monkeypatch.setattr(interactions, "process_idle_embed", fake)
        return calls

    def run_action(self, action):
        calls = self.recorder()
        browser = self.logged_in()
        url = self.links_url(200)
        body = self.body_of(browser, 200)
        forms = {"adicionar": (acao_form(body, "adicionar"), {"nome": "Rock", "url": BASE_URL + "r"}),
                 "editar": (acao_form(body, "editar", "Fixo"), {"url": BASE_URL + "e"}),
                 "remover": (acao_form(body, "remover", "Fixo"), {}),
                 "importar": (acao_form(body, "importar"), {"dados": json.dumps({"A1": link(BASE_URL + "i")})})}
        form, over = forms[action]
        bot = self.world.bot2
        bot.calls["get_channel"] = 0
        response = self.submit(browser, url, form, **over)
        return response, calls, bot.calls["get_channel"]

    def test_every_successful_change_refreshes_the_idle_embed_after_the_write(self):
        def check(action):
            response, calls, channel_reads = self.run_action(action)
            assert response.code == 200, f"status {response.code}"
            assert calls, "nenhum efeito: utils.music.interactions.process_idle_embed não foi chamado"
            bot, guild, data = calls[-1]
            assert bot is self.world.bot2 and guild.id == 200
            assert data["player_controller"]["fav_links"] == self.stored("2", 200), "com os dados já gravados"

        for action in ("adicionar", "editar", "remover", "importar"):
            self.world.db.seed("2", 200, self.world.bot_doc())
            check(action)

    def test_rejected_changes_have_no_effect(self):
        calls = self.recorder()
        browser = self.logged_in()
        url = self.links_url(200)
        form = acao_form(self.body_of(browser, 200), "adicionar")
        self.world.bot2.calls["get_channel"] = 0
        assert self.submit(browser, url, form, nome="x", url="ftp://x").code == 422
        external_change(self.db, "2", 200, autoplay=False)
        set_links(self.db, "2", 200, {"Outro": link()})
        assert self.submit(browser, url, form, nome="Rock", url=BASE_URL + "r").code == 409
        assert not calls, "422/409 não disparam o efeito"

    def test_active_player_guild_still_saves(self):
        assert self.add(self.logged_in(), "Rock", BASE_URL + "r").code == 200  # guild 100 tem player ativo


class LinksImportNormalizationTest(LinksBase):
    """BAIXO-1/2 da E4b (aceitos pelo MAESTRO, corrigidos na E4c): a importação grava só o match do URL_REG e
    normaliza o nome como o "adicionar" (strip, 2–25, sem controle/quebra de linha)."""

    def do_import(self, browser, payload):
        return self.act(browser, 100, "importar", dados=json.dumps(payload))

    def test_import_stores_only_the_url_reg_match_not_the_trailing_text(self):
        browser = self.logged_in()
        payload = {"Lixo": link("https://example.com/ <img src=x onerror=alert(1)>", "d"),
                   "Dois": link("https://example.com/b?x=1 texto depois", "e")}
        assert self.do_import(browser, payload).code == 200
        assert self.stored()["Lixo"]["url"] == "https://example.com/"
        assert self.stored()["Dois"]["url"] == "https://example.com/b?x=1"

    def test_import_strips_names_like_add_does(self):
        assert self.do_import(self.logged_in(), {"  Rock  ": link(BASE_URL + "r")}).code == 200
        assert "Rock" in self.stored() and "  Rock  " not in self.stored()

    def test_import_rejects_names_that_add_would_reject(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        cases = {"só espaços": "   ", "um caractere": "x", "com quebra de linha": "a\nb", "com tabulação": "a\tb",
                 "controle": "ab\x00", "vazio": "", "26 após strip": " " + "n" * 26}

        def check(item):
            label, name = item
            response = self.do_import(browser, {name: link(BASE_URL + "r")})
            assert response.code == 422, f"{label}: status {response.code}"

        Each.run(list(cases.items()), check)
        assert self.db.doc("1", 100) == before and len(self.db.writes) == writes

    def test_names_that_collide_after_normalization_are_rejected(self):
        browser = self.logged_in()
        before = self.db.doc("1", 100)
        payload = {" Rock": link(BASE_URL + "a"), "Rock ": link(BASE_URL + "b")}
        assert self.do_import(browser, payload).code == 422
        assert self.db.doc("1", 100) == before

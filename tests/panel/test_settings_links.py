"""E4b — Links fixos do servidor (G-16): listar, adicionar, editar, remover, importar, exportar.

Regras extraídas do CÓDIGO (utils/music/interactions.py: FavModalAdd/FavModalImport/FavMenuView, modo
guild_fav_manager) onde ele diverge do briefing; ver .qa-e4b-interp.txt. Escopo: bot (`player_controller.fav_links`).
"""

import copy
import html
import json
import re

from tests.panel.helpers_settings import NOT_FOUND_TEXT, UID, acao_form
from tests.panel.test_settings_http import Each, HttpBase, external_change
from tests.support.modais import trocar_process_idle_embed

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
    def test_each_bot_has_its_own_list(self):
        browser = self.logged_in()
        first, second = self.body_of(browser, 800), self.body_of(browser, 800, bot=2)
        assert "example.com/um" in first and "example.com/dois" not in first
        assert "example.com/dois" in second and "do bot 2" in second and "example.com/um" not in second

    def test_urls_become_links_only_for_http_and_https_with_rel_noopener_noreferrer(self):
        set_links(
            self.db,
            "1",
            100,
            {
                "a": link("javascript:alert(1)"),
                "b": link("data:text/html,x"),
                "c": link("HTTP://UPPER.example/"),
                "d": link("https://ok.example/x"),
                "e": link("//evil.example/x"),
                "f": link("vbscript:x"),
            },
        )
        body = self.body_of(self.logged_in(), 100)
        hrefs = re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>', body)
        bad = [
            h
            for h in hrefs
            if re.match(r"\s*(javascript|data|vbscript):", html.unescape(h), re.I) or html.unescape(h).startswith("//")
        ]
        assert not bad, f"href perigoso: {bad}"
        for tag in re.findall(r'<a\b[^>]*href="https?://ok\.example/x"[^>]*>', body):
            assert "noopener" in tag and "noreferrer" in tag, tag


# ============================================================================ adicionar


class LinksAddTest(LinksBase):
    def test_description_is_optional(self):
        assert self.add(self.logged_in(), "Sem desc", "https://example.com/s").code == 200
        assert self.stored()["Sem desc"] == link("https://example.com/s", "")

    def test_adding_to_a_full_list_is_422(self):
        set_links(self.db, "1", 100, full_list())
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        assert self.add(self.logged_in(), "Extra", BASE_URL + "extra").code == 422
        self.assert_untouched(before, writes)

    def test_other_fields_in_the_post_are_ignored(self):
        browser = self.logged_in()
        url = self.links_url(100)
        form = acao_form(self.body_of(browser, 100), "adicionar")
        before = self.db.doc("1", 100)
        pairs = form.pairs(nome="Rock", url=BASE_URL + "r") + [
            ("player_controller.channel", "1"),
            ("djroles", "5001"),
            ("autoplay", "on"),
            ("ver", "9.9"),
            ("fav_links", "{}"),
        ]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("1", 100)
        for key in ("djroles", "autoplay", "ver", "extra_flag"):
            assert after[key] == before[key], key
        assert after["player_controller"]["channel"] == "7777" and "Fixo" in after["player_controller"]["fav_links"]


# ============================================================================ editar / remover


class LinksEditRemoveTest(LinksBase):
    def test_edit_still_works_when_the_list_is_full(self):
        set_links(self.db, "1", 100, full_list())  # descrições gravadas têm 2 caracteres ("d3"): fora de 3–100
        browser = self.logged_in()
        # só o que MUDOU é validado: reenviar a descrição já gravada (mesmo curta) é aceito
        response = self.act(browser, 100, "editar", alvo="L03", url=BASE_URL + "novo")
        assert response.code == 200 and self.stored()["L03"] == link(BASE_URL + "novo", "d3")
        assert self.act(browser, 100, "editar", alvo="L03", descricao="novo texto").code == 200
        assert self.stored()["L03"]["description"] == "novo texto" and len(self.stored()) == MAX_LINKS
        assert self.act(browser, 100, "editar", alvo="L03", descricao="x").code == 422, "descrição ALTERADA segue 3–100"

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

    def test_space_rule_counts_overwritten_names_as_free(self):
        browser = self.logged_in()
        set_links(self.db, "1", 100, full_list(24))
        extra = {"N1": link(BASE_URL + "1"), "N2": link(BASE_URL + "2")}
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        assert self.do_import(browser, extra).code == 422, "24 + 2 novos > 25"
        self.assert_untouched(before, writes)
        overwrite = {"L00": link(BASE_URL + "novo", "xxx"), "N1": link(BASE_URL + "1")}
        assert self.do_import(browser, overwrite).code == 200, "L00 já existe: só 1 vaga nova (24 + 1 = 25)"
        assert len(self.stored()) == MAX_LINKS

    def test_export_follows_the_chosen_bot_and_the_same_authorization_rules(self):
        browser = self.logged_in()
        assert json.loads(browser.get("/painel/servidores/800/links/exportar?bot=2").body) == self.stored("2", 800)
        assert json.loads(browser.get("/painel/servidores/800/links/exportar").body) == self.stored("1", 800)
        reference = browser.get("/painel/servidores/999999/links").code
        assert reference == 404
        for path in (
            "/painel/servidores/300/links/exportar",
            "/painel/servidores/600/links/exportar",
            "/painel/servidores/500/links/exportar",
            "/painel/servidores/100/links/exportar?bot=2",
            "/painel/servidores/100/links/exportar?bot=abc",
        ):
            response = browser.get(path)
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), path


# ============================================================================ transversal: acesso, versão, htmx, efeitos, log


class LinksProtocolTest(LinksBase):
    def test_anonymous_and_denied_guilds(self):
        assert self.browser().get(self.links_url(100)).code == 302
        browser = self.logged_in()
        assert browser.get(self.links_url(100)).code == 200, "a rota deve existir"
        browser.get("/painel/servidores/999999/links")
        for gid, bot in ((300, None), (600, None), (500, None), (100, 2), (100, "abc"), (800, 3)):
            response = browser.get(self.links_url(gid, bot))
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), (gid, bot)

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


class LinksEffectsTest(LinksBase):
    """Efeito do comando ao mudar fav_links: process_idle_embed(bot, guild, guild_data) (interactions.py:644) —
    atualiza o embed ocioso do canal de pedidos (no-op se há player ativo). Guild 200 (bot 2) não tem player."""

    def recorder(self):
        from empiremuse.utils.music import interactions

        calls = []

        async def fake(bot, guild, guild_data):
            calls.append((bot, guild, copy.deepcopy(guild_data)))

        trocar_process_idle_embed(self.monkeypatch, fake)
        return calls

    def run_action(self, action):
        calls = self.recorder()
        browser = self.logged_in()
        url = self.links_url(200)
        body = self.body_of(browser, 200)
        forms = {
            "adicionar": (acao_form(body, "adicionar"), {"nome": "Rock", "url": BASE_URL + "r"}),
            "editar": (acao_form(body, "editar", "Fixo"), {"url": BASE_URL + "e"}),
            "remover": (acao_form(body, "remover", "Fixo"), {}),
            "importar": (acao_form(body, "importar"), {"dados": json.dumps({"A1": link(BASE_URL + "i")})}),
        }
        form, over = forms[action]
        bot = self.world.bot2
        bot.calls["get_channel"] = 0
        response = self.submit(browser, url, form, **over)
        return response, calls, bot.calls["get_channel"]

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


class LinksImportNormalizationTest(LinksBase):
    """BAIXO-1/2 da E4b (aceitos pelo MAESTRO, corrigidos na E4c): a importação grava só o match do URL_REG e
    normaliza o nome como o "adicionar" (strip, 2–25, sem controle/quebra de linha)."""

    def do_import(self, browser, payload):
        return self.act(browser, 100, "importar", dados=json.dumps(payload))

    def test_import_rejects_names_that_add_would_reject(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        cases = {
            "só espaços": "   ",
            "um caractere": "x",
            "com quebra de linha": "a\nb",
            "com tabulação": "a\tb",
            "controle": "ab\x00",
            "vazio": "",
            "26 após strip": " " + "n" * 26,
        }

        def check(item):
            label, name = item
            response = self.do_import(browser, {name: link(BASE_URL + "r")})
            assert response.code == 422, f"{label}: status {response.code}"

        Each.run(list(cases.items()), check)
        assert self.db.doc("1", 100) == before and len(self.db.writes) == writes

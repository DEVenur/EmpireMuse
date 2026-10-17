"""E4c — categoria `canal` (G-06 setup / G-07 reset): acesso, página e VALIDAÇÕES (grupos 2 e 3 da PROPOSTA-E4c).

Contrato do formulário (interpretações em .qa-e4c-interp.txt): `POST /painel/servidores/<gid>/canal[?bot=]` com
`acao` ∈ configurar | reset | confirmar_reset; configurar: `modo` ∈ existente|criar, `canal`, `limpar_mensagens`,
`titulo_forum`, `tipo` ∈ texto|voz|palco, `categoria`. Validação falha = 422 SÍNCRONO (nenhuma tarefa, nenhum efeito
no Discord, nada no banco); sucesso = 202 + tarefa (ver test_channel_tasks.py).
"""

import html
import re
from urllib.parse import parse_qs, urlsplit

from tests.panel.helpers import EXPECTED_SECURITY_HEADERS, OAUTH_SECRET, COOKIE_SECRET
from tests.panel.helpers_channel import ChannelBase, GID
from tests.panel.helpers_settings import NOT_FOUND_TEXT, UID, acao_form, version_of
from tests.panel.test_settings_http import Each, HttpBase, normalize
from tests.helpers_request_channel import perms, FULL_TEXT

TASK_PATH = re.compile(r"/painel/servidores/\d+/canal/tarefas/")


class CanalBase(ChannelBase, HttpBase):
    def canal_url(self, bot=None, gid=GID):
        return f"/painel/servidores/{gid}/canal" + (f"?bot={bot}" if bot is not None else "")

    def body(self, browser, gid=GID, bot=None):
        response = browser.get(self.canal_url(bot, gid))
        assert response.code == 200, f"GET canal: {response.code}"
        return response.body.decode()

    def setup_form(self, browser):
        form = acao_form(self.body(browser), "configurar")
        assert form is not None, "a página deve oferecer o formulário acao=configurar"
        return form

    def configure(self, browser, htmx=False, **fields):
        """Envia o formulário de setup como o navegador, com os campos dados."""
        form = self.setup_form(browser)
        return self.submit(browser, self.canal_url(), form, htmx=htmx, **fields)

    def assert_nothing_happened(self, response=None, status=422):
        if response is not None:
            assert response.code == status, f"status {response.code}"
            assert not TASK_PATH.search(response.body.decode()), "validação não pode criar tarefa"
        assert list(self.world.j) == [], f"nenhum efeito esperado, houve: {self.world.j.names()}"


# ============================================================================ acesso


class CanalAccessTest(CanalBase):
    def test_anonymous_is_redirected_to_login_with_next(self):
        response = self.browser().get(self.canal_url())
        location = urlsplit(response.headers.get("Location", ""))
        assert response.code == 302 and location.path == "/painel/login"
        assert parse_qs(location.query).get("next") == [f"/painel/servidores/{GID}/canal"]

    def test_anonymous_post_and_poll_do_nothing(self):
        browser = self.browser()
        token = self.xsrf_header(browser)
        for method, path in (("POST", self.canal_url()), ("GET", f"/painel/servidores/{GID}/canal/tarefas/{'a' * 32}")):
            response = browser.request(
                path,
                method,
                headers={"Content-Type": "application/x-www-form-urlencoded", **token},
                **({"body": "acao=configurar"} if method == "POST" else {}),
            )
            assert response.code in (302, 401, 403), f"{method}: {response.code}"
        assert list(self.world.j) == []

    def test_authorized_page_exists_with_security_headers_and_no_cache(self):
        response = self.logged_in().get(self.canal_url())
        assert response.code == 200 and response.headers["Content-Type"].startswith("text/html")
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert response.headers.get("Cache-Control") == "no-store"
        body = response.body.decode()
        assert OAUTH_SECRET not in body and COOKIE_SECRET not in body

    def test_unknown_bot_or_foreign_guild_is_the_generic_404(self):
        browser = self.logged_in()
        assert browser.get(self.canal_url()).code == 200, "a rota deve existir"
        reference = normalize(browser.get("/painel/servidores/999999/canal").body.decode())
        assert NOT_FOUND_TEXT in reference

        def check(path):
            response = browser.get(path)
            assert response.code == 404 and normalize(response.body.decode()) == reference, response.code

        Each.run(
            [
                self.canal_url(1),
                self.canal_url("abc"),
                self.canal_url("7000;1"),
                "/painel/servidores/300/canal",
                "/painel/servidores/abc/canal",
            ],
            check,
        )
        post = self.post_raw(browser, self.canal_url(1), [("acao", "configurar"), ("versao", "0" * 16)])
        assert post.code == 404 and list(self.world.j) == []

    def test_bot_that_is_not_ready_is_not_found(self):
        browser = self.logged_in()
        assert browser.get(self.canal_url()).code == 200
        self.world.bot.ready = False
        self.clock.advance(31)
        assert browser.get(self.canal_url()).code == 404

    def test_post_without_xsrf_is_403_and_nothing_happens(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        pairs = [p for p in form.pairs(modo="existente", canal="22") if p[0] != "_xsrf"]
        assert self.submit(browser, self.canal_url(), form, pairs=pairs).code == 403
        self.assert_nothing_happened()

    def test_post_without_version_or_unknown_action_is_422(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        no_version = [p for p in form.pairs(modo="existente", canal="22") if p[0] != "versao"]
        self.assert_nothing_happened(self.submit(browser, self.canal_url(), form, pairs=no_version))
        for acao in ("", "apagar", "CONFIGURAR"):
            self.assert_nothing_happened(
                self.submit(browser, self.canal_url(), form, acao=acao, modo="existente", canal="22")
            )

    def test_body_over_16_kib_is_413_and_the_write_rate_limit_is_20_per_minute(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        big = form.pairs(modo="existente", canal="22") + [("pad", "x" * 20000)]
        assert self.submit(browser, self.canal_url(), form, pairs=big).code == 413
        codes = [
            self.submit(browser, self.canal_url(), form, gap=0, modo="existente", canal="abc").code for _ in range(20)
        ]
        assert 429 not in codes, "o 413 não conta; as 20 primeiras escritas do minuto passam"
        assert self.submit(browser, self.canal_url(), form, gap=0, modo="existente", canal="abc").code == 429
        assert list(self.world.j) == []

    def test_write_after_permission_revoked_is_404_inside_the_cache_window(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        member = self.world.guild.members[UID]
        member.guild_permissions.administrator = member.guild_permissions.manage_guild = False
        response = self.submit(browser, self.canal_url(), form, gap=2, modo="existente", canal="22")
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        assert list(self.world.j) == []

    def test_422_has_a_fragment_for_htmx_and_the_whole_page_otherwise(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        fragment = self.submit(browser, self.canal_url(), form, htmx=True, modo="existente", canal="abc")
        whole = self.submit(browser, self.canal_url(), form, modo="existente", canal="abc")
        assert fragment.code == whole.code == 422
        assert "<html" not in fragment.body.decode().lower() and "<html" in whole.body.decode().lower()
        assert 'aria-invalid="true"' in fragment.body.decode()


# ============================================================================ página


class CanalPageTest(CanalBase):
    def test_not_configured_page_offers_setup_and_no_reset(self):
        body = self.body(self.logged_in())
        assert "não configurado" in html.unescape(body).lower()
        assert acao_form(body, "configurar") and acao_form(body, "reset") is None

    def test_configured_page_shows_the_channel_name_escaped_and_the_reset_button(self):
        self.world.text.name = "<b>pedidos</b>"
        self.world.configured_text()
        body = self.body(self.logged_in())
        assert "<b>pedidos</b>" not in body and "&lt;b&gt;pedidos&lt;/b&gt;" in body
        assert acao_form(body, "reset") is not None

    def test_removed_channel_is_shown_as_such(self):
        self.world.configure("424242", "1")
        body = html.unescape(self.body(self.logged_in())).lower()
        assert "não configurado" in body or "removido" in body or "apagado" in body

    def test_existing_channel_choices_are_the_bots_text_voice_stage_and_forum_channels_of_this_guild(self):
        form = self.setup_form(self.logged_in())
        offered = set(form.choices("canal"))
        assert offered == {"11", "22", "23", "33", "44", "55"}, f"canal: {sorted(offered)} (sem categoria nem alheios)"

    def test_channel_names_in_the_choices_are_escaped(self):
        self.world.other.name = "<img src=x onerror=alert(1)>"
        body = self.body(self.logged_in())
        assert "<img src=x" not in body and "&lt;img" in body

    def test_creation_options_stage_only_with_community_and_categories_from_the_cache(self):
        form = self.setup_form(self.logged_in())
        assert set(form.choices("tipo")) == {"texto", "voz"}
        assert set(form.choices("categoria")) >= {"66"} and "" in form.choices("categoria")

    def test_form_carries_xsrf_version_and_the_documented_fields(self):
        form = self.setup_form(self.logged_in())
        assert form.method == "post" and form.value("_xsrf") and re.fullmatch(r"[0-9a-f]{16}", form.value("versao"))
        assert all(
            form.has(name) for name in ("modo", "canal", "limpar_mensagens", "titulo_forum", "tipo", "categoria")
        )

    def test_version_is_the_hash_of_channel_and_message_id(self):
        browser = self.logged_in()
        assert self.setup_form(browser).value("versao") == version_of({"channel": None, "message_id": None})
        self.world.configured_text()
        assert self.setup_form(browser).value("versao") == version_of({"channel": "22", "message_id": "555"})

    def test_navigation_links_to_canal_and_nothing_is_coming_soon(self):
        body = self.logged_in().get(f"/painel/servidores/{GID}").body.decode()
        assert f'href="/painel/servidores/{GID}/canal"' in body
        assert "em breve" not in body.lower() and 'aria-disabled="true"' not in body

    def test_pages_of_the_other_categories_link_to_canal_too(self):
        body = self.logged_in().get(f"/painel/servidores/{GID}/player").body.decode()
        assert f"/painel/servidores/{GID}/canal" in body


# ============================================================================ validações (422 síncrono, sem efeitos)


class CanalSetupValidationTest(CanalBase):
    def check_422(self, **fields):
        browser = self.logged_in()
        response = self.configure(browser, **fields)
        self.assert_nothing_happened(response)
        body = response.body.decode()
        assert 'aria-invalid="true"' in body, "campo inválido sem aria-invalid"
        for leak in ("Traceback", "GenericError", "repr("):
            assert leak not in body
        return body

    def test_channel_id_must_be_digits_known_and_from_this_guild(self):
        def check(value):
            self.world.j.clear()
            self.check_422(modo="existente", canal=value)

        Each.run(["", "abc", "22 ", "-22", "22.0", "٢٢", "9" * 21, "999999", "99", "<script>"], check)

    def test_accepted_channel_types_only(self):
        for value in ("66",):  # categoria
            self.check_422(modo="existente", canal=value)
        post = self.world.forum.add_post(900, "post")
        self.world.bot.channels[900] = post  # thread/post de fórum não é um alvo válido
        self.check_422(modo="existente", canal="900")

    def test_discord_updates_and_rules_channels_are_refused(self):
        self.world.guild.public_updates_channel = self.world.text
        body = self.check_422(modo="existente", canal="22")
        assert "atualizações" in html.unescape(body)
        self.world.guild.public_updates_channel, self.world.guild.rules_channel = None, self.world.text
        self.world.j.clear()
        body = self.check_422(modo="existente", canal="22")
        assert "regras" in html.unescape(body)

    def test_each_missing_bot_permission_on_the_channel_is_a_separate_422_translated_to_pt_br(self):
        cases = {"send_messages": "Enviar mensagem", "embed_links": "Inserir links", "view_channel": "Ler mensagens"}

        def check(item):
            missing, label = item
            self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != missing})
            self.world.j.clear()
            body = html.unescape(self.check_422(modo="existente", canal="22"))
            assert any(x in body for x in (label, "Ver canal")), f"{missing}: {body[:200]}"

        Each.run(list(cases.items()), check)

    def test_forum_permissions_are_checked_before_any_task(self):
        for missing in ("send_messages", "send_messages_in_threads", "embed_links", "view_channel"):
            self.world.forum._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != missing})
            self.world.j.clear()
            self.check_422(modo="existente", canal="55", titulo_forum="Pedidos do bot")

    def test_non_admin_bot_needs_manage_permissions_on_an_existing_channel(self):
        self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != "manage_permissions"})
        body = html.unescape(self.check_422(modo="existente", canal="22")).lower()
        assert "gerenciar permissões" in body or "administrador" in body

    def test_missing_manage_permissions_is_explained_in_panel_terms_not_with_the_commands_text(self):
        """Fase 2 / Trilha C: o texto do /setup ("use o comando sem selecionar um canal de destino") não serve ao painel."""
        from utils import branding

        self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != "manage_permissions"})
        body = " ".join(html.unescape(self.check_422(modo="existente", canal="22")).split())
        assert (
            f"O {branding.BOT_NAME} precisa da permissão Gerenciar permissões neste canal (ou de Administrador). "
            "Conceda a permissão ao cargo do bot ou escolha Criar um canal novo."
        ) in body
        lowered = body.lower()
        for forbidden in ("comando", "sem selecionar um canal de destino", "genericerror"):
            assert forbidden not in lowered, f"texto do comando vazou para o painel: {forbidden!r}"

    def test_the_manage_permissions_message_is_the_same_in_fragment_and_whole_page(self):
        self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != "manage_permissions"})
        browser = self.logged_in()
        for htmx in (False, True):
            response = self.configure(browser, htmx=htmx, modo="existente", canal="22")
            text = " ".join(html.unescape(response.body.decode()).split())
            assert response.code == 422 and "Gerenciar permissões neste canal" in text, htmx
            assert "comando" not in text.lower(), htmx

    def test_clearing_messages_needs_manage_messages_and_read_message_history(self):
        for missing in ("manage_messages", "read_message_history"):
            self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != missing})
            self.world.j.clear()
            self.check_422(modo="existente", canal="22", limpar_mensagens="on")
        self.world.text._perms = perms(**{k: v for k, v in FULL_TEXT.items() if k != "manage_messages"})
        self.world.j.clear()
        browser = self.logged_in()
        ok = self.configure(browser, modo="existente", canal="22", limpar_mensagens=None)
        assert ok.code == 202, "sem limpar mensagens, manage_messages não é exigido"

    def test_forum_title_is_4_to_30_characters(self):
        def check(item):
            title, status = item
            self.world.j.clear()
            response = self.configure(self.logged_in(), modo="existente", canal="55", titulo_forum=title)
            assert response.code == status, f"{len(title)} caracteres: {response.code}"
            if status == 422:
                self.assert_nothing_happened(response)
            self.world.forum.thread_list.clear()

        Each.run([("abc", 422), ("abcd", 202), ("a" * 30, 202), ("a" * 31, 422), ("", 422), ("   ", 422)], check)

    def test_forum_title_is_ignored_for_other_channel_types(self):
        assert self.configure(self.logged_in(), modo="existente", canal="22", titulo_forum="x").code == 202

    def test_mode_and_type_come_from_closed_lists(self):
        for fields in (
            {"modo": "outro"},
            {"modo": ""},
            {"modo": "criar", "tipo": "forum"},
            {"modo": "criar", "tipo": ""},
        ):
            self.world.j.clear()
            self.check_422(**fields)

    def test_stage_needs_community(self):
        self.check_422(modo="criar", tipo="palco")

    def test_category_must_be_a_category_of_this_guild(self):
        for value in ("999", "22", "abc", "66 ", "-66"):  # inexistente, canal comum, lixo
            self.world.j.clear()
            self.check_422(modo="criar", tipo="texto", categoria=value)

    def test_messages_are_pt_br_text_without_exception_reprs(self):
        body = html.unescape(self.check_422(modo="existente", canal="abc"))
        assert re.search(r"[áéíóúãõç]", body) or "canal" in body.lower()
        assert "Error(" not in body and "Exception" not in body

    def test_stale_version_is_409_and_nothing_happens(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        self.world.configured_text()
        response = self.submit(browser, self.canal_url(), form, modo="existente", canal="23")
        assert response.code == 409
        assert "alteradas em outro lugar" in html.unescape(response.body.decode())
        assert list(self.world.j) == []


class CanalCommunityTest(CanalBase):
    world_kwargs = {"features": ("COMMUNITY",)}

    def test_stage_is_offered_and_accepted_with_community(self):
        browser = self.logged_in()
        assert "palco" in self.setup_form(browser).choices("tipo")
        assert self.configure(browser, modo="criar", tipo="palco").code == 202


class CanalWithoutManageChannelsTest(CanalBase):
    world_kwargs = {"manage_channels": False}

    def test_creating_a_channel_is_refused_up_front(self):
        browser = self.logged_in()
        response = self.configure(browser, modo="criar", tipo="texto")
        self.assert_nothing_happened(response)
        assert "gerenciar canais" in html.unescape(response.body.decode()).lower()

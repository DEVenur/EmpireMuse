"""E4b — "Ouvir junto" (G-15) na categoria Geral: listar e remover convites (global, `listen_along_invites`).

Código de referência: modules/music_settings.py (listenalong / listen_along_modal): permissão `manage_channels`,
máx. 5 convites, efeito nos players do canal (`listen_along_invite`, `process_rpc()`). Adicionar fica fora da v1.
"""
import copy
import html
import re

from tests.panel.helpers_settings import CONFLICT_TEXT, NOT_FOUND_TEXT, SAVED_TEXT, UID, acao_form, parse_forms
from tests.panel.test_settings_http import Each, HttpBase, external_change

HEX16 = re.compile(r"^[0-9a-f]{16}$")
REMOVE = "remover_ouvir_junto"


class ListenAlongBase(HttpBase):
    def geral(self, browser, gid=100):
        response = browser.get(self.url(gid, "geral"))
        assert response.code == 200, f"GET geral: {response.code}"
        return response.body.decode()

    def remove(self, browser, canal, gid=100, htmx=False, **overrides):
        body = self.geral(browser, gid)
        form = next((f for f in parse_forms(body) if f.value("acao") == REMOVE and f.value("canal") == canal), None)
        assert form is not None, f"sem formulário de remover para o canal {canal}"
        return self.submit(browser, self.url(gid, "geral"), form, htmx=htmx, **overrides)

    def invites(self, gid=100):
        return self.db.doc("global", gid)["listen_along_invites"]


class ListenAlongReadTest(ListenAlongBase):
    def test_lists_channel_name_escaped_and_invite_as_text(self):
        body = self.geral(self.logged_in())
        assert "https://discord.gg/abc" in body
        assert "<i>DJ</i>" not in body and "&lt;i&gt;DJ&lt;/i&gt;" in body, "nome do canal do cache, escapado"

    def test_removed_channel_is_labelled_and_still_removable(self):
        external_change(self.db, "global", 100, listen_along_invites={"999": "https://discord.gg/zzz"})
        browser = self.logged_in()
        body = self.geral(browser)
        assert "canal removido" in html.unescape(body).lower()
        assert self.remove(browser, "999").code == 200 and self.invites() == {}

    def test_each_row_has_a_remove_form_with_xsrf_and_version(self):
        body = self.geral(self.logged_in(), 800)
        forms = [f for f in parse_forms(body) if f.value("acao") == REMOVE]
        assert sorted(f.value("canal") for f in forms) == ["123", "456"]
        for form in forms:
            assert form.method == "post" and form.value("_xsrf") and HEX16.match(form.value("versao") or "")

    def test_invite_links_are_inert_text_or_safe_links(self):
        external_change(self.db, "global", 100, listen_along_invites={"123": "javascript:alert(1)"})
        body = self.geral(self.logged_in())
        assert [f for f in parse_forms(body) if f.value("acao") == REMOVE], "a linha do convite deve ser listada"
        hrefs = [html.unescape(h) for h in re.findall(r'<a\b[^>]*href="([^"]*)"', body)]
        assert not [h for h in hrefs if h.lower().lstrip().startswith(("javascript:", "data:", "vbscript:"))]

    def test_user_without_manage_channels_sees_the_list_but_no_remove_form(self):
        body = self.geral(self.logged_in(), 200)  # guild 200: só MANAGE_GUILD
        assert "https://discord.gg/ccc" in body
        assert not [f for f in parse_forms(body) if f.value("acao") == REMOVE]

    def test_over_limit_legacy_data_stays_listed_and_removable(self):
        invites = {str(1000 + i): f"https://discord.gg/i{i}" for i in range(7)}
        external_change(self.db, "global", 100, listen_along_invites=invites)
        body = self.geral(self.logged_in())
        shown = [f for f in parse_forms(body) if f.value("acao") == REMOVE]
        # o comando só bloqueia NOVOS acima de 5; dados já gravados continuam listados e removíveis
        assert len(shown) == 7, "dados já gravados acima do limite têm de continuar removíveis"


class ListenAlongRemoveTest(ListenAlongBase):
    def test_remove_deletes_only_that_channel_and_touches_only_the_global_document(self):
        browser = self.logged_in()
        before = self.db.doc("global", 800)
        bots_before = (self.db.doc("1", 800), self.db.doc("2", 800))
        response = self.remove(browser, "123", gid=800)
        assert response.code == 200 and SAVED_TEXT in html.unescape(response.body.decode())
        expected = copy.deepcopy(before)
        del expected["listen_along_invites"]["123"]
        assert self.db.doc("global", 800) == expected, "prefix, skins, custom_skins*, ver etc. intactos"
        assert (self.db.doc("1", 800), self.db.doc("2", 800)) == bots_before
        assert self.db.writes == [("global", 800)]

    def test_players_in_that_voice_channel_clear_the_invite_and_refresh_rpc(self):
        self.world.p800b.listen_along_invite = "https://discord.gg/aaa"
        self.world.p800a.listen_along_invite = "https://discord.gg/bbb"
        self.events.clear()
        assert self.remove(self.logged_in(), "123", gid=800).code == 200
        assert self.world.p800b.listen_along_invite == "", "bot 2 está no canal 123"
        assert self.world.p800b.called("process_rpc") and self.world.p800b.called("process_save_queue")
        assert self.world.p800a.listen_along_invite == "https://discord.gg/bbb", "bot 1 está no canal 456"
        assert self.world.p800a.calls == []
        order = [(e[0], e[1]) if e[0] != "db" else ("db", "update") for e in self.events]
        assert order.index(("db", "update")) < order.index(("p800/b2", "process_rpc")), order

    def test_player_in_another_guild_is_untouched(self):
        self.world.p100.listen_along_invite = "https://discord.gg/abc"
        assert self.remove(self.logged_in(), "123", gid=800).code == 200
        assert self.world.p100.listen_along_invite == "https://discord.gg/abc" and self.world.p100.calls == []

    def test_unknown_or_malformed_channel_ids_are_422(self):
        browser = self.logged_in()
        body = self.geral(browser)
        form = next(f for f in parse_forms(body) if f.value("acao") == REMOVE)
        before, writes = self.db.doc("global", 100), len(self.db.writes)

        def check(canal):
            response = self.submit(browser, self.url(100, "geral"), form, canal=canal)
            assert response.code == 422, f"status {response.code}"

        Each.run(["456", "999999", "abc", "", "-123", "123.0", "١٢٣", "123 ", "9" * 40], check)
        assert self.db.doc("global", 100) == before and len(self.db.writes) == writes

    def test_adding_is_not_part_of_the_v1(self):
        browser = self.logged_in()
        form = next(f for f in parse_forms(self.geral(browser)) if f.value("acao") == REMOVE)
        before, writes = self.db.doc("global", 100), len(self.db.writes)
        response = self.submit(browser, self.url(100, "geral"), form, acao="adicionar_ouvir_junto",
                               canal="123", convite="https://discord.gg/novo")
        assert response.code == 422
        assert self.db.doc("global", 100) == before and len(self.db.writes) == writes

    def test_htmx_fragment_and_whole_page_shapes(self):
        browser = self.logged_in()
        fragment = self.remove(browser, "123", gid=800, htmx=True)
        body = fragment.body.decode()
        assert fragment.code == 200 and "<html" not in body.lower() and SAVED_TEXT in html.unescape(body)
        assert "456" in body and 'value="123"' not in body, "o fragmento já reflete a remoção"
        whole = self.remove(browser, "456", gid=800)
        assert whole.code == 200 and "<html" in whole.body.decode().lower()


class ListenAlongPermissionTest(ListenAlongBase):
    def test_manage_channels_is_required_at_write_time_not_only_at_render_time(self):
        browser = self.logged_in()
        body = self.geral(browser)
        form = next(f for f in parse_forms(body) if f.value("acao") == REMOVE)
        member = self.world.g100.members[UID]
        member.guild_permissions.manage_channels = False
        member.guild_permissions.administrator = False
        member.guild_permissions.manage_guild = True    # ainda gerencia o servidor, mas não os canais
        before, writes = self.db.doc("global", 100), len(self.db.writes)
        response = self.submit(browser, self.url(100, "geral"), form, gap=2)
        assert response.code == 403, f"sem manage_channels deveria ser 403, veio {response.code}"
        assert NOT_FOUND_TEXT not in response.body.decode(), "o usuário ainda gerencia o servidor: não é 404"
        assert self.db.doc("global", 100) == before and len(self.db.writes) == writes
        assert self.world.p100.calls == []

    def test_losing_every_permission_is_the_generic_404(self):
        browser = self.logged_in()
        form = next(f for f in parse_forms(self.geral(browser)) if f.value("acao") == REMOVE)
        member = self.world.g100.members[UID]
        member.guild_permissions.manage_channels = member.guild_permissions.administrator = False
        response = self.submit(browser, self.url(100, "geral"), form, gap=2)
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        assert len(self.db.writes) == 0

    def test_server_owner_without_flags_is_allowed(self):
        self.world.g100.owner_id = UID
        member = self.world.g100.members[UID]
        member.guild_permissions.administrator = member.guild_permissions.manage_guild = False
        member.guild_permissions.manage_channels = True  # o dono tem todas as permissões
        assert self.remove(self.logged_in(), "123").code == 200


class ListenAlongProtocolTest(ListenAlongBase):
    def test_xsrf_version_and_stale_conflict(self):
        browser = self.logged_in()
        form = next(f for f in parse_forms(self.geral(browser, 800)) if f.value("acao") == REMOVE)
        url = self.url(800, "geral")
        before, writes = self.db.doc("global", 800), len(self.db.writes)
        assert self.submit(browser, url, form, pairs=[p for p in form.pairs() if p[0] != "_xsrf"]).code == 403
        assert self.submit(browser, url, form, pairs=[p for p in form.pairs() if p[0] != "versao"]).code == 422
        external_change(self.db, "global", 800, listen_along_invites={"123": "https://discord.gg/novo"})
        for htmx in (True, False):
            response = self.submit(browser, url, form, htmx=htmx)
            assert response.code == 409 and CONFLICT_TEXT in html.unescape(response.body.decode())
        assert self.db.doc("global", 800)["listen_along_invites"] == {"123": "https://discord.gg/novo"}
        assert len(self.db.writes) == writes

    def test_other_geral_forms_do_not_change_the_invites_version(self):
        browser = self.logged_in()
        def version():
            form = next(f for f in parse_forms(self.geral(browser)) if f.value("acao") == REMOVE)
            return form.value("versao")
        first = version()
        external_change(self.db, "global", 100, prefix="?", voice_channel_status="{track.title}")
        assert version() == first
        external_change(self.db, "global", 100, listen_along_invites={"123": "https://discord.gg/outro"})
        assert version() != first

    def test_denied_guilds_and_foreign_bots_do_not_leak(self):
        browser = self.logged_in()
        for gid in (300, 600, 500, 999999):
            response = browser.post(self.url(gid, "geral"), body="acao=remover_ouvir_junto&canal=123&versao=" + "0" * 16,
                                    headers={"Content-Type": "application/x-www-form-urlencoded",
                                             **self.xsrf_header(browser)})
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), gid
        assert self.db.writes == []

    def test_audit_has_category_and_field_name_but_no_invite_url(self):
        browser = self.logged_in()
        self.caplog.clear()
        assert self.remove(browser, "123").code == 200
        text = self.audit_text()
        assert str(UID) in text and "100" in text and "geral" in text and "listen_along_invites" in text, text
        assert "discord.gg" not in self.all_log_text() and "abc" not in text

    def test_removal_failure_in_a_player_does_not_undo_or_break_the_response(self):
        async def boom():
            raise RuntimeError("falha simulada")

        self.world.p100.process_rpc = boom
        response = self.remove(self.logged_in(), "123")
        assert response.code == 200 and self.invites() == {}
        assert "falha simulada" not in response.body.decode() + self.all_log_text()

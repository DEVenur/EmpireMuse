"""E4b — "Ouvir junto" (G-15) na categoria Geral: listar e remover convites (global, `listen_along_invites`).

Código de referência: modules/music_settings.py (listenalong / listen_along_modal): permissão `manage_channels`,
máx. 5 convites, efeito nos players do canal (`listen_along_invite`, `process_rpc()`). Adicionar fica fora da v1.
"""

import copy
import html
import re

from tests.panel.helpers_settings import SAVED_TEXT, UID, parse_forms
from tests.panel.test_settings_http import HttpBase

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
    def test_each_row_has_a_remove_form_with_xsrf_and_version(self):
        body = self.geral(self.logged_in(), 800)
        forms = [f for f in parse_forms(body) if f.value("acao") == REMOVE]
        assert sorted(f.value("canal") for f in forms) == ["123", "456"]
        for form in forms:
            assert form.method == "post" and form.value("_xsrf") and HEX16.match(form.value("versao") or "")


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

    def test_adding_is_not_part_of_the_v1(self):
        browser = self.logged_in()
        form = next(f for f in parse_forms(self.geral(browser)) if f.value("acao") == REMOVE)
        before, writes = self.db.doc("global", 100), len(self.db.writes)
        response = self.submit(
            browser,
            self.url(100, "geral"),
            form,
            acao="adicionar_ouvir_junto",
            canal="123",
            convite="https://discord.gg/novo",
        )
        assert response.code == 422
        assert self.db.doc("global", 100) == before and len(self.db.writes) == writes


class ListenAlongPermissionTest(ListenAlongBase):
    def test_server_owner_without_flags_is_allowed(self):
        self.world.g100.owner_id = UID
        member = self.world.g100.members[UID]
        member.guild_permissions.administrator = member.guild_permissions.manage_guild = False
        member.guild_permissions.manage_channels = True  # o dono tem todas as permissões
        assert self.remove(self.logged_in(), "123").code == 200


class ListenAlongProtocolTest(ListenAlongBase):
    def test_audit_has_category_and_field_name_but_no_invite_url(self):
        browser = self.logged_in()
        self.caplog.clear()
        assert self.remove(browser, "123").code == 200
        text = self.audit_text()
        assert str(UID) in text and "100" in text and "geral" in text and "listen_along_invites" in text, text
        assert "discord.gg" not in self.all_log_text() and "abc" not in text

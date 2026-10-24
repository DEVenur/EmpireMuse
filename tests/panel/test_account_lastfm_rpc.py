"""E5 — Last.fm (U-04) e token do app de RPC (U-05): os dois itens com SEGREDO.

Last.fm: `lastfm.sessionkey` é segredo (nunca na página, nos logs, na auditoria, nos cabeçalhos); o painel só liga/desliga
`lastfm.scrobble` e só com conta vinculada. Token RPC: gerado no servidor com `secrets` (50 caracteres [A-Za-z0-9], como o
comando), mostrado UMA vez na resposta do POST e nunca mais.
"""

import html
import re

from tests.panel.helpers_account import RPC_TOKEN_OLD, SESSIONKEY, FakeRpcPlayer, OTHER_UID
from tests.panel.helpers_settings import CONFLICT_TEXT, UID, acao_form
from tests.panel.test_account_page import URL, AccountCase
import pytest

pytestmark = pytest.mark.critical

TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{50}(?![A-Za-z0-9])")


class LastFmTest(AccountCase):
    def test_a_username_without_a_session_key_is_not_a_linked_account(self):
        self.world.set_doc(lastfm={"username": "fantasma", "sessionkey": "", "scrobble": True})
        assert acao_form(self.body(self.logged_in()), "lastfm_scrobble") is None

    def test_toggle_changes_only_the_scrobble_flag(self):
        self.world.link_lastfm(scrobble=True)
        browser = self.logged_in()
        before = self.world.doc()
        assert self.act(browser, "lastfm_scrobble", scrobble=None).code == 200
        expected = {**before, "lastfm": {**before["lastfm"], "scrobble": False}}
        assert self.world.doc() == expected, "sessionkey e username intactos; demais campos também"
        assert self.act(browser, "lastfm_scrobble", scrobble="on").code == 200
        assert self.world.doc()["lastfm"]["scrobble"] is True

    def test_the_session_key_never_reaches_logs_audit_or_the_version(self):
        self.world.link_lastfm()
        browser = self.logged_in()
        self.caplog.clear()
        form = self.form(browser, "lastfm_scrobble")
        self.submit(browser, URL, form, scrobble=None)
        self.submit(browser, URL, form, scrobble=None)  # 409
        logs = self.all_log_text()
        assert SESSIONKEY not in logs and SESSIONKEY[:10] not in logs
        audit = self.audit_text()
        assert str(UID) in audit and "lastfm_scrobble" in audit and "scrobble" in audit
        before = self.form(browser, "lastfm_scrobble").value("versao")
        self.world.set_doc(lastfm={**self.world.doc()["lastfm"], "sessionkey": "OUTRA-CHAVE-SECRETA"})
        assert self.form(browser, "lastfm_scrobble").value("versao") == before, "a versão não depende do segredo"


class RpcTokenTest(AccountCase):
    def generate(self, browser, **kw):
        return self.act(browser, "rpc_token_gerar", **kw)

    def test_available_when_the_command_would_be_available(self):
        body = self.body(self.logged_in())
        assert acao_form(body, "rpc_token_gerar") is not None
        assert "Nenhum token" in html.unescape(body)

    def test_the_bot_owner_may_use_it_even_when_the_command_is_off_for_everyone(self):
        self.world.config["ENABLE_RPC_COMMAND"] = False
        self.world.owner_ids.add(UID)
        browser = self.logged_in()
        assert self.generate(browser).code == 200 and TOKEN.fullmatch(self.world.doc()["token"])

    def test_a_stale_generation_conflicts_and_its_response_does_not_leak_the_token(self):
        browser = self.logged_in()
        stale = self.form(browser, "rpc_token_gerar")
        self.generate(browser)
        token = self.world.doc()["token"]
        response = self.submit(browser, URL, stale)
        assert response.code == 409 and token not in response.body.decode()
        assert CONFLICT_TEXT in html.unescape(response.body.decode())

    def test_only_the_token_field_changes(self):
        before = self.world.doc()
        self.generate(self.logged_in())
        after = self.world.doc()
        assert {k for k in after if after[k] != before.get(k)} == {"token"}

    def test_replacing_a_token_first_closes_the_users_active_presence_then_writes(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        self.world.bot.music.players[555] = FakeRpcPlayer(self.world.journal, "na-voz", [UID])
        self.world.bot.music.players[666] = FakeRpcPlayer(self.world.journal, "sem-o-usuario", [OTHER_UID])
        assert self.generate(self.logged_in()).code == 200
        rpc = [e for e in self.world.journal if e[0] == "rpc"]
        assert len(rpc) == 1 and rpc[0][1] == "na-voz" and rpc[0][2] == [UID] and rpc[0][3]["op"] == "close"
        order = [e[0] for e in self.world.journal if e[0] in ("rpc", "db")]
        assert order == ["rpc", "db"], "como o comando: fecha a presença com o token antigo e só então grava"

    def test_one_failing_player_does_not_stop_the_presence_of_the_others_from_closing(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        broken = FakeRpcPlayer(self.world.journal, "quebrado", [UID])

        async def boom(*args, **kwargs):
            raise RuntimeError("falha-rpc")

        broken._send_rpc_data = boom
        self.world.bot.music.players[555] = broken
        self.world.bot.music.players[666] = FakeRpcPlayer(self.world.journal, "saudavel", [UID])
        assert self.generate(self.logged_in()).code == 200
        assert [e[1] for e in self.world.journal if e[0] == "rpc"] == ["saudavel"]

    def test_a_failure_while_looking_for_presences_does_not_prevent_the_new_token_or_leak(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)

        class BrokenMusic:
            @property
            def players(self):
                raise RuntimeError("players-secretos")

        self.world.bot.music = BrokenMusic()
        response = self.generate(self.logged_in())
        assert response.code == 200 and self.world.doc()["token"] != RPC_TOKEN_OLD
        assert "players-secretos" not in response.body.decode() + self.all_log_text()

    def test_rejected_attempts_do_not_close_presence_or_write(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        self.world.bot.music.players[555] = FakeRpcPlayer(self.world.journal, "na-voz", [UID])
        browser = self.logged_in()
        form = self.form(browser, "rpc_token_gerar")
        self.world.config["ENABLE_RPC_COMMAND"] = False
        assert self.submit(browser, URL, form).code == 403
        assert [e for e in self.world.journal if e[0] == "rpc"] == [] and self.world.doc()["token"] == RPC_TOKEN_OLD
        no_xsrf = [p for p in form.pairs() if p[0] != "_xsrf"]
        assert self.submit(browser, URL, form, pairs=no_xsrf).code == 403

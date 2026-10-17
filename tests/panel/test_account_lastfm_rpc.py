"""E5 — Last.fm (U-04) e token do app de RPC (U-05): os dois itens com SEGREDO.

Last.fm: `lastfm.sessionkey` é segredo (nunca na página, nos logs, na auditoria, nos cabeçalhos); o painel só liga/desliga
`lastfm.scrobble` e só com conta vinculada. Token RPC: gerado no servidor com `secrets` (50 caracteres [A-Za-z0-9], como o
comando), mostrado UMA vez na resposta do POST e nunca mais.
"""

import html
import random
import re

from tests.panel.helpers import COOKIE_SECRET, EXPECTED_SECURITY_HEADERS, OAUTH_SECRET
from tests.panel.helpers_account import RPC_TOKEN_OLD, SESSIONKEY, FakeRpcPlayer, OTHER_UID
from tests.panel.helpers_settings import CONFLICT_TEXT, UID, acao_form, parse_forms
from tests.panel.test_account_page import URL, AccountCase
from tests.panel.test_settings_http import Each

TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{50}(?![A-Za-z0-9])")


class LastFmTest(AccountCase):
    def test_without_a_linked_account_there_is_no_toggle_and_posting_is_422(self):
        browser = self.logged_in()
        body = self.body(browser)
        assert acao_form(body, "lastfm_scrobble") is None
        assert "vincul" in html.unescape(body).lower(), "explica que a vinculação é feita no Discord"
        form = self.form(browser, "prefixo")  # só para ter _xsrf/versao válidos
        before = self.world.doc()
        response = self.submit(browser, URL, form, acao="lastfm_scrobble", scrobble="on")
        assert response.code == 422 and self.world.doc() == before and self.db.writes == []

    def test_a_username_without_a_session_key_is_not_a_linked_account(self):
        self.world.set_doc(lastfm={"username": "fantasma", "sessionkey": "", "scrobble": True})
        assert acao_form(self.body(self.logged_in()), "lastfm_scrobble") is None

    def test_linked_account_shows_the_name_escaped_and_the_current_state(self):
        self.world.link_lastfm(username="<b>lfm</b>", scrobble=True)
        body = self.body(self.logged_in())
        assert "<b>lfm</b>" not in body and "&lt;b&gt;lfm&lt;/b&gt;" in body
        form = acao_form(body, "lastfm_scrobble")
        assert form is not None and form.values("scrobble"), "checkbox marcado = scrobble ligado"
        self.world.link_lastfm(scrobble=False)
        assert not acao_form(self.body(self.logged_in()), "lastfm_scrobble").values("scrobble")

    def test_toggle_changes_only_the_scrobble_flag(self):
        self.world.link_lastfm(scrobble=True)
        browser = self.logged_in()
        before = self.world.doc()
        assert self.act(browser, "lastfm_scrobble", scrobble=None).code == 200
        expected = {**before, "lastfm": {**before["lastfm"], "scrobble": False}}
        assert self.world.doc() == expected, "sessionkey e username intactos; demais campos também"
        assert self.act(browser, "lastfm_scrobble", scrobble="on").code == 200
        assert self.world.doc()["lastfm"]["scrobble"] is True

    def test_the_session_key_never_reaches_the_page_or_any_response_header(self):
        self.world.link_lastfm()
        browser = self.logged_in()
        responses = [
            browser.get(URL),
            self.act(browser, "lastfm_scrobble", scrobble=None),
            self.act(browser, "lastfm_scrobble", htmx=True, scrobble="on"),
            self.act(browser, "prefixo", custom_prefix="a b"),
        ]
        for response in responses:
            assert SESSIONKEY not in response.body.decode() and SESSIONKEY[:10] not in response.body.decode()
            assert SESSIONKEY not in str(response.headers)
        stale = self.form(browser, "lastfm_scrobble")
        self.world.set_doc(lastfm={**self.world.doc()["lastfm"], "scrobble": False})
        conflict = self.submit(browser, URL, stale, scrobble="on")
        assert conflict.code == 409 and SESSIONKEY not in conflict.body.decode()

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

    def test_stale_toggle_is_409_and_other_users_account_is_untouched(self):
        self.world.link_lastfm()
        self.world.link_lastfm(OTHER_UID, username="outro_lfm", scrobble=True)
        browser = self.logged_in()
        other_before = self.world.doc(OTHER_UID)
        form = self.form(browser, "lastfm_scrobble")
        self.world.set_doc(lastfm={**self.world.doc()["lastfm"], "scrobble": False})
        assert self.submit(browser, URL, form, scrobble="on").code == 409
        assert self.world.doc(OTHER_UID) == other_before

    def test_linking_and_unlinking_stay_on_discord(self):
        self.world.link_lastfm()
        browser = self.logged_in()
        form = self.form(browser, "lastfm_scrobble")
        before = self.world.doc()
        for acao in ("lastfm_desvincular", "lastfm_vincular"):
            assert self.submit(browser, URL, form, acao=acao).code == 422
        assert self.submit(
            browser, URL, form, pairs=form.pairs(scrobble="on") + [("sessionkey", "NOVA"), ("username", "x")]
        ).code in (200, 422)
        assert self.world.doc()["lastfm"]["sessionkey"] == before["lastfm"]["sessionkey"] == SESSIONKEY
        assert self.world.doc()["lastfm"]["username"] == "usuario_lfm"


class RpcTokenTest(AccountCase):
    def generate(self, browser, **kw):
        return self.act(browser, "rpc_token_gerar", **kw)

    def test_available_when_the_command_would_be_available(self):
        body = self.body(self.logged_in())
        assert acao_form(body, "rpc_token_gerar") is not None
        assert "Nenhum token" in html.unescape(body)

    def test_unavailable_exactly_when_the_command_would_be_unavailable(self):
        cases = {
            "ENABLE_RPC_COMMAND desligado e não é dono": {"ENABLE_RPC_COMMAND": False},
            "autenticação do RPC desligada (sem botões de token no comando)": {"ENABLE_RPC_AUTH": False},
            "sem RPC_PUBLIC_URL nem RPC_SERVER": {"RPC_PUBLIC_URL": "", "RPC_SERVER": ""},
        }

        def check(item):
            label, overrides = item
            self.world.config.update(
                {
                    "ENABLE_RPC_COMMAND": True,
                    "ENABLE_RPC_AUTH": True,
                    "RPC_PUBLIC_URL": "wss://rpc.example.com/ws",
                    "RPC_SERVER": "",
                }
            )
            browser = self.logged_in()
            form = self.form(browser, "rpc_token_gerar")
            self.world.config.update(overrides)
            assert acao_form(self.body(browser), "rpc_token_gerar") is None, "formulário oculto"
            before = self.world.doc()
            response = self.submit(browser, URL, form)
            assert response.code == 403 and not TOKEN.search(response.body.decode())
            assert self.world.doc() == before and self.db.writes == []

        Each.run(list(cases.items()), check)

    def test_the_bot_owner_may_use_it_even_when_the_command_is_off_for_everyone(self):
        self.world.config["ENABLE_RPC_COMMAND"] = False
        self.world.owner_ids.add(UID)
        browser = self.logged_in()
        assert self.generate(browser).code == 200 and TOKEN.fullmatch(self.world.doc()["token"])

    def test_generated_token_has_the_commands_format_and_is_stored_and_shown_once(self):
        browser = self.logged_in()
        response = self.generate(browser)
        stored = self.world.doc()["token"]
        assert response.code == 200 and re.fullmatch(r"[A-Za-z0-9]{50}", stored)
        assert stored in response.body.decode(), "o POST mostra o token"
        assert response.headers.get("Cache-Control") == "no-store"
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name
        assert not [h for h in response.headers.get_list("Set-Cookie") if stored in h]

    def test_get_and_later_responses_never_contain_the_token(self):
        browser = self.logged_in()
        self.generate(browser)
        token = self.world.doc()["token"]
        body = self.body(browser)
        assert token not in body and "Token configurado" in html.unescape(body) and "Nenhum token" not in body
        for response in (
            self.act(browser, "prefixo", htmx=True, custom_prefix="a b"),
            self.act(browser, "prefixo", custom_prefix=">>"),
            browser.get(URL + "/favoritos/exportar"),
        ):
            assert token not in response.body.decode()
        assert not TOKEN.search(body) or token not in body

    def test_a_stale_generation_conflicts_and_its_response_does_not_leak_the_token(self):
        browser = self.logged_in()
        stale = self.form(browser, "rpc_token_gerar")
        self.generate(browser)
        token = self.world.doc()["token"]
        response = self.submit(browser, URL, stale)
        assert response.code == 409 and token not in response.body.decode()
        assert CONFLICT_TEXT in html.unescape(response.body.decode())

    def test_each_generation_is_new_and_does_not_use_the_random_module(self):
        def boom(*args, **kwargs):
            raise AssertionError("o token do painel não pode usar `random` (não é criptográfico)")

        for name in ("choice", "choices", "randint", "randrange", "sample", "getrandbits", "random"):
            self.monkeypatch.setattr(random, name, boom)
        browser = self.logged_in()
        seen = set()
        for _ in range(3):
            assert self.generate(browser).code == 200
            seen.add(self.world.doc()["token"])
        assert len(seen) == 3 and all(re.fullmatch(r"[A-Za-z0-9]{50}", t) for t in seen)

    def test_only_the_token_field_changes(self):
        before = self.world.doc()
        self.generate(self.logged_in())
        after = self.world.doc()
        assert {k for k in after if after[k] != before.get(k)} == {"token"}

    def test_the_version_does_not_depend_on_the_token_value(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        browser = self.logged_in()
        first = self.form(browser, "rpc_token_gerar").value("versao")
        self.world.set_doc(token="U" * 50)
        assert self.form(browser, "rpc_token_gerar").value("versao") == first, "o hash não pode expor o segredo"
        assert re.fullmatch(r"[0-9a-f]{16}", first)

    def test_replacing_a_token_first_closes_the_users_active_presence_then_writes(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        self.world.bot.music.players[555] = FakeRpcPlayer(self.world.journal, "na-voz", [UID])
        self.world.bot.music.players[666] = FakeRpcPlayer(self.world.journal, "sem-o-usuario", [OTHER_UID])
        assert self.generate(self.logged_in()).code == 200
        rpc = [e for e in self.world.journal if e[0] == "rpc"]
        assert len(rpc) == 1 and rpc[0][1] == "na-voz" and rpc[0][2] == [UID] and rpc[0][3]["op"] == "close"
        order = [e[0] for e in self.world.journal if e[0] in ("rpc", "db")]
        assert order == ["rpc", "db"], "como o comando: fecha a presença com o token antigo e só então grava"

    def test_first_token_has_nothing_to_close(self):
        self.world.bot.music.players[555] = FakeRpcPlayer(self.world.journal, "na-voz", [UID])
        assert self.generate(self.logged_in()).code == 200
        assert [e for e in self.world.journal if e[0] == "rpc"] == []

    def test_a_failing_rpc_close_does_not_prevent_the_new_token_or_leak(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        player = FakeRpcPlayer(self.world.journal, "quebrado", [UID])

        async def boom(*args, **kwargs):
            raise RuntimeError("falha-rpc-secreta")

        player._send_rpc_data = boom
        self.world.bot.music.players[555] = player
        response = self.generate(self.logged_in())
        assert response.code == 200 and self.world.doc()["token"] != RPC_TOKEN_OLD
        assert "falha-rpc-secreta" not in response.body.decode() + self.all_log_text()

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

    def test_players_without_voice_information_are_skipped_when_closing_the_presence(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        player = FakeRpcPlayer(self.world.journal, "sem-voz", [UID])
        player.guild.me.voice = None
        self.world.bot.music.players[555] = player
        response = self.generate(self.logged_in())
        assert response.code == 200 and self.world.doc()["token"] != RPC_TOKEN_OLD
        assert [e for e in self.world.journal if e[0] == "rpc"] == []

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

    def test_token_and_old_token_never_reach_logs_or_the_audit(self):
        self.world.set_doc(token=RPC_TOKEN_OLD)
        browser = self.logged_in()
        self.caplog.clear()
        self.generate(browser)
        token = self.world.doc()["token"]
        logs = self.all_log_text()
        assert (
            token not in logs and RPC_TOKEN_OLD not in logs and OAUTH_SECRET not in logs and COOKIE_SECRET not in logs
        )
        audit = self.audit_text()
        assert str(UID) in audit and "rpc_token_gerar" in audit and "token" in audit

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

    def test_import_or_edit_of_a_chosen_token_is_not_part_of_the_v1(self):
        browser = self.logged_in()
        form = self.form(browser, "rpc_token_gerar")
        before = self.world.doc()
        for acao in ("rpc_token_importar", "rpc_token_remover"):
            assert self.submit(browser, URL, form, acao=acao, token="A" * 50).code == 422, acao
        assert self.submit(browser, URL, form, pairs=form.pairs() + [("token", "A" * 50)]).code in (200, 422)
        assert self.world.doc()["token"] != "A" * 50, "o token nunca vem do formulário"
        assert before["token"] == ""

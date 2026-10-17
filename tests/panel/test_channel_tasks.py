"""E4c — categoria `canal`: EXECUÇÃO do setup/reset como tarefas com acompanhamento (grupos 4–7 da PROPOSTA-E4c).

Contrato (interpretações em .qa-e4c-interp.txt):
- POST válido de configurar/confirmar_reset = 202 + bloco da tarefa: elemento com `data-estado` ∈
  pendente|executando|ok|erro e link/hx-get para `/painel/servidores/<gid>/canal/tarefas/<id>` (id urlsafe de 32
  caracteres); enquanto não final, `hx-trigger="every 2s"`; nos estados finais NÃO há hx-trigger (o polling para).
- reset em dois passos: `acao=reset` devolve a confirmação (200, sem efeitos) com `token` assinado; `acao=confirmar_reset`
  com o token cria a tarefa. Deletar o canal exige digitar o nome exato (`confirmar_nome`).
- O painel usa `apply_request_channel(...)` e `reset_request_channel(...)` de utils/music/request_channel.py com o default
  de `send_idle_embed` (os testes trocam esse default) e entrega cópias profundas dos dados (FakeDB audita).
"""

import asyncio
import html
import logging
import re
from urllib.parse import urlencode

from tests.helpers_request_channel import FakePlayer, FakeThreadInfo
from tests.panel.helpers import COOKIE_SECRET, OAUTH_SECRET, require
from tests.panel.helpers_channel import GID, PANEL_USER, TASK_ID
from tests.panel.helpers_login import DEFAULT_USER
from tests.panel.helpers_settings import NOT_FOUND_TEXT, UID, acao_form
from tests.panel.test_channel_page import CanalBase
from tests.panel.test_settings_http import Each, external_change
from empiremuse.utils.music.errors import GenericError

TASK_URL = re.compile(r"/painel/servidores/(\d+)/canal/tarefas/([A-Za-z0-9_-]{32})")
FINAL = ("ok", "erro")


def task_ref(body):
    match = TASK_URL.search(html.unescape(body))
    return match.group(0) if match else None


def estado(body):
    match = re.search(r'data-estado="([a-z]+)"', body)
    return match.group(1) if match else None


def polls_every_2s(body):
    return bool(re.search(r'hx-trigger="[^"]*every 2s[^"]*"', body)) and "hx-get=" in body


class TasksBase(CanalBase):
    def start(self, browser, htmx=True, **fields):
        return self.configure(browser, htmx=htmx, **fields)

    def poll(self, browser, ref, htmx=True):
        return browser.get(ref, headers={"HX-Request": "true"} if htmx else {})

    def finish(self, browser, response, loops=40):
        """Deixa a tarefa andar e devolve (estado final, corpo) do último polling."""
        assert response.code == 202, f"POST deveria criar a tarefa (202), veio {response.code}"
        ref = task_ref(response.body.decode())
        assert ref, "a resposta 202 deve apontar para a tarefa"
        for _ in range(loops):
            self.settle(0.02)
            polled = self.poll(browser, ref)
            assert polled.code == 200, f"polling: {polled.code}"
            if estado(polled.body.decode()) in FINAL:
                return estado(polled.body.decode()), polled.body.decode()
        raise AssertionError("a tarefa não terminou")

    def run_setup(self, browser=None, **fields):
        browser = browser or self.logged_in()
        return self.finish(browser, self.start(browser, **fields))

    def reset_confirmation(self, browser, **fields):
        form = acao_form(self.body(browser), "reset")
        assert form is not None, "página configurada deve oferecer o formulário acao=reset"
        return self.submit(browser, self.canal_url(), form, htmx=True, **fields)

    def confirm_reset(self, browser, confirmation, **fields):
        form = acao_form(confirmation.body.decode(), "confirmar_reset")
        assert form is not None, "a confirmação deve trazer o formulário acao=confirmar_reset"
        return self.submit(browser, self.canal_url(), form, htmx=True, **fields)

    def db_other_fields(self):
        doc = self.world.doc
        pc = {k: v for k, v in doc["player_controller"].items() if k not in ("channel", "message_id")}
        return {k: v for k, v in doc.items() if k != "player_controller"}, pc


# ============================================================================ tarefa de setup: execução e efeitos


class SetupExecutionTest(TasksBase):
    def test_existing_text_channel_runs_the_same_steps_as_the_command_and_saves_last(self):
        browser = self.logged_in()
        response = self.start(browser, modo="existente", canal="22")
        assert response.code == 202
        state, body = self.finish(browser, response)
        assert state == "ok", body
        names = [
            n
            for n in self.world.j.names()
            if n in ("channel.history", "channel.edit", "send_idle_embed", "message.create_thread", "db")
        ]
        assert names == ["channel.history", "channel.edit", "send_idle_embed", "message.create_thread", "db"]
        assert self.world.doc["player_controller"]["channel"] == "22"
        assert self.world.doc["player_controller"]["message_id"] == str(self.world.next_message)

    def test_only_channel_and_message_id_change_and_ver_and_favorites_stay(self):
        other, pc = self.db_other_fields()
        self.run_setup(modo="existente", canal="22")
        other_after, pc_after = self.db_other_fields()
        assert other_after == other and pc_after == pc
        assert self.db.writes == [(str(7000), GID)]
        assert isinstance(self.world.doc["player_controller"]["channel"], str)

    def test_success_message_is_pt_br_and_has_no_exception_text(self):
        state, body = self.run_setup(modo="existente", canal="22")
        text = html.unescape(re.sub(r"<[^>]+>", " ", body))
        assert state == "ok" and "<#22>" not in body and "Traceback" not in text and "repr" not in text.lower()

    def test_clear_messages_purges_up_to_100_keeping_the_bots_thread_messages(self):
        self.run_setup(modo="existente", canal="22", limpar_mensagens="on")
        purge = self.world.j.of("channel.purge")
        assert len(purge) == 1 and purge[0][2] == 100

    def test_without_clearing_nothing_is_purged(self):
        self.run_setup(modo="existente", canal="22", limpar_mensagens=None)
        assert self.world.j.of("channel.purge") == []

    def test_voice_channel_gets_no_thread(self):
        self.run_setup(modo="existente", canal="33")
        assert self.world.j.of("message.create_thread") == [] and self.world.doc["player_controller"]["channel"] == "33"

    def test_forum_creates_a_post_with_the_given_title_and_saves_the_post_id(self):
        self.run_setup(modo="existente", canal="55", titulo_forum="Pedidos do bot")
        create = self.world.j.of("forum.create_thread")[0]
        assert create[2:] == ("Pedidos do bot", "Post para pedido de músicas.", 10080, 5)
        post = self.world.forum.created[0]
        assert self.world.doc["player_controller"]["channel"] == str(post.id)
        assert self.world.j.of("channel.purge") == [], "limpar mensagens é ignorado em fórum"

    def test_create_text_channel_inside_the_chosen_category(self):
        self.run_setup(modo="criar", tipo="texto", categoria="66")
        created = self.world.j.of("create_text_channel")[0]
        assert created[1] == "#Música" and created[2] == "Bot Um player controller"
        assert self.world.doc["player_controller"]["channel"] == str(self.world.guild._next)
        assert self.world.j.of("channel.edit") == [], "canal novo não tem overwrite editado de novo"

    def test_create_without_category_uses_the_guild_root(self):
        self.run_setup(modo="criar", tipo="voz", categoria="")
        assert self.world.j.of("create_voice_channel")[0][1] == "raiz"

    def test_actor_in_discord_reasons_and_notices_is_the_panel_user(self):
        old = self.world.other.add_message(777, self.world.guild.me, FakeThreadInfo(self.world.j, "thread-antiga"))
        self.world.configure("23", "777")
        self.run_setup(modo="existente", canal="22")
        edit = self.world.j.of("message.edit")[0]
        assert PANEL_USER in edit[2]["embed"].description, "o aviso de canal reconfigurado cita o usuário do painel"
        thread_edit = self.world.j.of("thread.edit")[0]
        assert PANEL_USER in thread_edit[2]["reason"] and old.id == 777

    def test_active_player_is_moved_to_the_new_channel(self):
        player = FakePlayer(self.world.j, self.world.guild, self.world.lobby, static=False, message=None)
        self.world.bot.music.players[GID] = player
        self.run_setup(modo="existente", canal="22")
        assert player.static is True and player.text_channel is self.world.text

    def test_generic_error_during_execution_ends_in_erro_with_the_pt_br_text_and_the_database_untouched(self):
        self.world.fail_with = GenericError("**O bot não pôde enviar a mensagem inicial.**")
        before = self.world.doc
        state, body = self.run_setup(modo="existente", canal="22")
        text = html.unescape(re.sub(r"<[^>]+>", " ", body))
        assert state == "erro" and "O bot não pôde enviar a mensagem inicial." in text
        assert "GenericError" not in text and self.world.doc == before and self.db.writes == []

    def test_unexpected_error_is_generic_in_the_page_and_only_its_type_in_the_log(self):
        self.world.fail_with = RuntimeError("segredo-interno-123")
        state, body = self.run_setup(modo="existente", canal="22")
        assert state == "erro" and "Não foi possível concluir. Tente novamente." in html.unescape(body)
        assert "segredo-interno-123" not in body
        logs = "\n".join(r.getMessage() for r in self.caplog.records)
        assert "segredo-interno-123" not in logs and "RuntimeError" in logs
        assert self.db.writes == []

    def test_data_is_read_and_written_through_the_bot_with_a_deep_copy(self):
        self.run_setup(modo="existente", canal="22")
        assert self.db.violations == [], self.db.violations  # mutar o cache / gravar o dict do cache / id não-int


# ============================================================================ tarefa: estados, polling, acesso, limites


class TaskLifecycleTest(TasksBase):
    def test_post_returns_202_with_an_urlsafe_32_char_task_id_and_a_polling_block(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        response = self.start(browser, modo="existente", canal="22")
        body = response.body.decode()
        assert response.code == 202 and "<html" not in body.lower()
        ref = task_ref(body)
        assert ref and TASK_ID.fullmatch(ref.rsplit("/", 1)[1])
        assert estado(body) in ("pendente", "executando") and polls_every_2s(body)
        assert html.unescape(re.search(r'hx-get="([^"]+)"', body).group(1)) == ref

    def test_states_go_from_running_to_ok_and_polling_stops_by_itself(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        running = self.poll(browser, ref)
        assert running.code == 200 and estado(running.body.decode()) == "executando"
        assert polls_every_2s(running.body.decode())
        self.world.gate.set()
        self.settle()
        done = self.poll(browser, ref).body.decode()
        assert estado(done) == "ok" and not polls_every_2s(done) and "every" not in done
        assert estado(self.poll(browser, ref).body.decode()) == "ok", "estado final estável"

    def test_error_state_also_stops_polling(self):
        self.world.fail_with = RuntimeError("x")
        state, body = self.run_setup(modo="existente", canal="22")
        assert state == "erro" and "every" not in body and "hx-trigger" not in body

    def test_plain_post_without_htmx_returns_the_whole_page_with_a_link_to_the_task(self):
        browser = self.logged_in()
        response = self.start(browser, htmx=False, modo="existente", canal="22")
        body = response.body.decode()
        assert response.code == 202 and "<html" in body.lower() and task_ref(body)
        ref = task_ref(body)
        self.settle()
        page = self.poll(browser, ref, htmx=False)
        assert page.code == 200 and "<html" in page.body.decode().lower(), "sem htmx o acompanhamento é uma página"

    def test_task_poll_has_security_headers_and_no_store(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        response = self.poll(browser, ref)
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_only_one_running_task_per_guild(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        first = self.start(browser, modo="existente", canal="22")
        self.settle()
        second = self.start(browser, modo="existente", canal="23")
        assert first.code == 202 and second.code == 409
        assert (
            "andamento" in html.unescape(second.body.decode()).lower()
            or "aguarde" in html.unescape(second.body.decode()).lower()
        )
        self.world.gate.set()
        self.settle()
        self.world.gate = None
        third = self.start(browser, modo="existente", canal="23")
        assert third.code in (202, 409), "depois de terminar, nova tarefa é aceita (409 só por versão velha)"

    def test_a_new_task_is_accepted_after_the_previous_one_finished(self):
        browser = self.logged_in()
        assert self.run_setup(browser, modo="existente", canal="22")[0] == "ok"
        assert self.run_setup(browser, modo="existente", canal="23")[0] == "ok"
        assert self.world.doc["player_controller"]["channel"] == "23"

    def test_unknown_malformed_and_foreign_task_ids_are_the_generic_404(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        assert browser.get(ref).code == 200, "a rota de acompanhamento deve existir"
        reference = browser.get("/painel/servidores/999999/canal").body.decode()

        def check(path):
            response = browser.get(path, headers={"HX-Request": "true"})
            assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode(), response.code

        base = f"/painel/servidores/{GID}/canal/tarefas/"
        Each.run(
            [
                base + "a" * 32,
                base + "short",
                base + "../" + "a" * 29,
                base + "a" * 33,
                base + "%00" * 8,
                "/painel/servidores/300/canal/tarefas/" + ref.rsplit("/", 1)[1],
                f"/painel/servidores/abc/canal/tarefas/{'a' * 32}",
            ],
            check,
        )
        assert reference

    def test_another_user_cannot_read_the_task_even_with_the_id(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        self.fake.user = {**DEFAULT_USER, "id": "2002", "username": "outro", "global_name": "Outro"}
        self.world.guild.members[2002] = self.world.guild.members[UID]
        other = self.browser()
        assert self.login(other).code == 302
        response = other.get(ref, headers={"HX-Request": "true"})
        assert response.code == 404 and NOT_FOUND_TEXT in response.body.decode()
        assert browser.get(ref).code == 200, "o dono continua vendo"

    def test_post_to_the_task_url_is_refused_without_a_server_error(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        self.clock.advance(4)
        response = browser.post(
            ref, body="a=1", headers={"Content-Type": "application/x-www-form-urlencoded", **self.xsrf_header(browser)}
        )
        assert response.code in (404, 405), f"POST na URL de acompanhamento: {response.code} (nunca 500)"
        assert not [r for r in self.caplog.records if r.levelno >= logging.ERROR], "sem 'Uncaught exception' no log"

    def test_409_for_another_user_does_not_expose_the_active_task_of_the_owner(self):
        """BAIXO-1 do AppSec: o 409 do usuário B não pode trazer bloco/URL/polling da tarefa de A (daria 404)."""
        self.world.gate = asyncio.Event()
        owner = self.logged_in()
        mine = task_ref(self.start(owner, modo="existente", canal="22").body.decode())
        self.settle()
        self.fake.user = {**DEFAULT_USER, "id": "2002", "username": "outro", "global_name": "Outro"}
        self.world.guild.members[2002] = self.world.guild.members[UID]
        other = self.browser()
        assert self.login(other).code == 302
        form = self.setup_form(other)  # com o _xsrf do próprio B
        assert estado(self.body(other)) is None, "B não vê a tarefa de A na página"
        for htmx in (True, False):
            response = self.submit(other, self.canal_url(), form, htmx=htmx, modo="existente", canal="23")
            body = response.body.decode()
            assert response.code == 409, f"htmx={htmx}: {response.code}"
            assert mine.rsplit("/", 1)[1] not in html.unescape(body), "id da tarefa de A vazou para B"
            assert not TASK_URL.search(html.unescape(body)) and "hx-trigger" not in body and "data-estado" not in body
            assert "andamento" in html.unescape(body).lower() or "aguarde" in html.unescape(body).lower()
        assert task_ref(self.body(owner)) == mine, "o dono continua vendo a própria tarefa"
        assert estado(self.poll(owner, mine).body.decode()) in ("pendente", "executando")

    def test_anonymous_poll_goes_to_login(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        assert self.browser().get(ref).code == 302

    def test_poll_is_404_after_the_owner_lost_permission(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        member = self.world.guild.members[UID]
        member.guild_permissions.administrator = member.guild_permissions.manage_guild = False
        self.clock.advance(31)
        assert browser.get(ref).code == 404

    def test_finished_tasks_expire_15_minutes_after_finishing(self):
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        assert estado(browser.get(ref).body.decode()) == "ok"
        self.clock.advance(14 * 60)
        assert browser.get(ref).code == 200
        self.clock.advance(2 * 60)
        assert browser.get(ref).code == 404

    def test_task_limits_are_pinned_by_constants(self):
        tasks = require("empiremuse.panel.services.tasks")
        assert (
            tasks.TASK_TIMEOUT_SECONDS,
            tasks.MAX_TASKS_PER_USER,
            tasks.MAX_TASKS_TOTAL,
            tasks.TASK_TTL_SECONDS,
        ) == (60, 5, 500, 15 * 60)

    def test_shutdown_cancels_running_tasks_and_leaves_none_behind(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        ref = task_ref(self.start(browser, modo="existente", canal="22").body.decode())
        self.settle()
        runner = self.panel_app.settings["task_runner"]
        self.io_loop.run_sync(runner.shutdown)
        assert self.world.cancelled is True, "a tarefa em andamento recebeu o cancelamento"
        later = browser.get(ref)
        assert later.code == 404 or estado(later.body.decode()) == "erro"
        assert self.db.writes == [], "setup cancelado antes do fim não grava"


class TaskConcurrencyTest(TasksBase):
    def test_two_simultaneous_setups_one_is_accepted_and_one_conflicts(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        self.clock.advance(4)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "HX-Request": "true",
            "Cookie": "; ".join(f"{k}={v}" for k, v in browser.cookies.items()),
            **self.xsrf_header(browser),
        }
        bodies = [urlencode(form.pairs(modo="existente", canal=c)) for c in ("22", "23")]
        path = self.canal_url()

        async def both():
            return await asyncio.gather(
                *[
                    self.http_client.fetch(
                        self.get_url(path),
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
        assert codes == [202, 409], codes
        self.settle(0.2)
        assert len(self.db.writes) <= 1

    def test_settings_write_during_a_running_task_is_not_lost(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        self.start(browser, modo="existente", canal="22")
        self.settle()
        url, form, _ = self.open_form(browser, GID, "player", "default_player_volume")
        self.clock.advance(4)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "; ".join(f"{k}={v}" for k, v in browser.cookies.items()),
            **self.xsrf_header(browser),
        }
        body = urlencode(form.pairs(default_player_volume="45"))

        async def scenario():
            settings_write = asyncio.ensure_future(
                self.http_client.fetch(
                    self.get_url(url),
                    method="POST",
                    headers=headers,
                    body=body,
                    raise_error=False,
                    follow_redirects=False,
                )
            )
            await asyncio.sleep(0.1)
            self.world.gate.set()
            return await settings_write

        response = self.io_loop.run_sync(scenario)
        self.settle(0.2)
        assert response.code == 200, response.code
        doc = self.world.doc
        assert doc["default_player_volume"] == 45, "a escrita das configurações não pode se perder"
        assert doc["player_controller"]["channel"] == "22", "nem a do canal de pedidos"


# ============================================================================ reset: confirmação dupla, token, deletar


class ResetFlowTest(TasksBase):
    def test_step_one_shows_the_confirmation_and_changes_nothing(self):
        self.world.text.name = "<b>pedidos</b>"
        self.world.configured_text()
        browser = self.logged_in()
        response = self.reset_confirmation(browser)
        body = response.body.decode()
        assert response.code == 200 and "<html" not in body.lower()
        assert "<b>pedidos</b>" not in body and "&lt;b&gt;pedidos&lt;/b&gt;" in body, "nome do canal escapado"
        form = acao_form(body, "confirmar_reset")
        assert form and form.value("token") and form.value("_xsrf") and form.value("versao")
        assert list(self.world.j) == [] and not TASK_URL.search(body)
        assert self.world.doc["player_controller"]["channel"] == "22"

    def test_default_is_not_deleting_and_the_irreversible_warning_appears_only_when_deleting(self):
        self.world.configured_text()
        browser = self.logged_in()
        plain = self.reset_confirmation(browser).body.decode()
        assert acao_form(plain, "confirmar_reset").has("confirmar_nome") is False
        deleting = self.reset_confirmation(browser, deletar="on").body.decode()
        form = acao_form(deleting, "confirmar_reset")
        assert form.has("confirmar_nome") and "irrevers" in html.unescape(deleting).lower()

    def test_reset_without_a_configured_channel_is_422(self):
        browser = self.logged_in()
        form = acao_form(self.body(browser), "reset") or self.setup_form(browser)
        response = self.submit(browser, self.canal_url(), form, htmx=True, acao="reset")
        assert response.code == 422 and list(self.world.j) == []

    def test_reset_needs_manage_threads_up_front(self):
        self.world.configured_text()
        self.world.guild.me.guild_permissions = self.world.guild.me.guild_permissions.__class__(manage_threads=False)
        response = self.reset_confirmation(self.logged_in())
        assert response.code == 422 and "Gerenciar Tópicos" in html.unescape(response.body.decode())

    def test_stale_version_in_step_one_is_409(self):
        browser = self.logged_in()
        self.world.configured_text()
        form = acao_form(self.body(browser), "reset")
        external_change(self.db, "7000", GID, autoplay=True)  # não é do formulário: não conflita
        self.world.configure("23", "1")  # channel/message_id mudaram
        response = self.submit(browser, self.canal_url(), form, htmx=True)
        assert response.code == 409

    def test_confirming_runs_the_reset_task_like_the_command(self):
        message = self.world.configured_text()
        browser = self.logged_in()
        confirmation = self.reset_confirmation(browser)
        state, body = self.finish(browser, self.confirm_reset(browser, confirmation))
        assert state == "ok", body
        assert self.world.doc["player_controller"]["channel"] is None
        assert self.world.doc["player_controller"]["message_id"] is None
        assert self.world.j.of("channel.delete") == [], "padrão = não apagar o canal"
        edit = self.world.j.of("message.edit")[0][2]
        assert PANEL_USER in edit["content"] and message.id == 555
        (button,) = edit["components"]
        assert button.custom_id == "musicplayer_request_channel"
        assert self.world.j.of("thread.edit")[0][2]["archived"] is True

    def test_only_channel_and_message_id_are_cleared(self):
        self.world.configured_text()
        other, pc = self.db_other_fields()
        browser = self.logged_in()
        self.finish(browser, self.confirm_reset(browser, self.reset_confirmation(browser)))
        other_after, pc_after = self.db_other_fields()
        assert other_after == other and pc_after == pc and self.db.violations == []

    def test_forum_reset_clears_the_database_and_deletes_the_post(self):
        post = self.world.configured_forum()
        browser = self.logged_in()
        state, _ = self.finish(browser, self.confirm_reset(browser, self.reset_confirmation(browser)))
        assert state == "ok"
        assert self.world.j.of("channel.delete")[0][1] == post.label
        assert self.world.doc["player_controller"]["channel"] is None
        assert self.world.doc["player_controller"]["message_id"] is None

    def test_deleting_the_channel_needs_its_exact_name(self):
        self.world.configured_text()
        browser = self.logged_in()
        confirmation = self.reset_confirmation(browser, deletar="on")

        def check(typed):
            response = self.confirm_reset(browser, confirmation, deletar="on", confirmar_nome=typed)
            assert response.code == 422, f"{typed!r}: {response.code}"

        Each.run(["", "Pedidos", "pedidos ", "pedido", "#pedidos"], check)
        assert list(self.world.j) == [] and self.world.doc["player_controller"]["channel"] == "22"

    def test_exact_name_deletes_the_channel_after_clearing_the_database(self):
        self.world.configured_text()
        browser = self.logged_in()
        confirmation = self.reset_confirmation(browser, deletar="on")
        state, _ = self.finish(
            browser, self.confirm_reset(browser, confirmation, deletar="on", confirmar_nome="pedidos")
        )
        assert state == "ok"
        delete = self.world.j.of("channel.delete")[0]
        assert delete[1] == "#pedidos" and PANEL_USER in delete[2]
        names = self.world.j.names()
        assert names.index("db") < names.index("channel.delete"), "ordem do comando: banco antes do Discord"

    def test_tampering_with_the_delete_flag_in_step_two_still_requires_the_name(self):
        self.world.configured_text()
        browser = self.logged_in()
        confirmation = self.reset_confirmation(browser)  # passo 1 SEM deletar
        response = self.confirm_reset(browser, confirmation, deletar="on", confirmar_nome="")
        assert response.code == 422 and self.world.j.of("channel.delete") == []


class ResetTokenTest(TasksBase):
    def setUp(self):
        super().setUp()
        self.world.configured_text()

    def two_steps(self):
        browser = self.logged_in()
        return browser, self.reset_confirmation(browser)

    def test_missing_or_tampered_token_is_422(self):
        browser, confirmation = self.two_steps()

        def check(token):
            response = self.confirm_reset(browser, confirmation, token=token)
            assert response.code == 422, f"{token!r}: {response.code}"

        form = acao_form(confirmation.body.decode(), "confirmar_reset")
        real = form.value("token")
        Each.run(["", "x", real[:-2] + ("AA" if not real.endswith("AA") else "BB"), real + "x", real.upper()], check)
        assert list(self.world.j) == [] and self.world.doc["player_controller"]["channel"] == "22"

    def test_token_expires_after_two_minutes(self):
        browser, confirmation = self.two_steps()
        self.clock.advance(121)
        response = self.confirm_reset(browser, confirmation)
        assert response.code == 422 and self.world.doc["player_controller"]["channel"] == "22"

    def test_token_still_works_inside_the_two_minutes(self):
        browser, confirmation = self.two_steps()
        self.clock.advance(100)
        assert self.confirm_reset(browser, confirmation).code == 202

    def test_token_is_single_use(self):
        browser, confirmation = self.two_steps()
        assert self.finish(browser, self.confirm_reset(browser, confirmation))[0] == "ok"
        self.world.configured_text()  # mesmo canal de volta: só o uso único impede o reuso
        again = self.confirm_reset(browser, confirmation)
        assert again.code in (409, 422), again.code
        assert len(self.db.writes) == 1

    def test_token_is_bound_to_the_channel(self):
        browser, confirmation = self.two_steps()
        self.world.configure("23", "1")
        response = self.confirm_reset(browser, confirmation)
        assert response.code in (409, 422) and self.world.j.of("channel.delete") == []
        assert self.world.doc["player_controller"]["channel"] == "23"

    def test_token_is_bound_to_the_user(self):
        browser, confirmation = self.two_steps()
        form = acao_form(confirmation.body.decode(), "confirmar_reset")
        self.fake.user = {**DEFAULT_USER, "id": "2002", "username": "outro", "global_name": "Outro"}
        self.world.guild.members[2002] = self.world.guild.members[UID]
        other = self.browser()
        assert self.login(other).code == 302
        # o _xsrf tem de ser o do navegador do 2002, senão o Tornado devolve 403 antes do código do painel
        other_token = self.xsrf_header(other)["X-XSRFToken"]
        pairs = [(name, other_token if name == "_xsrf" else value) for name, value in form.pairs()]
        response = self.submit(other, self.canal_url(), form, htmx=True, pairs=pairs)
        assert response.code in (409, 422), f"o token do 1001 não vale para o 2002: {response.code}"
        assert self.world.doc["player_controller"]["channel"] == "22"
        assert list(self.world.j) == []

    def test_token_never_reaches_the_logs(self):
        browser, confirmation = self.two_steps()
        token = acao_form(confirmation.body.decode(), "confirmar_reset").value("token")
        self.finish(browser, self.confirm_reset(browser, confirmation))
        assert token not in "\n".join(r.getMessage() for r in self.caplog.records)


# ============================================================================ logs


class CanalAuditTest(TasksBase):
    def test_setup_audit_names_user_guild_bot_category_and_kind_but_no_values(self):
        self.world.text.name = "canal-SEGREDO"
        self.caplog.clear()
        browser = self.logged_in()
        self.finish(browser, self.start(browser, modo="existente", canal="55", titulo_forum="Titulo-SEGREDO-do-post"))
        audit = self.audit_text()
        for needle in (PANEL_USER, str(GID), "7000", "canal", "setup"):
            assert needle in audit, f"{needle!r} ausente da auditoria: {audit!r}"
        logs = self.all_log_text()
        for value in ("Titulo-SEGREDO", "canal-SEGREDO", OAUTH_SECRET, COOKIE_SECRET):
            assert value not in logs, value

    def test_reset_audit_has_kind_and_never_the_typed_channel_name(self):
        self.world.text.name = "canal-SEGREDO"
        self.world.configured_text()
        browser = self.logged_in()
        self.caplog.clear()
        confirmation = self.reset_confirmation(browser, deletar="on")
        self.finish(browser, self.confirm_reset(browser, confirmation, deletar="on", confirmar_nome="canal-SEGREDO"))
        audit = self.audit_text()
        assert "reset" in audit and PANEL_USER in audit and "canal" in audit, audit
        assert "canal-SEGREDO" not in self.all_log_text()

    def test_validation_failures_are_not_audited_as_changes(self):
        browser = self.logged_in()
        self.caplog.clear()
        self.configure(browser, modo="existente", canal="abc")
        assert self.audit_text() == ""

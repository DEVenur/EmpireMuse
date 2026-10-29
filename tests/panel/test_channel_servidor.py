"""Categoria `canal` do painel em escopo servidor (item 11, P4, S8): o canal de pedidos é UM por servidor, mora na seção `request` do
documento único e o painel e os comandos gravam o mesmo lugar; `?bot=` não escolhe documento; versão velha é 409; sem o store é 503."""

import asyncio
import re

from empiremuse.utils.servers import ServerConfigUnavailable
from tests.panel.helpers_channel import GID
from tests.panel.helpers_settings import CONFLICT_TEXT, acao_form
from tests.panel.test_channel_tasks import TasksBase


class CanalServidorTest(TasksBase):
    def test_the_page_is_the_servers_without_a_bot_selector_and_the_bot_query_is_ignored(self):
        self.world.configured_text()
        browser = self.logged_in()
        plain, with_bot = self.body(browser), self.body(browser, bot=2)
        assert "deste servidor" in plain and "Quem envia o painel e atende o canal é o" in plain
        assert not re.search(r'name="bot"|<select[^>]*bot', plain)
        form = lambda body: acao_form(body, "configurar").value("versao")  # noqa: E731
        assert form(plain) == form(with_bot)

    def test_setup_writes_the_server_document_and_leaves_the_bots_own_document_alone(self):
        bot_before = self.world.bot_doc
        self.run_setup(modo="existente", canal="22")

        request = self.world.request_doc
        assert request["channel"] == "22" and request["message_id"] and request["panel_bot_id"]
        assert self.world.bot_doc == bot_before  # nada em player_controller do documento por bot

    def test_the_command_side_sees_what_the_panel_set(self):  # S8: painel e comando gravam o mesmo documento
        self.run_setup(modo="existente", canal="22")
        config = self.io_loop.run_sync(lambda: self.pool.servers.request.get(GID))
        assert config.channel == 22 and config.message_id == int(self.world.request_doc["message_id"])
        view = self.io_loop.run_sync(lambda: self.pool.servers.legacy_doc(self.world.bot, GID))
        assert view["player_controller"]["channel"] == "22"

    def test_a_change_by_the_command_between_get_and_post_is_a_conflict_and_nothing_is_lost(self):
        browser = self.logged_in()
        form = self.setup_form(browser)
        self.world.configure("23", "1")  # o comando trocou o canal no meio
        before, writes = self.world.request_doc, len(self.db.writes)

        response = self.submit(browser, self.canal_url(), form, htmx=True, modo="existente", canal="22")

        assert response.code == 409 and CONFLICT_TEXT.split(".")[0] in response.body.decode().replace("&#39;", "'")
        assert self.world.request_doc == before and len(self.db.writes) == writes and list(self.world.j) == []

    def test_without_the_store_the_page_is_503_and_nothing_is_written(self):
        async def unavailable(gid):
            raise ServerConfigUnavailable

        browser = self.logged_in()
        self.pool.servers.request.get = unavailable
        assert browser.get(self.canal_url()).code == 503
        assert self.db.writes == [] and list(self.world.j) == []

    def test_reset_in_two_steps_clears_the_section_and_the_old_token_cannot_be_reused(self):
        self.world.configured_text()
        browser = self.logged_in()
        confirmation = self.reset_confirmation(browser)
        assert self.finish(browser, self.confirm_reset(browser, confirmation))[0] == "ok"
        assert self.world.request_doc["channel"] is None and self.world.request_doc["message_id"] is None

        self.world.configured_text()  # o canal volta; o token já foi gasto
        assert self.confirm_reset(browser, confirmation).code in (409, 422)
        assert self.world.request_doc["channel"] == "22"

    def test_two_simultaneous_setups_leave_one_consistent_channel(self):
        self.world.gate = asyncio.Event()
        browser = self.logged_in()
        first = self.start(browser, modo="existente", canal="22")
        assert first.code == 202
        self.world.gate.set()
        self.settle(0.2)
        request = self.world.request_doc
        assert request["channel"] == "22" and request["message_id"], "canal e mensagem sempre juntos"

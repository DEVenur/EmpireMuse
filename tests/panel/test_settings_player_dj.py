"""E4a — categorias Player (G-01…G-04) e DJ (G-05): leitura, escrita só dos campos do formulário, validações
contra o código dos comandos, escopo por bot e efeitos em memória."""

from tests.panel.helpers_settings import ROLE_IDS
from tests.panel.test_settings_http import HttpBase


class PlayerWriteTest(HttpBase):
    def test_post_writes_the_server_document_whatever_bot_the_url_names(self):
        browser = self.logged_in()
        bots_before = (self.db.doc("1", 800), self.db.doc("2", 800))
        response = self.save(browser, 800, "player", "default_player_volume", bot=2, default_player_volume="30")
        assert response.code == 200, f"status {response.code}"
        assert self.world.server_settings(800)["default_player_volume"] == 30
        assert (self.db.doc("1", 800), self.db.doc("2", 800)) == bots_before, "documentos por bot não são tocados"
        assert self.db.writes == [("servidor", 800)]

    def test_reaching_a_guild_with_no_document_yet_creates_it_with_the_defaults_and_the_change(self):
        browser = self.logged_in()
        self.world.database.servers.pop(200)
        self.pool.servers._docs.clear()
        response = self.save(browser, 200, "player", "default_player_volume", default_player_volume="75")
        assert response.code == 200
        doc = self.world.database.servers[200]
        assert doc["ver"] == 1.0 and doc["migrated"]["settings"] is True
        assert doc["settings"] == self.world.server_settings(200) | {"default_player_volume": 75}
        assert doc["settings"]["autoplay"] is False and doc["settings"]["djroles"] == []

    def test_panel_and_command_side_read_and_write_the_same_document(self):  # S8
        browser = self.logged_in()
        assert self.save(browser, 800, "player", "default_player_volume", default_player_volume="30").code == 200
        for bot in (
            self.world.bot1,
            self.world.bot2,
        ):  # o formato antigo (comandos) de qualquer bot vê a mudança do painel
            assert (
                self.io_loop.run_sync(lambda bot=bot: self.pool.servers.legacy_doc(bot, 800))["default_player_volume"]
                == 30
            )
        self.io_loop.run_sync(lambda: self.pool.servers.patch(800, "settings", {"default_player_volume": 45}))
        _, form, _ = self.open_form(browser, 800, "player", "default_player_volume")  # e o painel vê a do comando
        assert form.value("default_player_volume") == "45"


class PlayerEffectsTest(HttpBase):
    def test_failed_writes_have_no_side_effects(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert self.submit(browser, url, form, default_player_volume="7").code == 422
        self.world.external_server_change(100, autoplay=True)
        assert self.submit(browser, url, form, default_player_volume="30").code == 409
        assert self.world.p100.calls == [] and self.db.writes == []


# ============================================================================ DJ


class DjReadTest(HttpBase):
    def test_stale_ids_stored_for_deleted_roles_do_not_break_the_page(self):
        self.world.external_server_change(100, djroles=["5002", "999999999999"])
        response = self.logged_in().get(self.url(100, "dj"))
        assert response.code == 200 and "999999999999" not in response.body.decode()


class DjWriteTest(HttpBase):
    def save_roles(self, roles, gid=100, bot=None, **kw):
        return self.save(self.browser_cached(), gid, "dj", "djroles", bot=bot, djroles=roles, **kw)

    def browser_cached(self):
        if not hasattr(self, "_browser"):
            self._browser = self.logged_in()
        return self._browser

    def test_limit_is_25_per_submission(self):
        assert self.save_roles(ROLE_IDS[:25]).code == 200
        assert (
            sorted(self.world.server_settings(100)["djroles"]) == ROLE_IDS[:25]
        )  # a ordem segue as entradas, uma a uma
        before = self.world.server_settings(100)
        assert self.save_roles(ROLE_IDS[:26]).code == 422
        assert self.world.server_settings(100) == before

    def test_other_fields_in_the_post_are_ignored_and_no_player_effect_runs(self):
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        before, bot_before = self.world.server_settings(100), self.db.doc("1", 100)
        pairs = form.pairs(djroles=["5004"]) + [
            ("autoplay", "on"),
            ("default_player_volume", "5"),
            ("player_controller.skin", "neon"),
            ("ver", "9.9"),
        ]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.world.server_settings(100)
        for key in before.keys() - {"djroles"}:
            assert after[key] == before[key], key
        assert self.db.doc("1", 100) == bot_before
        assert self.world.p100.calls == [], "DJ não tem efeito em memória no player"

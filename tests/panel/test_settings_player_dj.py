"""E4a — categorias Player (G-01…G-04) e DJ (G-05): leitura, escrita só dos campos do formulário, validações
contra o código dos comandos, escopo por bot e efeitos em memória."""

from tests.panel.helpers_settings import ROLE_IDS, command_allowed_volumes, parse_forms
from tests.panel.test_settings_http import HttpBase, external_change


class PlayerReadTest(HttpBase):
    def test_volume_choices_are_exactly_the_command_set_when_the_control_is_a_select(self):
        _, form, _ = self.open_form(self.logged_in(), 100, "player", "default_player_volume")
        offered = form.choices("default_player_volume")
        if offered:  # <select>; um <input type=number> é validado só no POST
            assert {int(v) for v in offered} == command_allowed_volumes()


class PlayerWriteTest(HttpBase):
    def test_post_for_the_second_bot_changes_only_that_bots_document(self):
        browser = self.logged_in()
        before1 = self.db.doc("1", 800)
        response = self.save(browser, 800, "player", "default_player_volume", bot=2, default_player_volume="30")
        assert response.code == 200, f"status {response.code}"
        assert self.db.doc("2", 800)["default_player_volume"] == 30
        assert self.db.doc("1", 800) == before1
        assert self.db.writes == [("2", 800)]

    def test_422_message_sits_on_the_volume_field(self):
        browser = self.logged_in()
        response = self.save(browser, 100, "player", "default_player_volume", default_player_volume="7")
        form = next(f for f in parse_forms(response.body.decode()) if f.has("default_player_volume"))
        assert form.control("default_player_volume")["attrs"].get("aria-invalid") == "true"

    def test_reaching_a_guild_with_no_document_yet_creates_defaults_without_raising_ver(self):
        browser = self.logged_in()
        self.db.docs.pop(("2", 200))
        self.db.baseline.pop(("2", 200))
        response = self.save(browser, 200, "player", "default_player_volume", default_player_volume="75")
        assert response.code == 200
        ver = self.db.doc("2", 200)["ver"]
        from empiremuse.utils.db import DBModel, db_models

        assert ver == db_models[DBModel.guilds]["ver"], "o painel nunca sobe `ver` (KI-09)"


class PlayerEffectsTest(HttpBase):
    def test_failed_writes_have_no_side_effects(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert self.submit(browser, url, form, default_player_volume="7").code == 422
        external_change(self.db, "1", 100, autoplay=True)
        assert self.submit(browser, url, form, default_player_volume="30").code == 409
        assert self.world.p100.calls == [] and self.db.writes == []


# ============================================================================ DJ


class DjReadTest(HttpBase):
    def test_stale_ids_stored_for_deleted_roles_do_not_break_the_page(self):
        external_change(self.db, "1", 100, djroles=["5002", "999999999999"])
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
        assert len(self.db.doc("1", 100)["djroles"]) == 25
        before = self.db.doc("1", 100)
        assert self.save_roles(ROLE_IDS[:26]).code == 422
        assert self.db.doc("1", 100) == before

    def test_other_fields_in_the_post_are_ignored_and_no_player_effect_runs(self):
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        before = self.db.doc("1", 100)
        pairs = form.pairs(djroles=["5004"]) + [
            ("autoplay", "on"),
            ("default_player_volume", "5"),
            ("player_controller.skin", "neon"),
            ("ver", "9.9"),
        ]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("1", 100)
        for key in ("autoplay", "default_player_volume", "player_controller", "ver", "extra_flag"):
            assert after[key] == before[key], key
        assert self.world.p100.calls == [], "DJ não tem efeito em memória no player"

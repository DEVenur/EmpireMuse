"""E4a — categorias Player (G-01…G-04) e DJ (G-05): leitura, escrita só dos campos do formulário, validações
contra o código dos comandos, escopo por bot e efeitos em memória."""
import copy

from tests.panel.helpers_settings import HOSTILE_ROLE, ROLE_IDS, command_allowed_volumes, parse_forms
from tests.panel.test_settings_http import Each, HttpBase, external_change

PLAYER_FIELDS = ("default_player_volume", "autoplay", "check_other_bots_in_vc", "enable_restrict_mode")


class PlayerReadTest(HttpBase):
    def test_form_shows_the_current_values_of_the_chosen_bot(self):
        browser = self.logged_in()
        _, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert form.value("default_player_volume") == "100"
        assert not form.values("autoplay") and not form.values("check_other_bots_in_vc")
        assert not form.values("enable_restrict_mode")
        _, other, _ = self.open_form(browser, 800, "player", "default_player_volume")
        assert other.value("default_player_volume") == "60" and other.values("autoplay"), "bot 1 do servidor 800"
        _, second, _ = self.open_form(browser, 800, "player", "default_player_volume", bot=2)
        assert second.value("default_player_volume") == "80" and not second.values("autoplay")

    def test_volume_choices_are_exactly_the_command_set_when_the_control_is_a_select(self):
        _, form, _ = self.open_form(self.logged_in(), 100, "player", "default_player_volume")
        offered = form.choices("default_player_volume")
        if offered:  # <select>; um <input type=number> é validado só no POST
            assert {int(v) for v in offered} == command_allowed_volumes()

    def test_all_four_fields_live_in_one_form_posting_back_to_the_same_url(self):
        browser = self.logged_in()
        _, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert all(form.has(name) for name in PLAYER_FIELDS)
        assert form.method == "post"


class PlayerWriteTest(HttpBase):
    def test_valid_post_writes_only_the_four_player_fields(self):
        browser = self.logged_in()
        before = self.db.doc("1", 100)
        global_before = self.db.doc("global", 100)
        other_bot_before = self.db.doc("2", 800)
        response = self.save(browser, 100, "player", "default_player_volume", default_player_volume="50",
                             autoplay="on", check_other_bots_in_vc="on", enable_restrict_mode=None)
        assert response.code == 200, f"status {response.code}"
        expected = copy.deepcopy(before)
        expected.update({"default_player_volume": 50, "autoplay": True, "check_other_bots_in_vc": True,
                         "enable_restrict_mode": False})
        assert self.db.doc("1", 100) == expected, "demais campos, player_controller e ver devem ficar intactos"
        assert isinstance(self.db.doc("1", 100)["default_player_volume"], int)
        assert self.db.doc("global", 100) == global_before and self.db.doc("2", 800) == other_bot_before
        assert self.db.writes == [("1", 100)]

    def test_unchecked_boxes_mean_false(self):
        browser = self.logged_in()
        response = self.save(browser, 800, "player", "default_player_volume", autoplay=None)
        assert response.code == 200
        assert self.db.doc("1", 800)["autoplay"] is False

    def test_post_for_the_second_bot_changes_only_that_bots_document(self):
        browser = self.logged_in()
        before1 = self.db.doc("1", 800)
        response = self.save(browser, 800, "player", "default_player_volume", bot=2, default_player_volume="30")
        assert response.code == 200, f"status {response.code}"
        assert self.db.doc("2", 800)["default_player_volume"] == 30
        assert self.db.doc("1", 800) == before1
        assert self.db.writes == [("2", 800)]

    def test_volume_matches_the_command_set_exactly(self):
        browser = self.logged_in()
        allowed = command_allowed_volumes()
        accepted, rejected = [], []
        for volume in range(0, 201):
            url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
            before = self.db.doc("1", 100)
            response = self.submit(browser, url, form, default_player_volume=str(volume))
            (accepted if response.code == 200 else rejected).append((volume, response.code))
            if response.code != 200:
                assert self.db.doc("1", 100) == before, f"volume {volume} rejeitado não pode gravar"
        assert {v for v, _ in accepted} == allowed, (
            f"aceitos != conjunto do comando; a mais: {sorted({v for v, _ in accepted} - allowed)}, "
            f"a menos: {sorted(allowed - {v for v, _ in accepted})}")
        assert all(code == 422 for _, code in rejected), f"rejeição deve ser 422: {rejected[:5]}"

    def test_non_numeric_volumes_are_rejected_without_writing(self):
        browser = self.logged_in()
        before, writes = self.db.doc("1", 100), len(self.db.writes)

        def check(bad):
            url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
            response = self.submit(browser, url, form, default_player_volume=bad)
            assert response.code == 422, f"status {response.code}"

        Each.run(["abc", "", "50.0", "5e1", "-5", "٥٠", "9" * 30, "50 50", "<script>"], check)
        assert self.db.doc("1", 100) == before and len(self.db.writes) == writes

    def test_missing_volume_is_a_validation_error(self):
        browser = self.logged_in()
        response = self.save(browser, 100, "player", "default_player_volume", default_player_volume=None)
        assert response.code == 422 and self.db.writes == []

    def test_422_message_sits_on_the_volume_field(self):
        browser = self.logged_in()
        response = self.save(browser, 100, "player", "default_player_volume", default_player_volume="7")
        form = next(f for f in parse_forms(response.body.decode()) if f.has("default_player_volume"))
        assert form.control("default_player_volume")["attrs"].get("aria-invalid") == "true"

    def test_fields_of_other_forms_in_the_post_are_ignored(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        before = self.db.doc("1", 100)
        pairs = form.pairs(default_player_volume="40") + [
            ("djroles", "5020"), ("player_controller.channel", "1"), ("ver", "9.9"), ("prefix", "hack"),
            ("extra_flag", "mudou")]
        response = self.submit(browser, url, form, pairs=pairs)
        assert response.code in (200, 422), f"status {response.code}"
        after = self.db.doc("1", 100)
        for key in ("djroles", "player_controller", "ver", "extra_flag", "enable_prefixed_commands"):
            assert after[key] == before[key], f"campo fora do formulário foi alterado: {key}"
        assert self.db.doc("global", 100)["prefix"] == "!"

    def test_data_is_read_through_the_bot_with_int_ids_and_a_copy_is_written(self):
        # as violações do FakeDB (id não-int, mutar o cache, gravar o dict do cache) derrubam o tearDown
        browser = self.logged_in()
        assert self.save(browser, 100, "player", "default_player_volume", default_player_volume="45").code == 200
        assert self.db.violations == []

    def test_reaching_a_guild_with_no_document_yet_creates_defaults_without_raising_ver(self):
        browser = self.logged_in()
        self.db.docs.pop(("2", 200))
        self.db.baseline.pop(("2", 200))
        response = self.save(browser, 200, "player", "default_player_volume", default_player_volume="75")
        assert response.code == 200
        ver = self.db.doc("2", 200)["ver"]
        from utils.db import DBModel, db_models
        assert ver == db_models[DBModel.guilds]["ver"], "o painel nunca sobe `ver` (KI-09)"


class PlayerEffectsTest(HttpBase):
    def test_active_player_of_that_bot_saves_its_queue_after_the_database_write(self):
        browser = self.logged_in()
        self.events.clear()
        assert self.save(browser, 100, "player", "default_player_volume", default_player_volume="45").code == 200
        assert len(self.world.p100.called("process_save_queue")) == 1
        names = [e[:3] if e[0] == "db" else (e[0], e[1]) for e in self.events]
        assert names.index(("db", "update", "1")) < names.index(("p100/b1", "process_save_queue")), names

    def test_only_the_edited_bots_player_is_touched(self):
        browser = self.logged_in()
        assert self.save(browser, 800, "player", "default_player_volume", bot=2, default_player_volume="30").code == 200
        assert len(self.world.p800b.called("process_save_queue")) == 1
        assert self.world.p800a.calls == [], "o player do outro bot não é afetado"

    def test_guild_without_an_active_player_saves_normally(self):
        browser = self.logged_in()
        assert 200 not in self.world.bot2.music.players
        assert self.save(browser, 200, "player", "default_player_volume", default_player_volume="45").code == 200

    def test_failed_writes_have_no_side_effects(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "player", "default_player_volume")
        assert self.submit(browser, url, form, default_player_volume="7").code == 422
        external_change(self.db, "1", 100, autoplay=True)
        assert self.submit(browser, url, form, default_player_volume="30").code == 409
        assert self.world.p100.calls == [] and self.db.writes == []


# ============================================================================ DJ

class DjReadTest(HttpBase):
    def test_offers_every_role_but_everyone_and_marks_the_current_ones(self):
        browser = self.logged_in()
        _, form, response = self.open_form(browser, 100, "dj", "djroles")
        assert sorted(form.choices("djroles")) == sorted(ROLE_IDS), "todos os cargos existentes, sem @everyone"
        assert "100" not in form.choices("djroles")
        assert form.values("djroles") == ["5002"], "cargo atual marcado"
        _, bot2, _ = self.open_form(browser, 800, "dj", "djroles", bot=2)
        assert sorted(bot2.values("djroles")) == ["5004", "5005"]

    def test_role_names_from_discord_are_escaped(self):
        body = self.logged_in().get(self.url(100, "dj")).body.decode()
        assert HOSTILE_ROLE not in body and "&lt;img" in body

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

    def test_valid_post_replaces_only_djroles_with_string_ids(self):
        before = self.db.doc("1", 100)
        assert self.save_roles(["5003", "5001"]).code == 200
        expected = copy.deepcopy(before)
        expected["djroles"] = ["5003", "5001"]
        assert self.db.doc("1", 100) == expected
        assert all(isinstance(r, str) for r in self.db.doc("1", 100)["djroles"])
        assert self.db.writes == [("1", 100)]

    def test_empty_selection_clears_the_list(self):
        assert self.save_roles(None).code == 200
        assert self.db.doc("1", 100)["djroles"] == []

    def test_resaving_the_unchanged_form_keeps_the_stored_order(self):
        external_change(self.db, "1", 100, djroles=["5003", "5001", "5002"])
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        assert self.submit(browser, url, form).code == 200
        assert self.db.doc("1", 100)["djroles"] == ["5003", "5001", "5002"]

    def test_limit_is_25_per_submission(self):
        assert self.save_roles(ROLE_IDS[:25]).code == 200
        assert len(self.db.doc("1", 100)["djroles"]) == 25
        before = self.db.doc("1", 100)
        assert self.save_roles(ROLE_IDS[:26]).code == 422
        assert self.db.doc("1", 100) == before

    def test_invalid_ids_are_rejected_without_writing(self):
        before, writes = self.db.doc("1", 100), len(self.db.writes)
        cases = {
            "cargo inexistente": ["999999999999"], "@everyone (id do servidor)": ["100"], "não numérico": ["abc"],
            "dígitos árabes": ["٥٠٠١"], "espaço": ["5001 "], "negativo": ["-5001"],
            "decimal": ["5001.0"], "hexadecimal": ["0x1389"], "válido + inválido": ["5001", "abc"],
            "duplicado": ["5001", "5001"], "injeção": ["5001<script>"], "enorme": ["9" * 40],
        }

        def check(item):
            label, roles = item
            browser = self.browser_cached()
            url, form, _ = self.open_form(browser, 100, "dj", "djroles")
            response = self.submit(browser, url, form, djroles=roles)
            assert response.code == 422, f"status {response.code}"

        Each.run(list(cases.items()), check)
        assert self.db.doc("1", 100) == before and len(self.db.writes) == writes

    def test_role_missing_from_the_bots_cache_is_rejected(self):
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        self.world.g100.roles = [r for r in self.world.g100.roles if r.id != 5003]
        assert self.submit(browser, url, form, djroles=["5003"]).code == 422
        assert self.db.writes == []

    def test_second_bots_roles_are_independent(self):
        before1 = self.db.doc("1", 800)
        assert self.save_roles(["5010"], gid=800, bot=2).code == 200
        assert self.db.doc("2", 800)["djroles"] == ["5010"] and self.db.doc("1", 800) == before1

    def test_other_fields_in_the_post_are_ignored_and_no_player_effect_runs(self):
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        before = self.db.doc("1", 100)
        pairs = form.pairs(djroles=["5004"]) + [("autoplay", "on"), ("default_player_volume", "5"),
                                                ("player_controller.skin", "neon"), ("ver", "9.9")]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("1", 100)
        for key in ("autoplay", "default_player_volume", "player_controller", "ver", "extra_flag"):
            assert after[key] == before[key], key
        assert self.world.p100.calls == [], "DJ não tem efeito em memória no player"

    def test_422_message_sits_on_the_roles_field(self):
        browser = self.browser_cached()
        url, form, _ = self.open_form(browser, 100, "dj", "djroles")
        response = self.submit(browser, url, form, djroles=["abc"])
        body = response.body.decode()
        assert response.code == 422
        assert 'aria-invalid="true"' in body, "marcar o campo (ou o grupo) de cargos como inválido"

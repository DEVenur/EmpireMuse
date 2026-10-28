"""E4a — categorias Aparência (G-08…G-11) e Geral (G-12 prefixo, G-13 status do canal de voz): conjuntos de skins
do comando, skins personalizadas preservadas (S-04 privado), prefixo + cache do pool, placeholders do status de voz
e efeitos em memória. Regras extraídas do código em helpers_settings (command_*)."""

import copy

from tests.panel.helpers_settings import HOSTILE_SKIN, assentar, command_prefix_max_length
from tests.panel.test_settings_http import Each, HttpBase, external_change

CUSTOM = "> custom_skin: Meu<b>"


# ============================================================================ Aparência: leitura


class AppearanceReadTest(HttpBase):
    def test_ignore_lists_are_read_from_the_bot_config_at_request_time(self):
        browser = self.logged_in()
        self.world.config["IGNORE_SKINS"] = "neon dark"
        self.world.config["IGNORE_STATIC_SKINS"] = ""
        _, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert set(form.choices("skin")) == {"default", HOSTILE_SKIN}
        assert set(form.choices("static_skin")) == {"default", "green", "blue"}


# ============================================================================ Aparência: escrita por bot


class AppearanceBotWriteTest(HttpBase):
    def test_valid_post_writes_only_the_two_skin_keys_of_player_controller(self):
        browser = self.logged_in()
        before, global_before = self.db.doc("1", 100), self.db.doc("global", 100)
        response = self.save(browser, 100, "aparencia", "skin", skin="neon", static_skin="green")
        assert response.code == 200, f"status {response.code}"
        expected = copy.deepcopy(before)
        expected["player_controller"].update({"skin": "neon", "static_skin": "green"})
        assert self.db.doc("1", 100) == expected, "channel, message_id, fav_links, ver e demais campos intactos"
        assert self.db.doc("global", 100) == global_before and self.db.writes == [("1", 100)]

    def test_second_bot_is_independent(self):
        browser = self.logged_in()
        before1 = self.db.doc("1", 800)
        assert self.save(browser, 800, "aparencia", "skin", bot=2, skin="neon").code == 200
        assert self.db.doc("2", 800)["player_controller"]["skin"] == "neon" and self.db.doc("1", 800) == before1


class AppearanceBotEffectsTest(HttpBase):
    def test_static_player_reloads_only_when_the_static_skin_changes(self):
        browser = self.logged_in()
        self.world.p800a.static = True
        assert self.save(browser, 800, "aparencia", "skin", skin="neon").code == 200
        assert self.world.p800a.called("invoke_np") == [], "no modo song-request só static_skin conta (como o comando)"
        assert self.save(browser, 800, "aparencia", "skin", static_skin="green").code == 200
        assert self.world.p800a.called("invoke_np") == [{"force": True}]


# ============================================================================ Aparência: global


class AppearanceGlobalTest(HttpBase):
    def test_global_custom_skin_is_kept_when_not_changed(self):
        external_change(self.db, "global", 100, player_skin=CUSTOM)
        browser = self.logged_in()
        assert self.save(browser, 100, "aparencia", "global_skin", player_skin_static="green").code == 200
        assert self.db.doc("global", 100)["player_skin"] == CUSTOM

    def test_unchanged_global_form_reloads_nothing(self):
        browser = self.logged_in()
        assert self.save(browser, 800, "aparencia", "global_skin").code == 200
        assert self.world.p800a.calls == [] and self.world.p800b.calls == []


# ============================================================================ Geral: prefixo (G-12)


class PrefixTest(HttpBase):
    def test_length_limit_matches_the_command(self):
        limit = command_prefix_max_length()
        browser = self.logged_in()
        for ok in ("a" * limit, "😀" * limit, "?"):
            assert self.save(browser, 100, "geral", "prefix", prefix=ok).code == 200, ok
            assert self.db.doc("global", 100)["prefix"] == ok
        before = self.db.doc("global", 100)
        for bad in ("a" * (limit + 1), "😀" * (limit + 1), "a" * 500):
            assert self.save(browser, 100, "geral", "prefix", prefix=bad).code == 422, bad
        assert self.db.doc("global", 100) == before

    def test_other_global_fields_are_not_writable_from_this_form(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "geral", "prefix")
        before = self.db.doc("global", 100)
        pairs = form.pairs(prefix="$") + [
            ("custom_skins", "AAAA"),
            ("global_skin", "on"),
            ("listen_along_invites", "x"),
            ("ver", "9.9"),
        ]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("global", 100)
        for key in ("custom_skins", "global_skin", "listen_along_invites", "ver", "extra_flag"):
            assert after[key] == before[key], key


# ============================================================================ Geral: status do canal de voz (G-13)


class VoiceStatusTest(HttpBase):
    def test_text_without_a_valid_placeholder_is_rejected(self):
        browser = self.logged_in()
        before = self.db.doc("global", 100)

        def check(text):
            response = self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=text)
            assert response.code == 422, f"{text!r}: status {response.code}"

        Each.run(["Tocando agora", "{foo}", "{track.titulo}", "track.title", "{ track.title }", "{TRACK.TITLE}"], check)
        assert self.db.doc("global", 100) == before and self.db.writes == []

    def test_empty_status_uses_the_default_model_and_does_not_turn_the_feature_off(self):
        external_change(
            self.db, "global", 100, voice_channel_status="Tocando {track.title}", voice_status_permanent=True
        )
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status="").code == 200
        doc = self.db.doc("global", 100)
        assert doc["voice_channel_status"] == "" and doc["voice_status_permanent"] is True


class VoiceStatusEffectsTest(HttpBase):
    def test_empty_template_applies_the_default_model_to_the_player_without_touching_its_flag(self):
        external_change(
            self.db, "global", 100, voice_channel_status="Tocando {track.title}", voice_status_permanent=True
        )
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status="").code == 200
        self.io_loop.run_sync(assentar)  # o apply é uma tarefa por player
        player = self.world.p100
        (aplicacao,) = player.called("apply_permanent_voice_status")
        assert aplicacao["cfg"].permanent is True and aplicacao["cfg"].template.startswith("{track.emoji}")
        assert player.stage_title_event is False and player.called("update_stage_topic") == []

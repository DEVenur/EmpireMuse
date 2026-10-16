"""E4a — categorias Aparência (G-08…G-11) e Geral (G-12 prefixo, G-13 status do canal de voz): conjuntos de skins
do comando, skins personalizadas preservadas (S-04 privado), prefixo + cache do pool, placeholders do status de voz
e efeitos em memória. Regras extraídas do código em helpers_settings (command_*)."""
import copy

from tests.panel.helpers_settings import (HOSTILE_SKIN, command_prefix_max_length, command_voice_max_length,
                                          command_voice_placeholders, parse_forms)
from tests.panel.test_settings_http import Each, HttpBase, external_change

CUSTOM = "> custom_skin: Meu<b>"
CUSTOM_LABEL = "Personalizada (gerencie no Discord)"
LEGACY_SKIN_FIELDS = ("custom_skins", "custom_skins_static")


# ============================================================================ Aparência: leitura

class AppearanceReadTest(HttpBase):
    def test_two_independent_forms_each_with_its_own_version(self):
        browser = self.logged_in()
        _, per_bot, _ = self.open_form(browser, 100, "aparencia", "skin")
        _, glob, _ = self.open_form(browser, 100, "aparencia", "global_skin")
        assert per_bot is not glob and not per_bot.has("global_skin") and not glob.has("skin")
        assert per_bot.has("static_skin") and glob.has("player_skin") and glob.has("player_skin_static")
        assert per_bot.value("versao") and glob.value("versao")

    def test_choices_are_the_bots_skins_minus_the_ignore_lists(self):
        browser = self.logged_in()
        _, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert set(form.choices("skin")) == {"default", "neon", HOSTILE_SKIN}, "IGNORE_SKINS='dark'"
        assert set(form.choices("static_skin")) == {"default", "green"}, "IGNORE_STATIC_SKINS='blue'"
        assert form.value("skin") == "default" and form.value("static_skin") == "default"

    def test_ignore_lists_are_read_from_the_bot_config_at_request_time(self):
        browser = self.logged_in()
        self.world.config["IGNORE_SKINS"] = "neon dark"
        self.world.config["IGNORE_STATIC_SKINS"] = ""
        _, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert set(form.choices("skin")) == {"default", HOSTILE_SKIN}
        assert set(form.choices("static_skin")) == {"default", "green", "blue"}

    def test_global_form_offers_the_same_filtered_sets_plus_an_empty_default(self):
        _, form, _ = self.open_form(self.logged_in(), 100, "aparencia", "global_skin")
        assert {"default", "neon"} <= set(form.choices("player_skin")) and "dark" not in form.choices("player_skin")
        assert "blue" not in form.choices("player_skin_static") and "green" in form.choices("player_skin_static")
        assert "" in form.choices("player_skin") and "" in form.choices("player_skin_static"), "opção vazia = padrão"
        assert not form.values("global_skin")

    def test_skin_names_from_the_bot_are_escaped(self):
        body = self.logged_in().get(self.url(100, "aparencia")).body.decode()
        assert HOSTILE_SKIN not in body and "&lt;b&gt;hostil" in body

    def test_custom_skin_is_shown_as_a_label_and_never_leaks_its_data(self):
        external_change(self.db, "1", 100, player_controller={**self.db.doc("1", 100)["player_controller"],
                                                              "skin": CUSTOM})
        body = self.logged_in().get(self.url(100, "aparencia")).body.decode()
        assert CUSTOM_LABEL in body
        assert "Meu<b>" not in body, "nome da skin personalizada vem escapado"
        assert "DADOS-LEGADOS" not in body, "o painel não lê custom_skins (formato legado, S-04)"


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

    def test_invalid_names_are_rejected_without_writing(self):
        browser = self.logged_in()
        before = self.db.doc("1", 100)
        cases = {"inexistente": "nope", "ignorada": "dark", "markup": "<b>", "maiúscula": "Default",
                 "espaço": "default ", "traversal": "../neon", "vazia (decisão MAESTRO)": "", "prefixo custom forjado":
                 "> custom_skin: Forjada", "estática no campo normal": "green"}

        def check(item):
            label, value = item
            url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
            response = self.submit(browser, url, form, skin=value)
            assert response.code == 422, f"skin={value!r}: status {response.code}"

        Each.run(list(cases.items()), check)
        for value in ("", "nope", "blue", "neon", "> custom_skin: Forjada"):
            url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
            assert self.submit(browser, url, form, static_skin=value).code == 422, f"static_skin={value!r}"
        assert self.db.doc("1", 100) == before and self.db.writes == []

    def test_custom_skin_is_kept_when_not_changed_and_replaceable_by_a_listed_skin(self):
        external_change(self.db, "1", 100, player_controller={**self.db.doc("1", 100)["player_controller"],
                                                              "skin": CUSTOM})
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert self.submit(browser, url, form, static_skin="green").code == 200
        assert self.db.doc("1", 100)["player_controller"]["skin"] == CUSTOM, "personalizada mantida"
        assert self.db.doc("1", 100)["player_controller"]["static_skin"] == "green"
        url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert self.submit(browser, url, form, skin="neon").code == 200
        assert self.db.doc("1", 100)["player_controller"]["skin"] == "neon"

    def test_a_custom_skin_name_is_accepted_only_if_it_is_the_one_already_stored(self):
        external_change(self.db, "1", 100, player_controller={**self.db.doc("1", 100)["player_controller"],
                                                              "skin": CUSTOM})
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert self.submit(browser, url, form, skin=CUSTOM).code == 200, "reenviar o valor atual não é troca"
        url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        assert self.submit(browser, url, form, skin="> custom_skin: Outra").code == 422

    def test_second_bot_is_independent(self):
        browser = self.logged_in()
        before1 = self.db.doc("1", 800)
        assert self.save(browser, 800, "aparencia", "skin", bot=2, skin="neon").code == 200
        assert self.db.doc("2", 800)["player_controller"]["skin"] == "neon" and self.db.doc("1", 800) == before1

    def test_legacy_skin_data_cannot_be_written_through_the_form(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "aparencia", "skin")
        before = self.db.doc("global", 100)
        pairs = form.pairs(skin="neon") + [("custom_skins", "AAAA"), ("custom_skins_static", "BBBB"),
                                           ("global_skin", "on"), ("prefix", "hack")]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        assert self.db.doc("global", 100) == before, "nada do documento global muda pelo formulário por bot"


class AppearanceBotEffectsTest(HttpBase):
    def test_active_players_reload_the_skin_like_the_command_does(self):
        browser = self.logged_in()
        self.events.clear()
        assert self.save(browser, 800, "aparencia", "skin", skin="neon", static_skin="green").code == 200
        player = self.world.p800a
        assert (player.skin, player.skin_static) == ("neon", "green")
        for step in ("destroy_message", "setup_features", "setup_hints", "process_hint"):
            assert player.called(step), f"falta {step}"
        assert player.called("invoke_np") == [{"force": True}]
        assert self.world.p800b.calls == [], "skin por bot não mexe no player do outro bot"

    def test_unchanged_skin_does_not_reload(self):
        browser = self.logged_in()
        assert self.save(browser, 800, "aparencia", "skin").code == 200
        assert self.world.p800a.calls == []

    def test_static_player_reloads_only_when_the_static_skin_changes(self):
        browser = self.logged_in()
        self.world.p800a.static = True
        assert self.save(browser, 800, "aparencia", "skin", skin="neon").code == 200
        assert self.world.p800a.called("invoke_np") == [], "no modo song-request só static_skin conta (como o comando)"
        assert self.save(browser, 800, "aparencia", "skin", static_skin="green").code == 200
        assert self.world.p800a.called("invoke_np") == [{"force": True}]

    def test_failed_writes_do_not_reload_anything(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 800, "aparencia", "skin")
        assert self.submit(browser, url, form, skin="nope").code == 422
        assert self.submit(browser, url, form, versao="0" * 16, skin="neon").code == 409
        assert self.world.p800a.calls == [] and self.db.writes == []


# ============================================================================ Aparência: global

class AppearanceGlobalTest(HttpBase):
    def test_valid_post_writes_only_the_three_global_skin_fields(self):
        browser = self.logged_in()
        before = self.db.doc("global", 100)
        bot_before = self.db.doc("1", 100)
        response = self.save(browser, 100, "aparencia", "global_skin", global_skin="on", player_skin="neon",
                             player_skin_static="green")
        assert response.code == 200, f"status {response.code}"
        expected = copy.deepcopy(before)
        expected.update({"global_skin": True, "player_skin": "neon", "player_skin_static": "green"})
        assert self.db.doc("global", 100) == expected, "custom_skins*, listen_along_invites, prefix, ver intactos"
        assert self.db.doc("global", 100)["custom_skins"] == {"meu": "DADOS-LEGADOS"}
        assert self.db.doc("1", 100) == bot_before and self.db.writes == [("global", 100)]

    def test_empty_names_mean_the_pool_default_and_unchecked_means_off(self):
        browser = self.logged_in()
        external_change(self.db, "global", 100, global_skin=True, player_skin="neon", player_skin_static="green")
        assert self.save(browser, 100, "aparencia", "global_skin", global_skin=None, player_skin="",
                         player_skin_static="").code == 200
        doc = self.db.doc("global", 100)
        assert doc["global_skin"] is False and doc["player_skin"] is None and doc["player_skin_static"] is None

    def test_invalid_global_names_are_rejected(self):
        browser = self.logged_in()
        before = self.db.doc("global", 100)

        def check(item):
            field, value = item
            url, form, _ = self.open_form(browser, 100, "aparencia", "global_skin")
            response = self.submit(browser, url, form, **{field: value})
            assert response.code == 422, f"{field}={value!r}: status {response.code}"

        Each.run([("player_skin", "nope"), ("player_skin", "dark"), ("player_skin", "<b>"),
                  ("player_skin_static", "blue"), ("player_skin_static", "neon"),
                  ("player_skin_static", "> custom_skin: Forjada")], check)
        assert self.db.doc("global", 100) == before and self.db.writes == []

    def test_global_custom_skin_is_kept_when_not_changed(self):
        external_change(self.db, "global", 100, player_skin=CUSTOM)
        browser = self.logged_in()
        assert self.save(browser, 100, "aparencia", "global_skin", player_skin_static="green").code == 200
        assert self.db.doc("global", 100)["player_skin"] == CUSTOM

    def test_legacy_skin_fields_in_the_post_are_ignored(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "aparencia", "global_skin")
        pairs = form.pairs(player_skin="neon") + [("custom_skins", "AAAA"), ("custom_skins_static", "BBBB"),
                                                  ("listen_along_invites", "x"), ("ver", "9.9")]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        doc = self.db.doc("global", 100)
        assert doc["custom_skins"] == {"meu": "DADOS-LEGADOS"} and doc["custom_skins_static"] == {}
        assert doc["listen_along_invites"] == {"123": "https://discord.gg/abc"} and doc["ver"] == 1.4

    def test_global_save_reloads_the_players_of_every_bot_in_the_guild(self):
        browser = self.logged_in()
        assert self.save(browser, 800, "aparencia", "global_skin", global_skin="on", player_skin="neon",
                         player_skin_static="green").code == 200
        for player in (self.world.p800a, self.world.p800b):
            assert (player.skin, player.skin_static) == ("neon", "green"), player.label
            assert player.called("invoke_np") == [{"force": True}] and player.called("setup_features")

    def test_turning_global_off_puts_each_bot_back_on_its_own_skin(self):
        external_change(self.db, "global", 800, global_skin=True, player_skin="neon", player_skin_static="green")
        for player in (self.world.p800a, self.world.p800b):
            player.skin, player.skin_static = "neon", "green"
        browser = self.logged_in()
        assert self.save(browser, 800, "aparencia", "global_skin", global_skin=None).code == 200
        for player in (self.world.p800a, self.world.p800b):
            assert (player.skin, player.skin_static) == ("default", "default"), player.label
            assert player.called("invoke_np") == [{"force": True}]

    def test_unchanged_global_form_reloads_nothing(self):
        browser = self.logged_in()
        assert self.save(browser, 800, "aparencia", "global_skin").code == 200
        assert self.world.p800a.calls == [] and self.world.p800b.calls == []


# ============================================================================ Geral: prefixo (G-12)

class PrefixTest(HttpBase):
    def test_form_shows_the_current_prefix(self):
        _, form, _ = self.open_form(self.logged_in(), 100, "geral", "prefix")
        assert form.value("prefix") == "!"

    def test_valid_prefix_is_saved_globally_and_updates_the_pool_cache_with_an_int_key(self):
        browser = self.logged_in()
        before, bots_before = self.db.doc("global", 800), (self.db.doc("1", 800), self.db.doc("2", 800))
        response = self.save(browser, 800, "geral", "prefix", prefix=">>")
        assert response.code == 200, f"status {response.code}"
        expected = copy.deepcopy(before)
        expected["prefix"] = ">>"
        assert self.db.doc("global", 800) == expected
        assert self.pool.guild_prefix_cache == {800: ">>"}, "chave int do servidor editado (sem o bug de legacy_cmds:714)"
        assert (self.db.doc("1", 800), self.db.doc("2", 800)) == bots_before
        assert self.db.writes == [("global", 800)]

    def test_empty_prefix_resets_to_default_like_resetprefix(self):
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "prefix", prefix="").code == 200
        assert self.db.doc("global", 100)["prefix"] == ""
        assert self.pool.guild_prefix_cache == {100: ""}, "resetprefix grava '' no cache"

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

    def test_spaces_and_control_characters_are_rejected(self):
        browser = self.logged_in()
        before, writes = self.db.doc("global", 100), len(self.db.writes)

        def check(bad):
            assert self.save(browser, 100, "geral", "prefix", prefix=bad).code == 422

        Each.run(["a b", "a\tb", "a\nb", "a\r", "a\x00"], check)
        assert self.db.doc("global", 100) == before and len(self.db.writes) == writes

    def test_rejected_prefix_leaves_the_cache_alone(self):
        browser = self.logged_in()
        self.pool.guild_prefix_cache[100] = "!"
        assert self.save(browser, 100, "geral", "prefix", prefix="a b").code == 422
        url, form, _ = self.open_form(browser, 100, "geral", "prefix")
        external_change(self.db, "global", 100, prefix="?")
        assert self.submit(browser, url, form, prefix="$").code == 409
        assert self.pool.guild_prefix_cache == {100: "!"}

    def test_prefix_is_html_escaped_in_the_attribute(self):
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "prefix", prefix='"><x').code == 200
        response = browser.get(self.url(100, "geral"))
        body = response.body.decode()
        assert '"><x' not in body, "aspas e < sem escape quebrariam o atributo"
        form = next(f for f in parse_forms(body) if f.has("prefix"))
        assert form.value("prefix") == '"><x'

    def test_other_global_fields_are_not_writable_from_this_form(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "geral", "prefix")
        before = self.db.doc("global", 100)
        pairs = form.pairs(prefix="$") + [("custom_skins", "AAAA"), ("global_skin", "on"),
                                          ("listen_along_invites", "x"), ("ver", "9.9")]
        assert self.submit(browser, url, form, pairs=pairs).code in (200, 422)
        after = self.db.doc("global", 100)
        for key in ("custom_skins", "global_skin", "listen_along_invites", "ver", "extra_flag"):
            assert after[key] == before[key], key

    def test_prefix_save_has_no_player_effect(self):
        assert self.save(self.logged_in(), 100, "geral", "prefix", prefix="$").code == 200
        assert self.world.p100.calls == []


# ============================================================================ Geral: status do canal de voz (G-13)

class VoiceStatusTest(HttpBase):
    def test_form_is_a_text_area_with_the_current_template(self):
        external_change(self.db, "global", 100, voice_channel_status="Tocando {track.title}")
        _, form, _ = self.open_form(self.logged_in(), 100, "geral", "voice_channel_status")
        assert form.value("voice_channel_status") == "Tocando {track.title}"

    def test_each_command_placeholder_is_accepted_alone(self):
        browser = self.logged_in()
        placeholders = command_voice_placeholders()
        assert len(placeholders) == 9

        def check(placeholder):
            response = self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=placeholder)
            assert response.code == 200, f"status {response.code}"
            assert self.db.doc("global", 100)["voice_channel_status"] == placeholder

        Each.run(list(placeholders), check)

    def test_text_without_a_valid_placeholder_is_rejected(self):
        browser = self.logged_in()
        before = self.db.doc("global", 100)

        def check(text):
            response = self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=text)
            assert response.code == 422, f"{text!r}: status {response.code}"

        Each.run(["Tocando agora", "{foo}", "{track.titulo}", "track.title", "{ track.title }", "{TRACK.TITLE}"],
                 check)
        assert self.db.doc("global", 100) == before and self.db.writes == []

    def test_valid_placeholder_next_to_unknown_braces_is_accepted_like_the_command(self):
        browser = self.logged_in()
        text = "{foo} - {track.title}"
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=text).code == 200
        assert self.db.doc("global", 100)["voice_channel_status"] == text

    def test_line_breaks_become_spaces_and_the_text_is_stripped(self):
        browser = self.logged_in()
        text = "\n  Agora:\n{track.title}\n"
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=text).code == 200
        assert self.db.doc("global", 100)["voice_channel_status"] == "Agora: {track.title}"

    def test_length_limit_matches_the_command_modal(self):
        limit = max(command_voice_max_length())
        browser = self.logged_in()
        emoji = "{track.emoji}"  # expande para 1 caractere: no limite nem a regra "após expandir" estoura
        ok = "x" * (limit - len(emoji)) + emoji
        assert len(ok) == limit
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=ok).code == 200
        too_long = "x" * (limit + 1 - len(emoji)) + emoji
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=too_long).code == 422
        assert self.db.doc("global", 100)["voice_channel_status"] == ok

    def test_empty_status_turns_the_feature_off(self):
        external_change(self.db, "global", 100, voice_channel_status="Tocando {track.title}")
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status="").code == 200
        assert self.db.doc("global", 100)["voice_channel_status"] == ""

    def test_template_is_escaped_in_the_page(self):
        browser = self.logged_in()
        text = "</textarea><script>alert(1)</script> {track.title}"
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status=text).code == 200
        body = browser.get(self.url(100, "geral")).body.decode()
        assert "</textarea><script>" not in body and "<script>alert(1)" not in body
        form = next(f for f in parse_forms(body) if f.has("voice_channel_status"))
        assert form.value("voice_channel_status") == text

    def test_only_the_global_document_is_written(self):
        browser = self.logged_in()
        before = (self.db.doc("1", 800), self.db.doc("2", 800))
        assert self.save(browser, 800, "geral", "voice_channel_status",
                         voice_channel_status="{track.title}").code == 200
        assert (self.db.doc("1", 800), self.db.doc("2", 800)) == before
        assert self.db.writes == [("global", 800)]


class VoiceStatusEffectsTest(HttpBase):
    def test_every_active_player_of_the_guild_gets_the_new_template_after_the_write(self):
        browser = self.logged_in()
        self.events.clear()
        text = "Tocando {track.title}"
        assert self.save(browser, 800, "geral", "voice_channel_status", voice_channel_status=text).code == 200
        for player in (self.world.p800a, self.world.p800b):
            assert player.stage_title_event is True and player.stage_title_template == text, player.label
            assert player.update is True and player.called("set_command_log")
            assert player.called("update_stage_topic") == [{"clear": False}]
            assert len(player.called("process_save_queue")) == 1
        assert self.world.p100.calls == [], "player de outro servidor não é tocado"
        order = [e[:3] if e[0] == "db" else (e[0], e[1]) for e in self.events]
        assert order.index(("db", "update", "global")) < order.index(("p800/b1", "update_stage_topic")), order

    def test_empty_template_disables_and_clears_the_status(self):
        external_change(self.db, "global", 100, voice_channel_status="Tocando {track.title}")
        self.world.p100.stage_title_event = True
        browser = self.logged_in()
        assert self.save(browser, 100, "geral", "voice_channel_status", voice_channel_status="").code == 200
        player = self.world.p100
        assert player.stage_title_event is False and player.stage_title_template == ""
        assert player.called("update_stage_topic") == [{"clear": True}]
        assert len(player.called("process_save_queue")) == 1

    def test_rejected_or_conflicting_saves_touch_no_player(self):
        browser = self.logged_in()
        url, form, _ = self.open_form(browser, 100, "geral", "voice_channel_status")
        assert self.submit(browser, url, form, voice_channel_status="sem placeholder").code == 422
        external_change(self.db, "global", 100, voice_channel_status="{track.author}")
        assert self.submit(browser, url, form, voice_channel_status="{track.title}").code == 409
        assert self.world.p100.calls == []

    def test_guild_without_players_saves_normally(self):
        assert self.save(self.logged_in(), 200, "geral", "voice_channel_status",
                         voice_channel_status="{track.title}").code == 200

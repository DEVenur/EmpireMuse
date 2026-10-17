"""E5 — caracterização (VERDE desde já) das regras da conta, extraídas do CÓDIGO dos comandos. Se um comando mudar,
estes testes avisam que o painel (panel/services/account.py) precisa acompanhar — e o contrário.
"""

import re

from tests.panel.helpers import ROOT

LEGACY = (ROOT / "modules/legacy_cmds.py").read_text(encoding="utf-8")
INTERACTIONS = (ROOT / "utils/music/interactions.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "modules/music_settings.py").read_text(encoding="utf-8")
LASTFM = (ROOT / "modules/lastfm.py").read_text(encoding="utf-8")
MUSIC = (ROOT / "modules/music.py").read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


def block(source, start, end):
    return source[source.index(start) : source.index(end, source.index(start))]


class TestUserPrefixRules:
    def test_set_user_prefix_limit_strip_and_cache_key(self):
        code = block(LEGACY, "async def setuserprefix", "async def resetuserprefix")
        assert "prefix = prefix.strip()" in code and "len(prefix) > 5" in code
        assert "self.bot.pool.user_prefix_cache[ctx.author.id] = prefix" in code, "chave = id INT do usuário"
        assert 'user_data["custom_prefix"] = prefix' in code

    def test_reset_user_prefix_writes_empty_string_in_field_and_cache(self):
        code = block(LEGACY, "async def resetuserprefix", "async def setguildprefix")
        assert 'user_data["custom_prefix"] = ""' in code
        assert 'self.bot.pool.user_prefix_cache[ctx.author.id] = ""' in code

    def test_cache_is_read_with_the_same_int_key(self):
        source = (ROOT / "utils/db.py").read_text(encoding="utf-8")
        assert "bot.pool.user_prefix_cache[message.author.id]" in source


class TestFavoritesRules:
    def test_config_defaults(self):
        import config_loader

        cfg = config_loader.DEFAULT_CONFIG
        assert (
            cfg["MAX_USER_FAVS"],
            cfg["USER_FAV_MAX_NAME_LENGTH"],
            cfg["USER_FAV_MAX_URL_LENGTH"],
            cfg["MAX_USER_INTEGRATIONS"],
        ) == (10, 35, 90, 10)

    def test_add_modal_limits_and_extraction(self):
        code = flat(block(INTERACTIONS, "class FavModalAdd", "class FavMenuView"))
        assert re.search(r'custom_id="user_fav_name", min_length=2, max_length=25', code)
        assert re.search(r'custom_id="user_fav_url", min_length=10, max_length=200', code)
        assert "valid_url = URL_REG.findall(url)[0]" in code
        assert 'self.view.data["fav_links"][name] = valid_url' in code, "valor = URL em texto"

    def test_add_modal_limit_check_has_no_zero_or_owner_exemption_but_the_other_paths_do(self):
        modal = flat(INTERACTIONS)
        assert 'if len(self.view.data["fav_links"]) >= self.view.bot.config["MAX_USER_FAVS"]:' in modal
        assert 'self.bot.config["MAX_USER_FAVS"] > 0 and not (await self.bot.is_owner(interaction.author))' in flat(
            MUSIC
        )
        assert 'self.view.bot.config["MAX_USER_FAVS"] > 0 and not (await self.view.bot.is_owner(inter.author))' in modal

    def test_import_rules(self):
        code = flat(
            block(
                INTERACTIONS,
                "if self.view.mode == ViewMode.fav_manager:\n            if retry_after",
                "elif self.view.mode == ViewMode.guild_fav_manager:\n            if retry_after",
            )
        )
        assert 'if "> fav:" in name.lower(): continue' in code, "quirk: pula a validação de nomes '> fav:'"
        assert 'len(url) > (max_url_chars := self.view.bot.config["USER_FAV_MAX_URL_LENGTH"])' in code
        assert "not URL_REG.match(url)" in code
        assert 'len(name) > (max_name_chars := self.view.bot.config["USER_FAV_MAX_NAME_LENGTH"])' in code
        assert 'self.view.data["fav_links"].update(json_data)' in code
        assert '(json_size := len(json_data)) > self.view.bot.config["MAX_USER_FAVS"]' in code

    def test_export_is_the_stored_dict_dumped_as_json(self):
        code = flat(INTERACTIONS)
        assert 'json.dumps(self.data["fav_links"], indent=4)' in code and 'filename="favoritos.json"' in code


class TestIntegrationsRules:
    def test_import_rules(self):
        start = INTERACTIONS.index("elif self.view.mode == ViewMode.integrations_manager:\n            if retry_after")
        code = flat(INTERACTIONS[start : start + 3500])
        assert 'if "> itg:" in name.lower(): continue' in code
        assert "max_url_chars := 150" in code and "not URL_REG.match(url)" in code
        assert 'del self.view.data["integration_links"][name.lower()[:90]]' in code
        assert (
            'self.view.bot.config["MAX_USER_INTEGRATIONS"] > 0 and not (await self.view.bot.is_owner(inter.author))'
            in code
        )
        assert 'self.view.data["integration_links"].update(json_data)' in code

    def test_stored_shape_of_added_integrations_is_an_object_with_url_and_optional_avatar(self):
        code = flat(INTERACTIONS)
        assert (
            '"avatar": result["images"][-1]["url"]' in code or '"avatar": result["images"][-1][\'url\']' in code
        ) and '"url": result["external_urls"]["spotify"]' in code

    def test_remove_deletes_by_exact_title(self):
        assert 'del self.data["integration_links"][self.current]' in flat(INTERACTIONS)


class TestLastFmRules:
    def test_toggle_exists_only_with_a_session_key_and_writes_only_the_scrobble_flag(self):
        assert re.search(r"def build_components\(self\):\s+if self\.session_key:", LASTFM)
        assert 'user_data["lastfm"]["scrobble"] = self.scrobble_enabled' in LASTFM
        assert "CooldownMapping.from_cooldown(1, 7, commands.BucketType.user)" in flat(LASTFM)

    def test_scrobbling_needs_the_flag_and_a_session_key(self):
        assert 'if fminfo["scrobble"] is False or not fminfo["sessionkey"]:' in flat(LASTFM)


class TestRpcTokenRules:
    def test_command_availability_condition(self):
        code = flat(SETTINGS)
        assert (
            'if not self.bot.config["ENABLE_RPC_COMMAND"] and not any(' in code
            and "[await b.is_owner(inter.author) for b in self.bot.pool.get_guild_bots(inter.guild_id)]" in code
        )
        assert 'if not self.bot.config["RPC_PUBLIC_URL"] and not self.bot.config["RPC_SERVER"]:' in code
        assert 'if self.bot.config["ENABLE_RPC_AUTH"]:' in code, "botões de token só com ENABLE_RPC_AUTH"

    def test_generated_token_format_is_50_letters_and_digits(self):
        code = flat(SETTINGS)
        assert 'data["token"] = "".join(random.choice(string.ascii_letters + string.digits) for i in range(50))' in code
        assert "min_length=50, max_length=50" in code

    def test_replacing_or_removing_a_token_closes_the_active_presence_first(self):
        gen = flat(block(SETTINGS, 'if button_id == "rpc_gen":', 'elif button_id == "rpc_create":'))
        assert 'if data["token"]: await self.close_presence(inter)' in gen
        assert gen.index("close_presence") < gen.index('data["token"] = "".join')
        modal = flat(block(SETTINGS, "async def rpc_create_modal", "@commands.cooldown(1, 5"))
        assert modal.index("close_presence") < modal.index('data["token"] = inter.text_values["token_input"]')

    def test_close_presence_sends_op_close_to_players_where_the_user_is_in_voice(self):
        code = flat(block(SETTINGS, "async def close_presence", "def setup(bot"))
        assert "inter.author.id not in player.guild.me.voice.channel.voice_states" in code
        assert '"op": "close"' in code and "await player._send_rpc_data([inter.author.id], stats)" in code

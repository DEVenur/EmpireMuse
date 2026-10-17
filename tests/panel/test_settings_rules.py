"""E4a — caracterização: as regras que o painel espelha, extraídas do CÓDIGO dos comandos (não do briefing),
mais a sanidade dos dublês (FakeDB e parser de formulário). Estes testes ficam verdes desde já: são a âncora que
detecta se um comando mudar e o painel ficar para trás (ou o contrário).
"""

import asyncio

from tests.panel.helpers import ROOT
from tests.panel.helpers_settings import (
    SettingsWorld,
    command_allowed_volumes,
    command_prefix_max_length,
    command_voice_max_length,
    command_voice_placeholders,
    command_volume_ranges,
    parse_forms,
    version_of,
)

LEGACY = (ROOT / "empiremuse/cogs/legacy_cmds.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "empiremuse/cogs/music_settings.py").read_text(encoding="utf-8")
INTERACTIONS = (ROOT / "empiremuse/utils/music/interactions.py").read_text(encoding="utf-8")


class TestCommandRules:
    def test_volume_set_is_5_to_100_step_5_and_110_to_150_step_10(self):
        assert command_volume_ranges() == [(5, 101, 5), (110, 151, 10)]
        allowed = command_allowed_volumes()
        assert len(allowed) == 25 and min(allowed) == 5 and max(allowed) == 150
        assert 105 not in allowed and 100 in allowed and 110 in allowed and 0 not in allowed

    def test_voice_status_placeholders_are_the_nine_of_the_command(self):
        assert set(command_voice_placeholders()) == {
            "{track.title}",
            "{track.timestamp}",
            "{track.emoji}",
            "{track.author}",
            "{track.duration}",
            "{track.source}",
            "{track.playlist}",
            "{requester.name}",
            "{requester.id}",
        }

    def test_voice_status_modal_limit_is_496_and_at_least_one_placeholder_is_required(self):
        assert command_voice_max_length() == {496}
        flat = " ".join(INTERACTIONS.split())
        assert (
            'not any(p in values["status_voice_value"] for p in self.placeholders)' in flat
            or 'not any( p in values["status_voice_value"] for p in self.placeholders)' in flat
        )
        assert '.replace("\\n", " ").strip()' in INTERACTIONS, "o comando troca quebras de linha por espaço"

    def test_prefix_limit_is_five_and_reset_stores_empty_in_the_pool_cache_with_an_int_key(self):
        assert command_prefix_max_length() == 5
        assert "prefix = prefix.strip()" in LEGACY
        assert "self.bot.pool.guild_prefix_cache[ctx.guild.id] = prefix" in LEGACY
        assert 'self.bot.pool.guild_prefix_cache[ctx.guild.id] = ""' in LEGACY

    def test_skin_choices_exclude_the_ignore_lists_read_from_bot_config(self):
        assert '[s for s in bot.player_skins if s not in bot.config["IGNORE_SKINS"].split()]' in SETTINGS
        assert '[s for s in bot.player_static_skins if s not in bot.config["IGNORE_STATIC_SKINS"].split()]' in SETTINGS
        assert "> custom_skin: " in SETTINGS

    def test_dj_roles_are_string_ids_and_everyone_is_refused(self):
        assert "if role == guild.default_role:" in SETTINGS
        assert (
            "str(role.id) in guild_data['djroles']" in SETTINGS or 'str(role.id) in guild_data["djroles"]' in SETTINGS
        )
        assert (
            "guild_data['djroles'].append(str(role.id))" in SETTINGS
            or 'guild_data["djroles"].append(str(role.id))' in SETTINGS
        )

    def test_models_hold_the_fields_the_panel_writes(self):
        from empiremuse.utils.db import DBModel, db_models, global_db_models

        guild = db_models[DBModel.guilds]
        assert {
            "autoplay",
            "check_other_bots_in_vc",
            "enable_restrict_mode",
            "default_player_volume",
            "djroles",
            "ver",
        } <= set(guild)
        assert {"skin", "static_skin"} <= set(guild["player_controller"])
        globals_ = global_db_models[DBModel.guilds]
        assert {"prefix", "global_skin", "player_skin", "player_skin_static", "voice_channel_status", "ver"} <= set(
            globals_
        )


class TestDoublesSanity:
    def test_fake_db_flags_in_place_mutation_and_writing_the_cache_object(self):
        world = SettingsWorld()
        db = world.db

        async def scenario():
            cached = await db.get("1", 100, "guilds")
            cached["autoplay"] = True  # mutou o cache sem gravar
            await db.update("1", 100, cached, "guilds")  # e gravou o próprio objeto
            return db.violations

        violations = asyncio.run(scenario())
        assert any("próprio dict do cache" in v for v in violations)
        assert any("mutado" in v for v in violations)

    def test_fake_db_accepts_the_copy_then_write_pattern_and_checks_id_type(self):
        world = SettingsWorld()
        db = world.db

        async def scenario():
            import copy

            data = copy.deepcopy(await db.get("1", 100, "guilds"))
            data["autoplay"] = True
            await db.update("1", 100, data, "guilds")
            await db.get("1", "100", "guilds")

        asyncio.run(scenario())
        assert db.doc("1", 100)["autoplay"] is True
        assert db.violations == ["id do servidor deve ser int, veio '100'"]

    def test_form_parser_follows_browser_semantics(self):
        html = (
            '<form action="/x" method="post"><input type="hidden" name="_xsrf" value="t">'
            '<input type="checkbox" name="a" checked><input type="checkbox" name="b">'
            '<select name="v"><option value="1">1</option><option value="2" selected>2</option></select>'
            '<select name="m" multiple><option value="x" selected>x</option><option value="y" selected>y</option>'
            '</select><textarea name="t">\nolá</textarea><button>ok</button></form>'
        )
        form = parse_forms(html)[0]
        assert form.pairs() == [("_xsrf", "t"), ("a", "on"), ("v", "2"), ("m", "x"), ("m", "y"), ("t", "olá")]
        assert form.pairs(a=None, m=["z"]) == [("_xsrf", "t"), ("v", "2"), ("t", "olá"), ("m", "z")]

    def test_version_formula_is_sha256_of_canonical_json_first_16_hex(self):
        assert version_of({"b": 1, "a": 2}) == version_of({"a": 2, "b": 1})
        assert len(version_of({"a": 1})) == 16 and version_of({"a": 1}) != version_of({"a": 2})
        assert version_of({"a": 1}) == "015abd7f5cc57a2d"  # sha256('{"a":1}')[:16]

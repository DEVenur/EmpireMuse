"""E4a — caracterização: as regras que o painel espelha, medidas no COMPORTAMENTO dos comandos (callbacks reais com
dublês, nunca lendo o texto do código-fonte), mais a sanidade dos dublês (FakeDB e parser de formulário). Estes testes
ficam verdes desde já: são a âncora que detecta se um comando mudar e o painel ficar para trás (ou o contrário).
"""

import asyncio

import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
from empiremuse.utils.db import DBModel
from tests.support.drivers_de_regras import (
    BotDeComandos,
    CargoFalso,
    GuildaFalsa,
    abrir_modal_do_status_permanente,
    comando_de_dj,
    executar,
    opcoes_de_volume,
    opcoes_do_change_skin,
    skins_do_bot,
    status_no_comando,
)
from tests.support.modais import SERVIDOR_DO_COMANDO
from tests.panel.helpers_settings import (
    SettingsWorld,
    command_allowed_volumes,
    command_prefix_max_length,
    command_voice_max_length,
    command_voice_placeholders,
    parse_forms,
    version_of,
)


class TestCommandRules:
    @pytest.mark.asyncio
    async def test_volume_set_is_5_to_100_step_5_and_110_to_150_step_10(self):
        offered, default = await opcoes_de_volume(100)
        allowed = command_allowed_volumes()
        assert sorted(offered) == sorted(allowed) and default == [100]
        assert len(allowed) == 25 and min(allowed) == 5 and max(allowed) == 150
        assert 105 not in allowed and 100 in allowed and 110 in allowed and 0 not in allowed

    @pytest.mark.asyncio
    async def test_volume_select_marks_the_saved_volume_as_the_default(self):
        assert (await opcoes_de_volume(150))[1] == [150] and (await opcoes_de_volume(5))[1] == [5]

    @pytest.mark.parametrize("placeholder", command_voice_placeholders())
    @pytest.mark.asyncio
    async def test_each_voice_status_placeholder_is_accepted_alone_by_the_command(self, placeholder):
        saved, _ = await status_no_comando(BotDeComandos(), placeholder)
        assert saved == placeholder

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

    @pytest.mark.parametrize("text", ["Tocando agora", "{foo}", "{track.titulo}", "track.title", "{TRACK.TITLE}"])
    @pytest.mark.asyncio
    async def test_voice_status_without_a_valid_placeholder_is_refused_by_the_command(self, text):
        saved, message = await status_no_comando(BotDeComandos(), text)
        assert saved is None and "placeholder" in message

    @pytest.mark.asyncio
    async def test_voice_status_modal_limit_is_496_and_line_breaks_become_spaces(self):
        field = await abrir_modal_do_status_permanente()
        assert {field.max_length} == command_voice_max_length() and field.required is False
        saved, _ = await status_no_comando(BotDeComandos(), "\n Agora:\n{track.title}\n")
        assert saved == "Agora: {track.title}", "o comando troca quebras de linha por espaço e apara as pontas"

    @pytest.mark.asyncio
    async def test_prefix_limit_is_five_and_reset_stores_empty_in_the_pool_cache_with_an_int_key(self):
        limit = command_prefix_max_length()
        assert limit == 5
        bot = BotDeComandos()
        ok = await executar(bot, legacy_cmds.Owner.setprefix, " " + "a" * limit + " ")
        assert not ok.recusado and bot.ultimo_global["prefix"] == "a" * limit, "o comando apara as pontas"
        assert bot.pool.guild_prefix_cache == {SERVIDOR_DO_COMANDO: "a" * limit}
        assert all(isinstance(key, int) for key in bot.pool.guild_prefix_cache)
        too_long = await executar(BotDeComandos(), legacy_cmds.Owner.setprefix, "a" * (limit + 1))
        assert too_long.recusado
        reset = await executar(bot, legacy_cmds.Owner.resetprefix)
        assert not reset.recusado and bot.ultimo_global["prefix"] == ""
        assert bot.pool.guild_prefix_cache == {SERVIDOR_DO_COMANDO: ""}

    @pytest.mark.asyncio
    async def test_skin_choices_exclude_the_ignore_lists_read_from_bot_config(self, monkeypatch):
        bot = BotDeComandos(config={"IGNORE_SKINS": "modern ghost", "IGNORE_STATIC_SKINS": "bar"})
        skins_do_bot(
            bot,
            ["classic", "modern", "compact"],
            ["simple", "bar"],
            personalizadas=["minha"],
            personalizadas_estaticas=["fixa"],
        )
        normal, static, global_normal, global_static = await opcoes_do_change_skin(monkeypatch, bot, GuildaFalsa())
        assert normal == global_normal == ["classic", "compact", "> custom_skin: minha"]
        assert static == global_static == ["simple", "> custom_skin: fixa"]

    @pytest.mark.asyncio
    async def test_dj_roles_are_string_ids_and_everyone_is_refused(self, monkeypatch):
        role = CargoFalso(1001)
        guild = GuildaFalsa([role])
        bot = BotDeComandos()
        refused = await comando_de_dj(monkeypatch, "add_dj_role", bot, guild, guild.default_role)
        assert bot.gravacoes == [] and "não pode adicionar" in refused.texto
        await comando_de_dj(monkeypatch, "add_dj_role", bot, guild, role)
        assert bot.ultimo_do_bot["djroles"] == ["1001"], "ids como texto, na ordem de inclusão"
        bot.documento("bot", DBModel.guilds, SERVIDOR_DO_COMANDO)["djroles"] = ["1001"]
        repeated = await comando_de_dj(monkeypatch, "add_dj_role", bot, guild, role)
        assert "já está na lista" in repeated.texto

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

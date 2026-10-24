"""Caracterização (VERDE contra o código ATUAL) de /setup e /reset — modules/music_settings.py:375-1010.

Objetivo: congelar o comportamento antes de extrair a lógica para `utils/music/request_channel.py` (E4c, opção A).
Mede efeitos no Discord e no banco, a ORDEM entre eles, mensagens de erro e limites. Nada aqui corrige defeitos:
comportamentos ruins estão registrados de propósito e marcados `INVERTER_APOS_E4C` quando a E4c vai corrigi-los.
"""

import asyncio
from types import SimpleNamespace

import disnake
import pytest

import empiremuse.cogs.music_settings as ms
from tests.support.canal_de_pedidos import (
    BOT_MENTION,
    GUILD_ID,
    CommandInter,
    ComponentInter,
    FakeBot,
    FakeCategory,
    FakeDB,
    FakeForum,
    FakeGuild,
    FakeMessage,
    FULL_TEXT,
    FakePlayer,
    FakeStage,
    FakeText,
    FakeThreadInfo,
    FakeVoice,
    Journal,
    ModalInter,
    perms,
)
from empiremuse.utils.music.errors import GenericError


ESC = "\x1b"
FORUM_MANAGE_THREADS_TEXT = (
    f"**{BOT_MENTION} não possui permissão de gerenciar tópicos no canal <#55>.**\n"
    "`Nota: Você pode me conceder temporariamente essa permissão e após usar o comando novamente "
    "você pode remover essa permissão.`"
)


def ansi_permissions_message(mention, channel, missing):
    """Mensagem EXATA de check_channel_perm: bloco ```ansi com uma linha amarela (ESC[0;33m … ESC[0m) por permissão,
    na ordem em que `Permissions` itera. Os bytes ESC fazem parte do contrato (o Discord só colore com eles)."""
    from empiremuse.utils.music.converters import perms_translations

    ordered = [name for name, _ in channel.permissions_for(None) if name in missing]
    lines = "\n".join(f"{ESC}[0;33m{perms_translations.get(name, name)}{ESC}[0m" for name in ordered)
    return f"**{BOT_MENTION} não possui as seguintes permissões necessárias no canal {mention}** ```ansi\n{lines}```"


class Scenario:
    """Servidor com um bot, o canal do comando (#geral, em uma categoria) e um canal de cada tipo."""

    def __init__(
        self,
        monkeypatch,
        *,
        admin=False,
        manage_channels=True,
        manage_threads=True,
        features=(),
        db_channel=None,
        db_message=None,
        history=True,
    ):
        self.j = Journal()
        bot_perms = perms(
            administrator=admin,
            manage_channels=manage_channels,
            manage_threads=manage_threads,
            read_message_history=history,
        )
        self.guild = FakeGuild(self.j, bot_perms, features)
        self.db = FakeDB(self.j, db_channel, db_message)
        self.bot = FakeBot(self.j, self.guild, self.db)
        self.category = FakeCategory(self.j, self.guild)
        self.lobby = FakeText(self.j, 11, "geral", self.guild, category=self.category)
        self.text = FakeText(self.j, 22, "pedidos", self.guild)
        self.voice = FakeVoice(self.j, 33, "voz", self.guild)
        self.stage = FakeStage(self.j, 44, "palco", self.guild)
        self.forum = FakeForum(self.j, 55, "fórum", self.guild)
        for channel in (self.lobby, self.text, self.voice, self.stage, self.forum):
            self.bot.channels[channel.id] = channel
        self.cog = ms.MusicSettings(self.bot)
        self.next_message = 9000
        monkeypatch.setattr(ms, "send_idle_embed", self.fake_send_idle_embed)

    # ---- o send_idle_embed real monta embeds enormes: aqui só registramos a chamada e devolvemos a mensagem
    async def fake_send_idle_embed(self, target, text="", *, bot, force=False, guild_data=None):
        label = target.label if hasattr(target, "label") else f"mensagem-{target.id}"
        self.j.add("send_idle_embed", label, force, bot is self.bot)
        if isinstance(target, FakeMessage):
            return target
        self.next_message += 1
        return target.add_message(self.next_message, self.guild.me)

    # ---- execução
    def command_inter(self):
        return CommandInter(self.j, self.bot, self.guild, self.lobby)

    def setup(self, target=None, purge="no", inter=None):
        self.inter = inter or self.command_inter()
        return asyncio.run(self.cog.setup.callback(self.cog, self.inter, target=target, purge_messages=purge))

    def reset(self, delete="não", inter=None):
        self.inter = inter or self.command_inter()
        return asyncio.run(self.cog.reset.callback(self.cog, self.inter, delete_channel=delete))

    # ---- consultas
    @property
    def saved(self):
        return self.db.doc["player_controller"]

    def final_embed_text(self):
        edits = self.j.of("inter.edit_original_message")
        return edits[-1][3]["embed"].description if edits else None


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


def error_text(call, *args, **kwargs):
    with pytest.raises(GenericError) as raised:
        call(*args, **kwargs)
    return raised.value.text


class TestSetupExistingTextChannel:
    def test_bot_overwrite_has_nine_permissions_and_manage_permissions_only_for_admin(self, world, monkeypatch):
        world.setup(target=world.text)
        overwrite = world.j.of("channel.edit")[0][2]["overwrites"][world.guild.me]
        granted = {name for name, value in overwrite if value is True}
        assert granted == {
            "embed_links",
            "send_messages",
            "send_messages_in_threads",
            "view_channel",
            "create_public_threads",
            "read_message_history",
            "manage_messages",
            "manage_channels",
            "attach_files",
        }
        admin = Scenario(monkeypatch, admin=True)
        admin.setup(target=admin.text)
        overwrite_admin = admin.j.of("channel.edit")[0][2]["overwrites"][admin.guild.me]
        assert {n for n, v in overwrite_admin if v is True} == granted | {
            "manage_roles"
        }  # manage_permissions == manage_roles

    def test_purge_yes_runs_before_the_history_scan_and_keeps_bot_messages_with_a_thread(self, world):
        world.setup(target=world.text, purge="yes")
        purge = world.j.of("channel.purge")
        assert len(purge) == 1 and purge[0][2] == 100
        assert world.j.index("channel.purge") < world.j.index("channel.history")
        check = purge[0][3]
        me, other = world.guild.me, SimpleNamespace()
        assert check(SimpleNamespace(author=other, thread=object())) is True, "mensagem de outra pessoa: apaga"
        assert check(SimpleNamespace(author=me, thread=None)) is True, "do bot sem thread: apaga"
        assert check(SimpleNamespace(author=me, thread=object())) is False, "do bot COM thread: preserva"

    def test_reused_thread_is_reactivated_by_the_rules_of_the_code(self, world):
        me = world.guild.me

        def run(thread):
            scenario = world
            scenario.text.history_list.clear()
            scenario.text.add_message(3, me, thread)
            scenario.j.clear()
            scenario.setup(target=scenario.text)
            return scenario.j.of("thread.edit")

        locked = FakeThreadInfo(world.j, "locked", locked=True, archived=True, perms_=perms(manage_threads=True))
        assert run(locked)[0][2] == {
            "locked": False,
            "archived": False,
            "reason": f"Song request reativado por: Autor#0001.",
        }
        archived = FakeThreadInfo(world.j, "arq", archived=True, perms_=perms(manage_threads=False))
        assert run(archived)[0][2] == {"archived": False, "reason": "Song request reativado por: Autor#0001."}
        healthy = FakeThreadInfo(world.j, "ok")
        assert run(healthy) == [], "thread saudável não é editada"
        stranger = FakeThreadInfo(world.j, "alheia", owner_id=1, archived=True, perms_=perms())
        assert run(stranger) == [], "arquivada mas de outro dono e sem manage_threads: não mexe"

    def test_a_failing_overwrite_edit_is_swallowed_and_setup_continues(self, world):
        world.text.fail_edit = disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        world.setup(target=world.text)
        assert world.saved["channel"] == "22" and len(world.db.updates) == 1


class TestSetupRefusals:
    """Cada recusa é um GenericError; em todas o banco fica intacto e nada é enviado ao canal."""

    def assert_nothing_happened(self, world):
        assert world.db.updates == []
        for name in ("send_idle_embed", "channel.edit", "channel.purge", "message.create_thread", "db.update"):
            assert world.j.of(name) == [], name

    def test_missing_send_messages_and_embed_links_list_both_translated(self, world):
        world.text._perms = perms(view_channel=True, manage_permissions=True)
        text = error_text(world.setup, target=world.text)
        assert text == ansi_permissions_message("<#22>", world.text, ("send_messages", "embed_links"))
        self.assert_nothing_happened(world)


class TestSetupOldMessageAndPlayer:
    def old_message(self, world, channel, message_id=777, with_thread=True):
        thread = FakeThreadInfo(world.j, "thread-antiga") if with_thread else None
        message = channel.add_message(message_id, world.guild.me, thread)
        world.db.doc["player_controller"].update({"channel": str(channel.id), "message_id": str(message_id)})
        return message

    def test_old_message_inside_a_forum_post_deletes_the_post_instead_of_editing(self, world):
        post = world.forum.add_post(700, "post antigo")
        thread = FakeThreadInfo(world.j, "post-antigo")
        old = FakeMessage(world.j, 700, post, world.guild.me, thread)
        post.messages[700] = old
        world.bot.channels[700] = post
        world.db.doc["player_controller"].update({"channel": "700", "message_id": "700"})
        world.setup(target=world.text)
        assert world.j.of("thread.delete") == [
            ("thread.delete", "post-antigo", {"reason": "Player reconfigurado por Autor#0001."})
        ]
        assert world.j.of("message.edit") == []
        assert world.j.of("send_idle_embed"), "mensagem nova é enviada no canal escolhido"

    def test_failure_archiving_the_old_message_is_swallowed(self, world):
        old_channel = FakeText(world.j, 23, "antigo", world.guild)
        world.bot.channels[23] = old_channel
        old = self.old_message(world, old_channel)
        old.fail_edit = RuntimeError("boom")
        old.thread.fail = RuntimeError("boom")
        world.setup(target=world.text)
        assert world.saved["channel"] == "22"

    def test_static_player_moves_to_the_new_channel_after_archiving_its_thread(self, world):
        player_message = world.lobby.add_message(222, world.guild.me, FakeThreadInfo(world.j, "do-player"))
        player = FakePlayer(world.j, world.guild, world.lobby, static=True, message=player_message)
        world.bot.music.players[GUILD_ID] = player
        world.setup(target=world.text)
        names = world.j.names()
        archive = [e for e in world.j.of("thread.edit") if e[1] == "do-player"]
        assert archive and archive[-1][2] == {
            "archived": True,
            "locked": True,
            "reason": "Player reconfigurado por Autor#0001.",
        }
        tail = [n for n in names if n.startswith("player.") or n == "db.update"]
        assert tail == ["player.setup_hints", "player.setup_features", "player.invoke_np", "db.update"]
        assert world.j.of("player.invoke_np") == [("player.invoke_np", True)]
        assert player.static is True and player.text_channel is world.text
        assert player.message.channel is world.text and world.saved["message_id"] == str(player.message.id)


class TestSetupVoiceAndStage:
    def test_player_is_reconnected_to_the_voice_channel_unless_already_there(self, world):
        player = FakePlayer(world.j, world.guild, world.lobby, static=False, message=None, voice_channel=world.stage)
        world.bot.music.players[GUILD_ID] = player
        world.setup(target=world.voice)
        # o ramo do player (text_channel != target) vem primeiro; a reconexão fica no `elif` da cadeia seguinte
        assert world.j.of("player.connect") == [("player.connect", 33)]
        world.j.clear()
        player.guild.me.voice = SimpleNamespace(channel=world.voice)
        world.setup(target=world.voice)
        assert world.j.of("player.connect") == []


def click(world, custom_id, values=None, event="button_click"):
    """Enfileira a interação que o `wait_for` entregará (ids terminam em _777, o id da interação do comando)."""
    interaction = ComponentInter(world.j, world.bot, world.guild, custom_id, values)
    world.bot.script.setdefault(event, []).append(interaction)
    return interaction


class TestSetupCreateAndSelect:
    """/setup sem canal: mostra a seleção (45 s) e cria texto/voz/palco ou usa o canal escolhido."""

    def components(self, world):
        first = world.j.of("inter.edit_original_message")[0]
        return first[3]["embeds"], first[3]["components"]

    def test_without_manage_channels_the_create_buttons_are_disabled_with_a_notice(self, monkeypatch):
        scenario = Scenario(monkeypatch, manage_channels=False, features=("COMMUNITY",))
        click(scenario, "voice_channel_cancel_777")
        scenario.setup()
        embeds, components = self.components(scenario)
        labels = {b.label: b.disabled for b in components[1:]}
        assert labels == {
            "Criar canal de texto": True,
            "Criar canal de voz": True,
            "Criar canal de palco": True,
            "Cancelar": False,
        }
        assert embeds[0].description == "**Selecione um canal abaixo:**"
        assert len(embeds) == 2 and embeds[1].description == (
            f"Os botões de criar canal foram desativados devido o bot **{BOT_MENTION}** "
            "não possuir a permissão de **gerenciar canais** no servidor."
        )

    def test_timeout_resets_the_cooldown_and_says_time_is_up(self, world, monkeypatch):
        real_wait = asyncio.wait

        async def fast(fs, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            return await real_wait(fs, timeout=0.05, return_when=return_when)

        monkeypatch.setattr(ms.asyncio, "wait", fast)
        world.setup()
        assert world.j.of("cooldown.reset") == [("cooldown.reset",)]
        edit = world.j.of("select_message.edit")[0][1]
        assert edit["embed"].description == "**Tempo esgotado!**" and edit["components"] is None
        assert world.db.updates == []

    def test_command_channel_without_category_creates_at_the_root(self, world):
        world.lobby._category = None
        click(world, "text_channel_777")
        world.setup()
        assert world.j.of("create_text_channel")[0][1] == "raiz"

    @pytest.mark.parametrize(
        "button,creator", [("voice_channel_777", "create_voice_channel"), ("stage_channel_777", "create_stage_channel")]
    )
    def test_voice_and_stage_are_created_without_a_thread(self, world, button, creator):
        click(world, button)
        world.setup()
        assert world.j.of(creator)[0][2] == "Bot Um player controller"
        assert world.j.of("message.create_thread") == [] and world.saved["channel"] == str(world.guild._next)

    def test_creating_without_manage_channels_is_refused_even_if_the_button_is_forced(self, monkeypatch):
        scenario = Scenario(monkeypatch, manage_channels=False)
        click(scenario, "text_channel_777")
        text = error_text(scenario.setup)
        assert text == f"**O bot {BOT_MENTION} não possui permissão de gerenciar canais pra criar um novo canal.**"
        assert scenario.db.updates == [] and scenario.j.of("create_text_channel") == []

    def test_choosing_an_existing_channel_from_the_dropdown_behaves_like_the_argument(self, world):
        click(world, "existing_channel_777", values=["22"], event="dropdown")
        world.setup()
        assert world.j.of("create_text_channel") == []
        assert world.j.of("channel.edit")[0][1] == "#pedidos" and world.saved["channel"] == "22"


def modal_answer(world, title, custom_id="777"):
    answer = ModalInter(world.j, world.bot, world.guild, custom_id, {"forum_title": title})
    world.bot.script.setdefault("modal_submit", []).append(answer)
    return answer


class TestSetupForum:
    def test_forum_argument_asks_the_post_title_first_with_a_30_second_modal(self, world):
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        opened = world.j.of("response.send_modal")[0][2]
        assert opened["title"] == "Escolha um nome para o post (em até 30seg.)" and opened["custom_id"] == "777"
        field = opened["components"][0]
        assert (field.custom_id, field.min_length, field.max_length, field.value) == (
            "forum_title",
            4,
            30,
            "Bot Um Song Request",
        )
        event, timeout, _ = world.bot.waits[0]
        assert (event, timeout) == ("modal_submit", 30)
        assert world.j.of("response.defer")[0][2] is True, "depois do modal: defer efêmero na interação do modal"

    def test_modal_timeout_ends_silently_without_touching_anything(self, world):
        world.bot.script["modal_submit"] = [asyncio.TimeoutError()]
        world.setup(target=world.forum)
        assert world.db.updates == [] and world.j.of("forum.create_thread") == []
        assert world.j.of("send_idle_embed") == []

    def test_open_post_that_is_locked_is_unlocked_only_with_manage_threads(self, world):
        mine = world.forum.add_post(802, "meu post", locked=True, archived=True)
        world.forum.thread_list, world.forum.archived_list = [mine], []
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert world.j.of("thread.edit")[0][2] == {"locked": False, "archived": False}
        world.j.clear()
        world.forum._perms = perms(**{**FULL_TEXT, "manage_threads": False})
        mine.locked, mine.archived = True, True
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert world.j.of("thread.edit")[0][2] == {"archived": False}, "sem manage_threads: só desarquiva"

    def test_post_whose_first_message_is_gone_is_skipped(self, world):
        world.forum.add_post(804, "sem mensagem", with_message=False)
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert world.j.of("forum.create_thread"), "NotFound em fetch_message => continua e cria outro"

    def test_creating_a_post_needs_manage_threads_in_the_forum(self, world):
        world.forum._perms = perms(
            view_channel=True, send_messages=True, embed_links=True, send_messages_in_threads=True
        )
        modal_answer(world, "Pedidos do bot")
        text = error_text(world.setup, target=world.forum)
        assert text == FORUM_MANAGE_THREADS_TEXT
        assert world.db.updates == [] and world.j.of("forum.create_thread") == []

    def test_forum_chosen_from_the_dropdown_opens_a_second_modal(self, world):
        click(world, "existing_channel_777", values=["55"], event="dropdown")
        modal_answer(world, "Pedidos do bot", custom_id="modal_778")
        world.setup()
        opened = world.j.of("response.send_modal")[0]
        assert opened[1] == "component:existing_channel_777"
        assert opened[2]["title"] == "Definir um nome para o post do fórum" and opened[2]["custom_id"] == "modal_778"
        assert world.j.of("select_message.delete") == [("select_message.delete",)]
        assert world.j.of("forum.create_thread")[0][2] == "Pedidos do bot"
        assert world.saved["channel"] == str(world.forum.created[0].id)

    def test_dropdown_forum_modal_timeout_says_time_is_up_and_saves_nothing(self, world):
        click(world, "existing_channel_777", values=["55"], event="dropdown")
        world.bot.script["modal_submit"] = [asyncio.TimeoutError()]
        world.setup()
        texts = [e[3]["embed"].description for e in world.j.of("inter.edit_original_message") if "embed" in e[3]]
        assert "### Tempo esgotado!" in texts
        assert world.db.updates == [] and world.j.of("forum.create_thread") == []


def configured(world, thread=True):
    """Canal de pedidos #pedidos (22) com a mensagem 555 (e thread) gravados no banco."""
    message = world.text.add_message(555, world.guild.me, FakeThreadInfo(world.j, "song-requests") if thread else None)
    world.db.doc["player_controller"].update({"channel": "22", "message_id": "555"})
    return message


class TestResetRefusals:
    @pytest.mark.parametrize("channel", [None, "999999"])
    def test_no_configured_channel_or_a_missing_one(self, world, channel):
        world.db.doc["player_controller"].update({"channel": channel, "message_id": "1"})
        text = error_text(world.reset)
        assert (
            text == f"**Não há canais de pedido de música configurado no bot {BOT_MENTION} (ou o canal foi deletado).**"
        )
        assert world.db.updates == []


class TestResetTextChannel:
    def test_missing_message_is_not_an_error(self, world):
        world.db.doc["player_controller"].update({"channel": "22", "message_id": "404"})
        world.reset()
        assert world.saved["channel"] is None and world.j.of("message.edit") == []

    def test_player_is_reset_after_the_discord_cleanup_the_database_and_the_reply(self, world):
        configured(world)
        player = FakePlayer(world.j, world.guild, world.text, static=True, message=object())
        world.bot.music.players[GUILD_ID] = player
        world.reset()
        names = [
            n
            for n in world.j.names()
            if n
            in ("db.update", "inter.edit_original_message", "player.process_hint", "player.invoke_np", "message.edit")
        ]
        assert names == [
            "message.edit",
            "db.update",
            "inter.edit_original_message",
            "player.process_hint",
            "player.invoke_np",
        ]
        assert player.static is False and player.message is None and player.text_channel is world.lobby
        assert world.j.of("player.invoke_np") == [("player.invoke_np", True)]

    def test_channel_delete_failure_also_keeps_the_database(self, world):
        configured(world)
        world.text.fail_delete = disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
        text = error_text(world.reset, delete="sim")
        assert "Missing Access" not in text and "resetado da base" not in text
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555")


class TestResetForum:
    def post(self, world):
        post = world.forum.add_post(900, "post de pedidos")
        world.bot.channels[900] = post
        world.db.doc["player_controller"].update({"channel": "900", "message_id": "900"})
        return post

    def test_deletes_the_post_and_tells_the_user(self, world):
        self.post(world)
        world.reset()
        assert world.j.of("thread.edit") == [] and world.j.of("channel.delete") == [
            ("channel.delete", "#post de pedidos", f"{9000} resetou player")
        ]
        reply = world.j.of("inter.edit_original_message")[-1]
        assert reply[2] == ("O post foi deletado com sucesso!",) and reply[3] == {"embed": None, "components": None}


class TestResetWrapperAndLimits:
    def test_legacy_wrapper_translates_the_delete_flag(self, world, monkeypatch):
        seen = []

        async def record(self, interaction, delete_channel):
            seen.append(delete_channel)

        monkeypatch.setattr(world.cog, "reset", SimpleNamespace(callback=record))
        for given in ("--delete", None, "sim", "outra"):
            asyncio.run(world.cog.reset_legacy.callback(world.cog, world.command_inter(), delete_channel=given))
        assert seen == ["sim", None, "sim", "outra"]

    def test_legacy_setup_forwards_target_and_purge_flag(self, world, monkeypatch):
        seen = []

        async def record(self, interaction, target, purge_messages):
            seen.append((target, purge_messages))

        monkeypatch.setattr(world.cog, "setup", SimpleNamespace(callback=record))
        for flags in ((), ("--reset",), ("-purge",)):
            ctx = world.command_inter()
            ctx.command = SimpleNamespace(extras=ms.MusicSettings.setup_legacy.extras)
            asyncio.run(world.cog.setup_legacy.callback(world.cog, ctx, world.text, *flags))
        assert [p for _, p in seen] == [False, True, True] and all(t is world.text for t, _ in seen)

"""Caracterização (VERDE contra o código ATUAL) de /setup e /reset — modules/music_settings.py:375-1010.

Objetivo: congelar o comportamento antes de extrair a lógica para `utils/music/request_channel.py` (E4c, opção A).
Mede efeitos no Discord e no banco, a ORDEM entre eles, mensagens de erro e limites. Nada aqui corrige defeitos:
comportamentos ruins estão registrados de propósito e marcados `INVERTER_APOS_E4C` quando a E4c vai corrigi-los.
"""

import asyncio
from types import SimpleNamespace

import disnake
import pytest
from disnake.ext import commands

import modules.music_settings as ms
from tests.helpers_request_channel import (
    ACTOR_MENTION,
    BOT_ID,
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
from utils.music.errors import GenericError

INVERTER_APOS_E4C = "comportamento ruim registrado de propósito: a E4c inverte este teste (ver BRIEFING-PAINEL-E4)"


ESC = "\x1b"
MANAGE_PERMISSIONS_TEXT = (
    f"**{BOT_MENTION} não possui permissão de administrador ou permissão de gerenciar permissões do canal <#22>** "
    "para editar as permissões necessárias para o sistema de pedir música funcionar devidamente.\n\n"
    "Caso não queira fornecer a permissão de administrador ou editar as permissões do canal <#22> para me permitir "
    "gerenciar permissões do canal. Você pode usar o comando sem selecionar um canal de destino."
)
FORUM_MANAGE_THREADS_TEXT = (
    f"**{BOT_MENTION} não possui permissão de gerenciar tópicos no canal <#55>.**\n"
    "`Nota: Você pode me conceder temporariamente essa permissão e após usar o comando novamente "
    "você pode remover essa permissão.`"
)


def ansi_permissions_message(mention, channel, missing):
    """Mensagem EXATA de check_channel_perm: bloco ```ansi com uma linha amarela (ESC[0;33m … ESC[0m) por permissão,
    na ordem em que `Permissions` itera. Os bytes ESC fazem parte do contrato (o Discord só colore com eles)."""
    from utils.music.converters import perms_translations

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
    def test_happy_path_effects_order_and_database(self, world):
        world.setup(target=world.text)
        j = world.j
        order = [
            e[0]
            for e in j
            if e[0] in ("channel.history", "send_idle_embed", "channel.edit", "message.create_thread", "db.update")
        ]
        # observado: o overwrite do bot é editado ANTES de enviar o embed ocioso
        assert order == ["channel.history", "channel.edit", "send_idle_embed", "message.create_thread", "db.update"]
        assert j.of("send_idle_embed") == [("send_idle_embed", "#pedidos", True, True)]
        assert j.of("channel.history") == [("channel.history", "#pedidos", 100)]
        assert j.of("message.create_thread")[0][2:] == ("Song-Requests", 10080)
        message_id = j.of("message.create_thread")[0][1]
        assert world.saved["channel"] == "22" and world.saved["message_id"] == str(message_id)
        assert isinstance(world.saved["channel"], str) and isinstance(world.saved["message_id"], str)

    def test_only_channel_and_message_id_change_in_the_database(self, world):
        before = {k: v for k, v in world.db.doc.items() if k != "player_controller"}
        before_pc = {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")}
        world.setup(target=world.text)
        assert {k: v for k, v in world.db.doc.items() if k != "player_controller"} == before
        assert {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")} == before_pc
        assert len(world.db.updates) == 1 and world.db.doc["ver"] == before["ver"]

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

    def test_final_reply_mentions_actor_channel_and_how_to_revert(self, world):
        world.setup(target=world.text)
        text = world.final_embed_text()
        assert text == (
            f"**{ACTOR_MENTION}, o sistema pra pedidos de música foi configurado no canal <#22> "
            f"através do bot: {BOT_MENTION}**\n\nObs: Caso queira reverter essa configuração, apenas use "
            f"o comando /reset ou delete o canal/post <#22>"
        )
        edits = world.j.of("inter.edit_original_message")
        assert edits[-1][3]["components"] is None
        assert world.j.of("response.defer")[0][2] is True, "resposta efêmera (defer ephemeral=True)"

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

    def test_purge_no_never_purges(self, world):
        world.setup(target=world.text, purge="no")
        assert world.j.of("channel.purge") == []

    def test_reuses_the_first_bot_message_with_a_thread_in_the_last_100(self, world):
        me = world.guild.me
        world.text.add_message(1, SimpleNamespace(id=1), FakeThreadInfo(world.j, "alheia"))
        world.text.add_message(2, me)  # do bot, sem thread
        reused = world.text.add_message(3, me, FakeThreadInfo(world.j, "t3"))  # do bot, com thread
        world.text.add_message(4, me, FakeThreadInfo(world.j, "t4"))  # mais antiga ainda
        world.text.history_list = [world.text.messages[i] for i in (1, 2, 3, 4)]
        world.setup(target=world.text)
        assert world.j.of("send_idle_embed") == [] and world.j.of("message.create_thread") == []
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "3") and reused.id == 3

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

    def test_without_create_public_threads_no_thread_is_created_and_the_database_is_still_saved(self, world):
        world.text._perms = perms(**{**FULL_TEXT_NO_THREADS})
        world.setup(target=world.text)
        assert world.j.of("message.create_thread") == [] and world.saved["channel"] == "22"

    def test_a_failing_overwrite_edit_is_swallowed_and_setup_continues(self, world):
        world.text.fail_edit = disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        world.setup(target=world.text)
        assert world.saved["channel"] == "22" and len(world.db.updates) == 1


FULL_TEXT_NO_THREADS = dict(
    view_channel=True,
    send_messages=True,
    embed_links=True,
    read_message_history=True,
    manage_permissions=True,
    manage_threads=True,
    send_messages_in_threads=True,
)


class TestSetupRefusals:
    """Cada recusa é um GenericError; em todas o banco fica intacto e nada é enviado ao canal."""

    def assert_nothing_happened(self, world):
        assert world.db.updates == []
        for name in ("send_idle_embed", "channel.edit", "channel.purge", "message.create_thread", "db.update"):
            assert world.j.of(name) == [], name

    def test_discord_updates_channel(self, world):
        world.guild.public_updates_channel = world.text
        assert (
            error_text(world.setup, target=world.text) == "**Você não pode usar um canal de atualizações do discord.**"
        )
        self.assert_nothing_happened(world)

    def test_rules_channel(self, world):
        world.guild.rules_channel = world.text
        assert error_text(world.setup, target=world.text) == "**Você não pode usar um canal de regras.**"
        self.assert_nothing_happened(world)

    def test_updates_check_wins_over_rules_check(self, world):
        world.guild.public_updates_channel = world.guild.rules_channel = world.text
        assert "atualizações" in error_text(world.setup, target=world.text)

    def test_missing_send_messages_and_embed_links_list_both_translated(self, world):
        world.text._perms = perms(view_channel=True, manage_permissions=True)
        text = error_text(world.setup, target=world.text)
        assert text == ansi_permissions_message("<#22>", world.text, ("send_messages", "embed_links"))
        self.assert_nothing_happened(world)

    def test_missing_view_channel_is_reported_by_check_channel_perm(self, world):
        # E4c: a checagem passa a enxergar o nome canônico `view_channel` (antes: "read_messages" nunca casava).
        world.text._perms = perms(send_messages=True, embed_links=True, manage_permissions=True)
        text = error_text(world.setup, target=world.text)
        assert text == ansi_permissions_message("<#22>", world.text, ("view_channel",))
        self.assert_nothing_happened(world)

    def test_existing_channel_needs_admin_or_manage_permissions(self, world, monkeypatch):
        world.text._perms = perms(view_channel=True, send_messages=True, embed_links=True)
        text = error_text(world.setup, target=world.text)
        assert text == MANAGE_PERMISSIONS_TEXT
        self.assert_nothing_happened(world)
        admin = Scenario(monkeypatch, admin=True)
        admin.text._perms = perms(view_channel=True, send_messages=True, embed_links=True)
        admin.setup(target=admin.text)  # administrador dispensa manage_permissions do canal
        assert admin.saved["channel"] == "22"

    def test_the_permission_check_runs_before_the_manage_permissions_check(self, world):
        world.text._perms = perms(view_channel=True)
        assert "não possui as seguintes permissões" in error_text(world.setup, target=world.text)


ARCHIVED_TEXT = "**Este canal de pedir música foi reconfigurado pelo membro <@9000>.**"


class TestSetupOldMessageAndPlayer:
    def old_message(self, world, channel, message_id=777, with_thread=True):
        thread = FakeThreadInfo(world.j, "thread-antiga") if with_thread else None
        message = channel.add_message(message_id, world.guild.me, thread)
        world.db.doc["player_controller"].update({"channel": str(channel.id), "message_id": str(message_id)})
        return message

    def test_old_message_in_another_channel_is_archived_before_the_new_one_is_sent(self, world):
        old_channel = FakeText(world.j, 23, "antigo", world.guild)
        world.bot.channels[23] = old_channel
        old = self.old_message(world, old_channel)
        world.setup(target=world.text)
        edit = world.j.of("message.edit")[0]
        assert edit[1] == 777 and edit[2]["content"] is None and edit[2]["view"] is None
        assert edit[2]["embed"].description == ARCHIVED_TEXT
        thread_edit = world.j.of("thread.edit")[0]
        assert thread_edit[1] == "thread-antiga"
        assert thread_edit[2] == {"archived": True, "locked": True, "reason": "Player reconfigurado por Autor#0001."}
        names = world.j.names()
        assert names.index("message.edit") < names.index("send_idle_embed") < names.index("db.update")
        assert world.saved["channel"] == "22" and old.id == 777

    def test_old_message_in_the_same_channel_is_reused(self, world):
        old = self.old_message(world, world.text, message_id=555)
        world.setup(target=world.text)
        assert world.j.of("send_idle_embed") == [] and world.j.of("message.edit") == []
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555") and old.thread is not None

    def test_database_lookup_failures_are_ignored(self, world):
        for channel, message in (("abc", "1"), ("99999", "1"), ("22", "999"), (None, None), ("22", "xyz")):
            world.j.clear()
            world.db.doc["player_controller"].update({"channel": channel, "message_id": message})
            world.setup(target=world.text)
            assert world.j.of("message.edit") == [], (channel, message)
            assert world.saved["channel"] == "22", (channel, message)

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

    def test_static_player_message_takes_precedence_over_the_database_message(self, world):
        stale_channel = FakeText(world.j, 23, "velho", world.guild)
        world.bot.channels[23] = stale_channel
        self.old_message(world, stale_channel, message_id=111)
        player_message = world.lobby.add_message(222, world.guild.me, FakeThreadInfo(world.j, "do-player"))
        world.bot.music.players[GUILD_ID] = FakePlayer(
            world.j, world.guild, world.lobby, static=True, message=player_message
        )
        world.setup(target=world.text)
        edited = [e[1] for e in world.j.of("message.edit")]
        assert 222 in edited and 111 not in edited

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

    def test_non_static_player_message_is_deleted_and_the_player_becomes_static(self, world):
        player_message = world.lobby.add_message(222, world.guild.me)
        player = FakePlayer(world.j, world.guild, world.lobby, static=False, message=player_message)
        world.bot.music.players[GUILD_ID] = player
        world.setup(target=world.text)
        assert world.j.of("message.delete") == [("message.delete", 222)]
        assert player.static is True and player.text_channel is world.text

    def test_player_already_in_the_target_channel_is_left_alone(self, world):
        player = FakePlayer(world.j, world.guild, world.text, static=True, message=None)
        world.bot.music.players[GUILD_ID] = player
        world.setup(target=world.text)
        assert [n for n in world.j.names() if n.startswith("player.")] == []
        assert world.j.of("send_idle_embed"), "o embed ocioso é enviado pelo ramo `elif not message`"


class TestSetupVoiceAndStage:
    @pytest.mark.parametrize("attr,channel_id", [("voice", 33), ("stage", 44)])
    def test_existing_voice_or_stage_channel_gets_the_embed_but_no_thread(self, world, attr, channel_id):
        channel = getattr(world, attr)
        world.setup(target=channel)
        assert world.j.of("send_idle_embed")[0][1] == channel.label
        assert world.j.of("message.create_thread") == []
        assert world.j.of("channel.edit")[0][1] == channel.label
        assert world.saved["channel"] == str(channel_id)

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

    def test_selection_message_offers_select_and_buttons_with_a_45_second_notice(self, world):
        click(world, "voice_channel_cancel_777")
        world.setup()
        embeds, components = self.components(world)
        select, *buttons = components
        assert isinstance(select, disnake.ui.ChannelSelect)
        assert [t for t in select.channel_types] == [
            disnake.ChannelType.text,
            disnake.ChannelType.voice,
            disnake.ChannelType.stage_voice,
            disnake.ChannelType.forum,
        ]
        assert [b.label for b in buttons] == ["Criar canal de texto", "Criar canal de voz", "Cancelar"]
        assert [b.custom_id for b in buttons] == ["text_channel_777", "voice_channel_777", "voice_channel_cancel_777"]
        assert not any(b.disabled for b in buttons)
        assert embeds[0].description == (
            "**Selecione um canal ou clique em um dos botões abaixo para criar um novo canal para pedir músicas.**"
        )
        assert embeds[0].footer.text == "Você tem apenas 45 segundos para selecionar/clicar em uma opção."
        assert len(embeds) == 1
        assert [w[:2] for w in world.bot.waits] == [("button_click", None), ("dropdown", None)]

    def test_stage_button_only_with_community_and_before_cancel(self, monkeypatch):
        scenario = Scenario(monkeypatch, features=("COMMUNITY",))
        click(scenario, "voice_channel_cancel_777")
        scenario.setup()
        buttons = scenario.j.of("inter.edit_original_message")[0][3]["components"][1:]
        assert [b.label for b in buttons] == [
            "Criar canal de texto",
            "Criar canal de voz",
            "Criar canal de palco",
            "Cancelar",
        ]
        assert buttons[2].custom_id == "stage_channel_777"

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

    def test_cancel_edits_the_message_and_changes_nothing(self, world):
        click(world, "voice_channel_cancel_777")
        world.setup()
        edit = world.j.of("response.edit_message")[0]
        assert edit[2]["embed"].description == "**Operação cancelada...**" and edit[2]["components"] is None
        assert world.db.updates == [] and world.j.of("send_idle_embed") == []

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

    def test_create_text_channel_in_the_commands_category(self, world):
        click(world, "text_channel_777")
        world.setup()
        created = world.j.of("create_text_channel")[0]
        assert created[1] == "categoria" and created[2] == "Bot Um player controller"
        overwrite = created[3]["overwrites"][world.guild.me]
        assert {n for n, v in overwrite if v is True} >= {"send_messages", "embed_links", "manage_channels"}
        assert world.j.of("response.defer")[-1][2] is False, "o botão faz defer (público)"
        assert world.j.of("channel.edit") == [], "canal recém-criado não tem overwrite editado de novo"
        assert world.j.of("channel.purge") == []
        new_id = world.saved["channel"]
        assert new_id == str(world.guild._next) and world.saved["message_id"] == str(world.next_message)
        assert world.j.of("message.create_thread")[0][2:] == ("Song-Requests", 10080)
        assert world.j.of("channel.history")[0][1] == "#Bot Um player controller", "o histórico do novo canal é lido"
        assert "/reset" in world.final_embed_text()

    def test_category_without_send_messages_falls_back_to_the_guild_root(self, world):
        world.category._perms = perms()
        click(world, "text_channel_777")
        world.setup()
        assert world.j.of("create_text_channel")[0][1] == "raiz"

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

    def test_dropdown_choice_still_goes_through_the_refusals(self, world):
        world.guild.rules_channel = world.text
        click(world, "existing_channel_777", values=["22"], event="dropdown")
        assert "regras" in error_text(world.setup)


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

    def test_creates_the_post_when_the_bot_has_none_and_saves_thread_and_message(self, world):
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        create = world.j.of("forum.create_thread")[0]
        assert create[2:] == ("Pedidos do bot", "Post para pedido de músicas.", 10080, 5)
        post = world.forum.created[0]
        assert world.j.of("send_idle_embed") == [("send_idle_embed", f"mensagem-{post.id}", True, True)]
        assert (world.saved["channel"], world.saved["message_id"]) == (str(post.id), str(post.id))
        assert world.j.of("channel.purge") == [] and world.j.of("message.create_thread") == []

    def test_after_the_idle_embed_the_post_is_edited_with_no_arguments_quirk(self, world):
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        edits = world.j.of("thread.edit")
        assert len(edits) == 1 and edits[0][2] == {}, "channel_kwargs é limpo e mesmo assim o post é `edit()`ado"
        assert world.j.of("channel.edit") == [], "o fórum em si nunca é editado"
        names = [
            n for n in world.j.names() if n in ("forum.create_thread", "send_idle_embed", "thread.edit", "db.update")
        ]
        assert names == ["forum.create_thread", "send_idle_embed", "thread.edit", "db.update"]

    def test_purge_is_ignored_for_forums(self, world):
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum, purge="yes")
        assert world.j.of("channel.purge") == []

    def test_reuses_the_bots_open_post_and_ignores_other_owners(self, world):
        world.forum.add_post(801, "de outra pessoa", owner_id=1)
        mine = world.forum.add_post(802, "meu post")
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert world.j.of("forum.create_thread") == [] and world.saved["channel"] == str(mine.id)

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

    def test_archived_posts_are_searched_only_when_the_bot_can_read_history(self, world, monkeypatch):
        mine = world.forum.add_post(803, "arquivado", archived=True)
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert world.j.of("forum.archived_threads") == [("forum.archived_threads", "#fórum", 100)]
        assert world.saved["channel"] == str(mine.id) and world.j.of("thread.edit")[0][2] == {"archived": False}
        blind = Scenario(monkeypatch, history=False)
        blind.forum.add_post(803, "arquivado", archived=True)
        modal_answer(blind, "Pedidos do bot")
        blind.setup(target=blind.forum)
        assert blind.j.of("forum.archived_threads") == [] and blind.j.of("forum.create_thread"), "cria um novo"

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

    def test_forum_permissions_missing_embed_links_is_reported_by_check_channel_perm(self, world):
        world.forum._perms = perms(
            view_channel=True, send_messages=True, send_messages_in_threads=True, manage_threads=True
        )
        modal_answer(world, "Pedidos do bot")
        assert "Inserir links" in error_text(world.setup, target=world.forum)

    def test_missing_create_forum_threads_is_reported_by_check_channel_perm(self, world):
        # E4c: create_forum_threads (alias de send_messages) passa a ser detectado já na checagem de permissões.
        world.forum._perms = perms(
            view_channel=True, embed_links=True, send_messages_in_threads=True, manage_threads=True
        )
        modal_answer(world, "Pedidos do bot")
        text = error_text(world.setup, target=world.forum)
        assert text == ansi_permissions_message("<#55>", world.forum, ("send_messages",))

    def test_old_request_message_is_archived_after_the_post_is_ready(self, world):
        old_channel = FakeText(world.j, 23, "antigo", world.guild)
        world.bot.channels[23] = old_channel
        old_channel.add_message(777, world.guild.me, FakeThreadInfo(world.j, "thread-antiga"))
        world.db.doc["player_controller"].update({"channel": "23", "message_id": "777"})
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        names = world.j.names()
        assert names.index("send_idle_embed") < names.index("message.edit") < names.index("db.update")

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


CONFIGURED_TEXT = "pedidos"


def configured(world, thread=True):
    """Canal de pedidos #pedidos (22) com a mensagem 555 (e thread) gravados no banco."""
    message = world.text.add_message(555, world.guild.me, FakeThreadInfo(world.j, "song-requests") if thread else None)
    world.db.doc["player_controller"].update({"channel": "22", "message_id": "555"})
    return message


class TestResetRefusals:
    def test_bot_without_manage_threads_in_the_guild(self, monkeypatch):
        scenario = Scenario(monkeypatch, manage_threads=False)
        configured(scenario)
        assert error_text(scenario.reset) == "Não tenho permissão de **Gerenciar Tópicos** no servidor."
        assert scenario.db.updates == [] and scenario.j.of("channel.delete") == []

    @pytest.mark.parametrize("channel", [None, "abc", "999999"])
    def test_no_configured_channel_or_a_missing_one(self, world, channel):
        world.db.doc["player_controller"].update({"channel": channel, "message_id": "1"})
        text = error_text(world.reset)
        assert (
            text == f"**Não há canais de pedido de música configurado no bot {BOT_MENTION} (ou o canal foi deletado).**"
        )
        assert world.db.updates == []

    def test_channel_from_another_guild_is_treated_as_missing(self, world):
        other_guild = SimpleNamespace(id=1)
        foreign = FakeText(world.j, 66, "alheio", other_guild)
        world.bot.channels[66] = foreign
        world.db.doc["player_controller"].update({"channel": "66", "message_id": "1"})
        assert "Não há canais de pedido de música configurado" in error_text(world.reset)
        assert world.db.updates == [] and world.j.of("channel.delete") == []

    def test_channel_outside_the_cache_is_found_through_the_api(self, world):
        configured(world)
        world.bot.channels.pop(22)
        world.bot.fetchable[22] = world.text
        world.reset()
        assert world.saved["channel"] is None


class TestResetTextChannel:
    def test_clears_the_database_first_then_replies_then_edits_the_message_and_archives_the_thread(self, world):
        message = configured(world)
        world.reset()
        names = [
            n
            for n in world.j.names()
            if n in ("db.update", "inter.edit_original_message", "message.edit", "thread.edit", "channel.delete")
        ]
        assert names == ["db.update", "inter.edit_original_message", "message.edit", "thread.edit"]
        assert world.saved["channel"] is None and world.saved["message_id"] is None
        reply = world.j.of("inter.edit_original_message")[-1][3]
        assert reply["embed"].description == "**O Canal de pedir música foi resetado com sucesso.**"
        assert reply["components"] == []
        edit = world.j.of("message.edit")[0][2]
        assert edit["content"] == f"Canal de pedir música foi resetado pelo membro {ACTOR_MENTION}."
        assert edit["embed"] is None
        (button,) = edit["components"]
        assert (button.label, button.custom_id) == ("Reconfigurar este canal", "musicplayer_request_channel")
        assert world.j.of("thread.edit")[0][2] == {"archived": True, "reason": "Player resetado por Autor#0001."}
        assert message.id == 555

    def test_only_channel_and_message_id_are_cleared(self, world):
        configured(world)
        before = {k: v for k, v in world.db.doc.items() if k != "player_controller"}
        before_pc = {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")}
        world.reset()
        assert {k: v for k, v in world.db.doc.items() if k != "player_controller"} == before
        assert {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")} == before_pc
        assert len(world.db.updates) == 1

    @pytest.mark.parametrize("answer", [None, "não"])
    def test_default_and_no_do_not_delete_the_channel(self, world, answer):
        configured(world)
        world.reset(delete=answer)
        assert world.j.of("channel.delete") == []

    def test_yes_deletes_the_channel_and_leaves_the_message_alone(self, world):
        configured(world)
        world.reset(delete="sim")
        assert world.j.of("channel.delete") == [("channel.delete", "#pedidos", "Player resetado por: Autor#0001")]
        assert world.j.of("message.edit") == [] and world.j.of("thread.edit") == []
        names = world.j.names()
        assert names.index("db.update") < names.index("channel.delete"), "banco limpo antes de apagar no Discord"

    def test_missing_message_is_not_an_error(self, world):
        world.db.doc["player_controller"].update({"channel": "22", "message_id": "404"})
        world.reset()
        assert world.saved["channel"] is None and world.j.of("message.edit") == []

    def test_player_is_reset_after_the_reply_and_before_the_discord_cleanup(self, world):
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
            "db.update",
            "inter.edit_original_message",
            "player.process_hint",
            "player.invoke_np",
            "message.edit",
        ]
        assert player.static is False and player.message is None and player.text_channel is world.lobby
        assert world.j.of("player.invoke_np") == [("player.invoke_np", True)]

    def test_discord_failure_after_the_database_was_cleared_is_reported_as_a_partial_error(self, world):
        message = configured(world)
        message.fail_edit = RuntimeError("falha simulada")
        text = error_text(world.reset)
        assert text == (
            "**O canal de pedir música foi resetado da base de dados mas ocorreu um erro no processo:** "
            "```py\nRuntimeError('falha simulada')```"
        )
        assert world.saved["channel"] is None, "o banco JÁ foi limpo (ordem banco × Discord)"

    def test_channel_delete_failure_is_also_a_partial_error(self, world):
        configured(world)
        world.text.fail_delete = disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
        assert "foi resetado da base de dados" in error_text(world.reset, delete="sim")
        assert world.saved["channel"] is None


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

    def test_no_reply_when_the_command_was_used_inside_the_post_itself(self, world):
        post = self.post(world)
        world.bot.channels[11] = post  # canal do comando == o post
        world.reset()
        assert world.j.of("inter.edit_original_message") == []

    def test_active_player_is_detached_from_the_post(self, world):
        self.post(world)
        player = FakePlayer(world.j, world.guild, world.forum, static=True, message=object())
        world.bot.music.players[GUILD_ID] = player
        world.reset()
        assert (player.static, player.message, player.text_channel) == (False, None, world.lobby)
        assert world.j.of("player.process_hint") and world.j.of("player.invoke_np") == [("player.invoke_np", True)]

    def test_forum_reset_clears_channel_and_message_id_in_the_database(self, world):
        """E4c (era INVERTER_APOS_E4C): o reset de fórum passa a limpar `channel`/`message_id` — comando e painel."""
        self.post(world)
        before = {k: v for k, v in world.db.doc.items() if k != "player_controller"}
        world.reset()
        assert world.saved["channel"] is None and world.saved["message_id"] is None
        assert len(world.db.updates) == 1
        assert {k: v for k, v in world.db.doc.items() if k != "player_controller"} == before, "só channel/message_id"
        assert world.j.of("channel.delete"), "o post continua sendo apagado"

    def test_forum_reset_still_clears_the_database_when_the_player_is_active(self, world):
        self.post(world)
        world.bot.music.players[GUILD_ID] = FakePlayer(world.j, world.guild, world.forum, static=True, message=object())
        world.reset()
        assert world.saved["channel"] is None and world.saved["message_id"] is None


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

    def test_cooldown_and_concurrency_are_one_use_per_20_seconds_and_one_run_per_guild(self):
        cd, mc = ms.MusicSettings.setup_cd, ms.MusicSettings.setup_mc
        assert (cd._cooldown.rate, cd._cooldown.per, cd._type) == (1, 20.0, commands.BucketType.guild)
        assert (mc.number, mc.per, mc.wait) == (1, commands.BucketType.guild, False)
        for name in ("setup_legacy", "reset_legacy"):
            command = getattr(ms.MusicSettings, name)
            assert (command._buckets._cooldown.rate, command._buckets._cooldown.per) == (1, 20.0), name
            assert (command._max_concurrency.number, command._max_concurrency.wait) == (1, False), name
        for name in ("setup", "reset"):
            command = getattr(ms.MusicSettings, name)
            assert command.default_member_permissions.manage_guild is True, name
            assert command._max_concurrency.number == 1

    def test_permission_checks_and_aliases(self):
        setup, reset = ms.MusicSettings.setup_legacy, ms.MusicSettings.reset_legacy
        assert setup.aliases == ["songrequestchannel", "sgrc"] and reset.aliases == []
        assert len(setup.checks) == 1, "só o usuário precisa de Gerenciar Servidor"
        assert len(reset.checks) == 2, "reset exige também manage_threads do bot (bot_has_guild_permissions)"


class TestPermissionMessageIsByteExact:
    """Regressão da extração (achada pelo Second Opinion): a cor ANSI perdeu o byte ESC (0x1B). Igualdade exata."""

    def test_text_channel_message_has_the_esc_bytes_and_the_exact_layout(self, world):
        world.text._perms = perms(view_channel=True, manage_permissions=True)
        text = error_text(world.setup, target=world.text)
        assert text == ansi_permissions_message("<#22>", world.text, ("send_messages", "embed_links"))
        assert text.count(ESC) == 4, "duas permissões => dois pares ESC[0;33m … ESC[0m"
        assert f"{ESC}[0;33mEnviar mensagem{ESC}[0m" in text and f"{ESC}[0;33mInserir links{ESC}[0m" in text

    def test_voice_and_stage_use_the_same_layout(self, world):
        for channel in (world.voice, world.stage):
            channel._perms = perms(view_channel=True, manage_permissions=True, send_messages=True)
            text = error_text(world.setup, target=channel)
            assert text == ansi_permissions_message(f"<#{channel.id}>", channel, ("embed_links",))

    def test_forum_message_has_the_esc_bytes(self, world):
        world.forum._perms = perms(
            view_channel=True, send_messages=True, send_messages_in_threads=True, manage_threads=True
        )
        modal_answer(world, "Pedidos do bot")
        text = error_text(world.setup, target=world.forum)
        assert text == ansi_permissions_message("<#55>", world.forum, ("embed_links",))

    def test_the_unit_function_in_the_shared_module_is_byte_exact_too(self, world):
        from utils.music import request_channel

        world.text._perms = perms(view_channel=True)
        with pytest.raises(GenericError) as raised:
            request_channel.check_channel_perm(world.text)
        assert raised.value.text == ansi_permissions_message("<#22>", world.text, ("send_messages", "embed_links"))

    def test_the_command_module_and_the_shared_module_agree_on_the_message(self, world):
        """Se o cog voltar a ter uma cópia própria da checagem, as duas têm de produzir os mesmos bytes."""
        import modules.music_settings as cog
        from utils.music import request_channel

        world.text._perms = perms(view_channel=True)
        messages = []
        for check in (getattr(cog, "check_channel_perm", None), request_channel.check_channel_perm):
            if check is None:
                continue
            with pytest.raises(GenericError) as raised:
                check(world.text)
            messages.append(raised.value.text)
        assert len(set(messages)) == 1 and ESC in messages[0]

"""Caracterização (VERDE contra o código ATUAL) de /setup e /reset — modules/music_settings.py:375-1010.

Objetivo: congelar o comportamento antes de extrair a lógica para `utils/music/request_channel.py` (E4c, opção A).
Mede efeitos no Discord e no banco, a ORDEM entre eles, mensagens de erro e limites. Nada aqui corrige defeitos:
comportamentos ruins estão registrados de propósito e marcados `INVERTER_APOS_E4C` quando a E4c vai corrigi-los.
"""

import asyncio

import pytest

import empiremuse.cogs.music_settings as ms
from tests.support.canal_de_pedidos import (
    BOT_MENTION,
    CommandInter,
    ComponentInter,
    FakeBot,
    FakeCategory,
    FakeDB,
    FakeForum,
    FakeGuild,
    FakeMessage,
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


def click(world, custom_id, values=None, event="button_click"):
    """Enfileira a interação que o `wait_for` entregará (ids terminam em _777, o id da interação do comando)."""
    interaction = ComponentInter(world.j, world.bot, world.guild, custom_id, values)
    world.bot.script.setdefault(event, []).append(interaction)
    return interaction


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


def configured(world, thread=True):
    """Canal de pedidos #pedidos (22) com a mensagem 555 (e thread) gravados no banco."""
    message = world.text.add_message(555, world.guild.me, FakeThreadInfo(world.j, "song-requests") if thread else None)
    world.db.doc["player_controller"].update({"channel": "22", "message_id": "555"})
    return message


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

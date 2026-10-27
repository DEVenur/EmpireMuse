"""``send_idle_embed`` só fixa a mensagem do controle com a permissão FIXAR MENSAGENS (``pin_messages``), não com ``manage_messages``.

Em 2025 o Discord separou "fixar mensagens" de "gerenciar mensagens" (disnake 2.12 tem ``Permissions.pin_messages``). O convite agora pede a
nova permissão; a guarda do ``pin`` tem de olhar a mesma. Fakes com ``spec`` (os ``isinstance`` do código valem); nada de rede.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils.others import send_idle_embed

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

CANAL = 123456789012345678


def alvo(permissoes: disnake.Permissions, *, fixada: bool = False):
    canal = MagicMock(spec=disnake.TextChannel)
    canal.id = CANAL
    mensagem = MagicMock(spec=disnake.Message)
    mensagem.channel = canal
    mensagem.guild_id = 1
    mensagem.pinned = fixada
    mensagem.edit = AsyncMock()
    mensagem.pin = AsyncMock()
    eu = MagicMock()
    eu.display_avatar.replace.return_value.url = "https://cdn.exemplo/avatar.png"
    eu.guild_permissions = permissoes
    mensagem.author = eu
    mensagem.guild = SimpleNamespace(me=eu, id=1)
    return mensagem


def bot_falso():
    return SimpleNamespace(
        music=SimpleNamespace(nodes={}),
        get_color=lambda *a: 0,
        get_global_command_named=lambda *a, **k: None,
    )


async def rodar(permissoes, **kwargs):
    mensagem = alvo(permissoes, **kwargs)
    dados = {"player_controller": {"channel": str(CANAL), "fav_links": {}}}

    await send_idle_embed(mensagem, "", bot=bot_falso(), guild_data=dados)

    return mensagem


class TestFixarMensagens:
    async def test_with_pin_messages_and_without_manage_messages_the_message_is_pinned(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=True, manage_messages=False))

        mensagem.pin.assert_awaited_once()

    async def test_with_manage_messages_but_without_pin_messages_the_message_is_not_pinned(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=False, manage_messages=True))

        mensagem.pin.assert_not_awaited()

    async def test_with_both_the_message_is_pinned(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=True, manage_messages=True))

        mensagem.pin.assert_awaited_once()

    async def test_with_neither_the_message_is_not_pinned(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=False, manage_messages=False))

        mensagem.pin.assert_not_awaited()

    async def test_an_already_pinned_message_is_not_pinned_again(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=True), fixada=True)

        mensagem.pin.assert_not_awaited()

    async def test_the_message_is_still_returned_and_edited_either_way(self):
        mensagem = await rodar(disnake.Permissions(pin_messages=False, manage_messages=False))

        mensagem.edit.assert_awaited_once()

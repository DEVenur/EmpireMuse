# -*- coding: utf-8 -*-
"""Canal de pedir música (song request): lógica do ``/setup`` e do ``/reset`` fora da interação do Discord.

Extraída de ``modules/music_settings.py`` SEM mudar comportamento (inclusive a ordem entre banco e Discord e os
defeitos já registrados na caracterização). O cog continua dono da interação (selects, botões, modais, timeouts);
os pontos em que a UI se mistura à lógica entram como callbacks:

- ``ask_forum_title(título_atual)``: pergunta/define o título do post de fórum; devolve ``None`` se o tempo esgotou.
- ``notify(evento)``: avisa a UI durante o reset (``"forum_deleted"`` e ``"reset_done"``).

``actor`` é quem executa a ação (precisa de ``id`` — usado no reset com deletar —, ``mention`` e ``str()``; no comando é
``inter.author``).
``send_idle_embed`` é injetável para o cog poder substituí-lo (testes) sem que este módulo conheça o cog.
"""
from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any, Awaitable, Callable, NamedTuple, Optional, Union

import disnake

from utils.db import DBModel
from utils.music.converters import perms_translations
from utils.music.errors import GenericError
from utils.others import send_idle_embed as default_send_idle_embed

if TYPE_CHECKING:
    from utils.client import BotCore
    from utils.music.models import LavalinkPlayer

# Nomes CANÔNICOS de ``disnake.Permissions`` (a iteração devolve ``view_channel`` e ``send_messages``; os aliases
# ``read_messages`` e ``create_forum_threads`` nunca apareciam e a falta dessas permissões passava batido).
channel_perms = ("send_messages", "embed_links", "view_channel")

thread_perms = ("send_messages_in_threads", "embed_links", "view_channel")

forum_perms = ("send_messages", "send_messages_in_threads", "embed_links", "view_channel")

AskForumTitle = Callable[[str], Awaitable[Optional[str]]]
Notify = Callable[[str], Awaitable[None]]


class RequestChannelResult(NamedTuple):
    channel: Any
    message: Any


def missing_channel_permissions(channel: Union[disnake.StageChannel, disnake.VoiceChannel, disnake.ForumChannel, disnake.TextChannel, disnake.Thread]) -> list[str]:
    """Nomes canônicos das permissões do bot que faltam no canal (post/thread: confere o canal pai)."""

    if isinstance(channel, disnake.ForumChannel):
        return [p for p, v in channel.permissions_for(channel.guild.me) if p in forum_perms and not v]

    if isinstance(channel, disnake.Thread):
        return [p for p, v in channel.parent.permissions_for(channel.guild.me) if p in thread_perms and not v]

    return [p for p, v in channel.permissions_for(channel.guild.me) if p in channel_perms and not v]


def check_channel_perm(channel: Union[disnake.StageChannel, disnake.VoiceChannel, disnake.ForumChannel, disnake.TextChannel]):

    missing_perms = missing_channel_permissions(channel)

    if missing_perms:
        raise GenericError(
            f"**{channel.guild.me.mention} não possui as seguintes permissões necessárias no canal {channel.mention}** ```ansi\n" +
            "\n".join(f"\x1b[0;33m{perms_translations.get(p, p)}\x1b[0m" for p in missing_perms) + "```")


# ============================================================================ preparo

def build_channel_kwargs(guild: disnake.Guild) -> dict:
    """Overwrite do bot nos canais criados/editados pelo setup."""
    perms_dict = {
        "embed_links": True,
        "send_messages": True,
        "send_messages_in_threads": True,
        "read_messages": True,
        "create_public_threads": True,
        "read_message_history": True,
        "manage_messages": True,
        "manage_channels": True,
        "attach_files": True,
    }

    if guild.me.guild_permissions.administrator:
        perms_dict["manage_permissions"] = True

    return {
        "overwrites": {
            guild.me: disnake.PermissionOverwrite(**perms_dict)
        }
    }


async def find_current_request_message(bot: BotCore, guild: disnake.Guild, guild_data: dict):
    """(player ativo ou None, mensagem atual do canal de pedidos ou None): player estático primeiro, depois o banco."""
    original_message = None

    try:
        player: LavalinkPlayer = bot.music.players[guild.id]
        if player.static:
            original_message = player.message
    except KeyError:
        player = None

    if not original_message:

        try:
            channel_db = bot.get_channel(int(guild_data["player_controller"]["channel"])) or \
                         await bot.fetch_channel(int(guild_data["player_controller"]["channel"]))
            original_message = await channel_db.fetch_message(int(guild_data["player_controller"]["message_id"]))
        except:
            pass

    return player, original_message


def ensure_can_create_channel(bot: BotCore, guild: disnake.Guild) -> None:
    if not guild.me.guild_permissions.manage_channels:
        raise GenericError(f"**O bot {bot.user.mention} não possui permissão de gerenciar canais pra criar um novo canal.**")


async def create_request_channel(bot: BotCore, parent: Union[disnake.CategoryChannel, disnake.Guild], kind: str,
                                 channel_kwargs: dict):
    """Cria o canal do bot (``kind``: ``text``, ``voice`` ou ``stage``) em ``parent`` (categoria ou servidor)."""
    name = f"{bot.user.name} player controller"
    if kind == "voice":
        return await parent.create_voice_channel(name, **channel_kwargs)
    if kind == "stage":
        return await parent.create_stage_channel(name, **channel_kwargs)
    return await parent.create_text_channel(name, **channel_kwargs)


async def _archive_previous_message(original_message, target, actor, embed_archived):

    if original_message and original_message.channel != target and original_message.guild.id == target.guild.id:

        try:
            if isinstance(original_message.channel.parent, disnake.ForumChannel):
                await original_message.thread.delete(reason=f"Player reconfigurado por {actor}.")
                return
        except AttributeError:
            pass
        except Exception:
            traceback.print_exc()
            return

        try:
            await original_message.edit(content=None, embed=embed_archived, view=None)
        except:
            pass

        try:
            await original_message.thread.edit(
                archived=True,
                locked=True,
                reason=f"Player reconfigurado por {actor}."
            )
        except:
            pass

    else:
        return original_message


# ============================================================================ setup

def validate_request_target(bot: BotCore, guild: disnake.Guild, target, *, existing_channel: bool = True) -> None:
    """Checagens do ``/setup`` que não têm efeito colateral (``GenericError`` na primeira que falhar).

    É a primeira etapa de ``apply_request_channel``; o painel a chama antes de criar a tarefa para responder 422 na hora.
    """
    if target == guild.public_updates_channel:
        raise GenericError("**Você não pode usar um canal de atualizações do discord.**")

    if target == guild.rules_channel:
        raise GenericError("**Você não pode usar um canal de regras.**")

    check_channel_perm(target)

    if isinstance(target, disnake.ForumChannel):

        if not target.permissions_for(guild.me).create_forum_threads:
            raise GenericError(f"**{bot.user.mention} não possui permissão para postar no canal {target.mention}.**")

        return

    if existing_channel and not guild.me.guild_permissions.administrator and not target.permissions_for(guild.me).manage_permissions:
        raise GenericError(f"**{guild.me.mention} não possui permissão de administrador ou permissão de "
                           f"gerenciar permissões do canal {target.mention}** para editar as permissões "
                           f"necessárias para o sistema de pedir música funcionar devidamente.\n\n"
                           f"Caso não queira fornecer a permissão de administrador ou editar as permissões do"
                           f" canal {target.mention} para me permitir gerenciar permissões do canal. Você pode usar o comando "
                           f"sem selecionar um canal de destino.")

    if not target.permissions_for(guild.me).read_messages:
        raise GenericError(f"{bot.user.mention} permissão para ler mensagens no canal {target.mention}")


async def apply_request_channel(
        bot: BotCore, guild: disnake.Guild, actor: Any, target, *, existing_channel: bool, purge: bool,
        channel_kwargs: dict, channel_name: str, original_message, player, guild_data: dict,
        ask_forum_title: Optional[AskForumTitle] = None, send_idle_embed=default_send_idle_embed,
) -> Optional[RequestChannelResult]:
    """Configura ``target`` como canal de pedidos e grava no banco (passos pós-escolha do ``/setup``).

    Devolve ``None`` se ``ask_forum_title`` informou que o tempo esgotou (nada foi gravado).
    """
    embed_archived = disnake.Embed(
        description=f"**Este canal de pedir música foi reconfigurado pelo membro {actor.mention}.**",
        color=bot.get_color(guild.me)
    )

    validate_request_target(bot, guild, target, existing_channel=existing_channel)

    if isinstance(target, disnake.ForumChannel):

        channel_kwargs.clear()

        if ask_forum_title:
            channel_name = await ask_forum_title(channel_name)
            if channel_name is None:
                return None

        thread = None
        message = None

        for t in target.threads:
            if t.owner_id == bot.user.id:
                try:
                    message = await t.fetch_message(t.id)
                except disnake.NotFound:
                    continue
                thread = t
                thread_kw = {}
                if thread.locked and target.permissions_for(target.guild.me).manage_threads:
                    thread_kw.update({"locked": False, "archived": False})
                elif thread.archived:
                    thread_kw["archived"] = False
                if thread_kw:
                    await t.edit(**thread_kw)
                break

        if not thread and guild.me.guild_permissions.read_message_history:
            async for t in target.archived_threads(limit=100):
                if t.owner_id == bot.user.id:
                    try:
                        message = await t.fetch_message(t.id)
                    except disnake.NotFound:
                        continue
                    thread = t
                    thread_kw = {}
                    if thread.locked and target.permissions_for(target.guild.me).manage_threads:
                        thread_kw.update({"locked": False, "archived": False})
                    elif thread.archived:
                        thread_kw["archived"] = False
                    if thread_kw:
                        await t.edit(**thread_kw)
                    break

        if not thread:

            if not target.permissions_for(guild.me).manage_threads:
                raise GenericError(
                    f"**{bot.user.mention} não possui permissão de gerenciar tópicos no canal {target.mention}.**\n"
                    f"`Nota: Você pode me conceder temporariamente essa permissão e após usar o comando novamente "
                    f"você pode remover essa permissão.`")

            """if not target.permissions_for(guild.me).create_forum_threads:
                raise GenericError(
                    f"**{bot.user.mention} não possui permissão para postar no canal {target.mention}.**")"""

            thread_wmessage = await target.create_thread(
                name=channel_name,
                content="Post para pedido de músicas.",
                auto_archive_duration=10080,
                slowmode_delay=5,
            )
            message = thread_wmessage.message

        message = await send_idle_embed(target=message, bot=bot, force=True,
                                        guild_data=guild_data)

        target = message.channel

        await _archive_previous_message(original_message, target, actor, embed_archived)

    else:

        if purge:
            await target.purge(limit=100, check=lambda m: m.author != guild.me or not m.thread)

        message = await _archive_previous_message(original_message, target, actor, embed_archived)

        if not message:

            async for m in target.history(limit=100):

                if m.author == guild.me and m.thread:
                    message = m
                    break

    if existing_channel:
        try:
            await target.edit(**channel_kwargs)
        except:
            traceback.print_exc()

    channel = target

    message = await _switch_player_and_thread(bot, guild, actor, channel, message, player, guild_data, send_idle_embed)

    guild_data['player_controller']['channel'] = str(channel.id)
    guild_data['player_controller']['message_id'] = str(message.id)
    await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

    return RequestChannelResult(channel, message)


async def _switch_player_and_thread(bot, guild, actor, channel, message, player, guild_data, send_idle_embed):
    """Religa o player ativo ao novo canal e garante a thread "Song-Requests"; devolve a mensagem final."""

    if player and player.text_channel != channel:
        if player.static:
            try:
                await player.message.thread.edit(
                    archived=True,
                    locked=True,
                    reason=f"Player reconfigurado por {actor}."
                )
            except:
                pass
        else:
            try:
                await player.message.delete()
            except:
                pass
        if not message or message.channel.id != channel.id:
            message = await send_idle_embed(channel, bot=bot, force=True, guild_data=guild_data)
        player.message = message
        player.static = True
        player.text_channel = channel
        player.setup_hints()
        player.setup_features()
        await player.invoke_np(force=True)

    elif not message or message.channel.id != channel.id:
        message = await send_idle_embed(channel, bot=bot, force=True, guild_data=guild_data)

    if isinstance(channel, disnake.TextChannel):
        if not message.thread:
            if channel.permissions_for(guild.me).create_public_threads:
                await message.create_thread(name="Song-Requests", auto_archive_duration=10080)
        else:
            thread_kw = {}
            if message.thread.locked and message.thread.permissions_for(guild.me).manage_threads:
                thread_kw.update({"locked": False, "archived": False})
            elif message.thread.archived and message.thread.owner_id == bot.user.id:
                thread_kw["archived"] = False
            if thread_kw:
                await message.thread.edit(reason=f"Song request reativado por: {actor}.", **thread_kw)
    elif player and isinstance(channel, (disnake.VoiceChannel, disnake.StageChannel)) and player.guild.me.voice.channel != channel:
        await player.connect(channel.id)

    return message


# ============================================================================ reset

def ensure_can_reset(guild: disnake.Guild) -> None:
    if not guild.me.guild_permissions.manage_threads:
        raise GenericError(f"Não tenho permissão de **{perms_translations['manage_threads']}** no servidor.")


async def find_request_channel(bot: BotCore, guild_id: int, guild_data: dict):
    """Canal de pedidos configurado no banco (cache ou API); ``GenericError`` se não há/foi apagado/é de outro servidor."""
    try:
        channel = bot.get_channel(int(guild_data['player_controller']['channel'])) or \
                  await bot.fetch_channel(int(guild_data['player_controller']['channel']))
    except:
        channel = None

    if not channel or channel.guild.id != guild_id:
        raise GenericError(f"**Não há canais de pedido de música configurado no bot {bot.user.mention} (ou o canal foi deletado).**")

    return channel


async def _reset_player(player, channel_inter):
    player.static = False
    player.message = None
    player.text_channel = channel_inter
    player.process_hint()
    await player.invoke_np(force=True)


async def reset_request_channel(
        bot: BotCore, guild: disnake.Guild, actor: Any, channel, *, delete_channel: Optional[str], channel_inter,
        guild_data: dict, notify: Notify,
) -> None:
    """Passos do ``/reset`` depois de achar o canal. ``delete_channel == "sim"`` apaga o canal.

    Mantém a ordem original: nos canais comuns o banco é limpo ANTES de mexer no Discord.
    """
    try:
        if isinstance(channel.parent, disnake.ForumChannel):
            # E4c: o reset de fórum também limpa o banco (antes o apontamento ficava até o próximo uso).
            guild_data["player_controller"].update({
                "message_id": None,
                "channel": None
            })
            await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

            await channel.delete(reason=f"{actor.id} resetou player")
            await notify("forum_deleted")

            try:
                player: LavalinkPlayer = bot.music.players[guild.id]
            except KeyError:
                pass
            else:
                await _reset_player(player, channel_inter)

            return

    except AttributeError:
        pass

    try:
        original_message = await channel.fetch_message(int(guild_data["player_controller"]["message_id"]))
    except:
        original_message = None

    guild_data["player_controller"].update({
        "message_id": None,
        "channel": None
    })

    await bot.update_data(guild.id, guild_data, db_name=DBModel.guilds)

    await notify("reset_done")

    try:
        player: LavalinkPlayer = bot.music.players[guild.id]
    except KeyError:
        pass
    else:
        await _reset_player(player, channel_inter)

    try:
        if delete_channel == "sim":
            await channel.delete(reason=f"Player resetado por: {actor}")

        elif original_message:
            await original_message.edit(
                content=f"Canal de pedir música foi resetado pelo membro {actor.mention}.",
                embed=None, components=[
                    disnake.ui.Button(label="Reconfigurar este canal", emoji="💠",
                                      custom_id="musicplayer_request_channel")
                ]
            )
            await original_message.thread.edit(archived=True, reason=f"Player resetado por {actor}.")
    except Exception as e:
        traceback.print_exc()
        raise GenericError(
            "**O canal de pedir música foi resetado da base de dados mas ocorreu um erro no processo:** "
            f"```py\n{repr(e)}```"
        )

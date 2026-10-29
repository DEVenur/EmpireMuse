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

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, NamedTuple, Optional, Union

import disnake

from empiremuse.utils.music.converters import perms_translations
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.others import send_idle_embed as default_send_idle_embed
from empiremuse.utils.server_request import RequestConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore
    from empiremuse.utils.music.models import LavalinkPlayer


def config_as_data(config: RequestConfig) -> dict:
    """O canal de pedidos no formato que o ``send_idle_embed`` lê (``player_controller.channel``/``message_id`` como texto)."""
    return {
        "player_controller": {
            "channel": str(config.channel) if config.channel else None,
            "message_id": str(config.message_id) if config.message_id else None,
        }
    }


async def ensure_panel_bot(bot: BotCore, guild_id: int) -> None:
    """Só o bot do painel configura ou reseta o canal de pedidos: ele é o autor da mensagem do canal (S-V11)."""
    if not await bot.pool.servers.request.is_panel_bot(guild_id, bot):
        raise GenericError("**Só o bot do painel do servidor pode configurar ou resetar o canal de pedidos.**")


# Nomes CANÔNICOS de ``disnake.Permissions`` (a iteração devolve ``view_channel`` e ``send_messages``; os aliases
# ``read_messages`` e ``create_forum_threads`` nunca apareciam e a falta dessas permissões passava batido).
channel_perms = ("send_messages", "embed_links", "view_channel")

thread_perms = ("send_messages_in_threads", "embed_links", "view_channel")

forum_perms = ("send_messages", "send_messages_in_threads", "embed_links", "view_channel")


class MissingManagePermissions(GenericError):
    """O bot não tem Administrador nem Gerenciar permissões no canal escolhido (o painel mapeia por este tipo)."""


AskForumTitle = Callable[[str], Awaitable[Optional[str]]]
Notify = Callable[[str], Awaitable[None]]


class RequestChannelResult(NamedTuple):
    channel: Any
    message: Any


def missing_channel_permissions(
    channel: Union[
        disnake.StageChannel, disnake.VoiceChannel, disnake.ForumChannel, disnake.TextChannel, disnake.Thread
    ],
) -> list[str]:
    """Nomes canônicos das permissões do bot que faltam no canal (post/thread: confere o canal pai)."""

    if isinstance(channel, disnake.ForumChannel):
        return [p for p, v in channel.permissions_for(channel.guild.me) if p in forum_perms and not v]

    if isinstance(channel, disnake.Thread):
        return [p for p, v in channel.parent.permissions_for(channel.guild.me) if p in thread_perms and not v]

    return [p for p, v in channel.permissions_for(channel.guild.me) if p in channel_perms and not v]


def check_channel_perm(
    channel: Union[disnake.StageChannel, disnake.VoiceChannel, disnake.ForumChannel, disnake.TextChannel],
):
    missing_perms = missing_channel_permissions(channel)

    if missing_perms:
        raise GenericError(
            f"**{channel.guild.me.mention} não possui as seguintes permissões necessárias no canal {channel.mention}** ```ansi\n"
            + "\n".join(f"\x1b[0;33m{perms_translations.get(p, p)}\x1b[0m" for p in missing_perms)
            + "```"
        )


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

    return {"overwrites": {guild.me: disnake.PermissionOverwrite(**perms_dict)}}


async def find_current_request_message(bot: BotCore, guild: disnake.Guild, config: RequestConfig):
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
            channel_db = bot.get_channel(config.channel) or await bot.fetch_channel(config.channel)  # type: ignore[arg-type]
            original_message = await channel_db.fetch_message(config.message_id)  # type: ignore[arg-type]
        except Exception:
            pass

    return player, original_message


def ensure_can_create_channel(bot: BotCore, guild: disnake.Guild) -> None:
    if not guild.me.guild_permissions.manage_channels:
        raise GenericError(
            f"**O bot {bot.user.mention} não possui permissão de gerenciar canais pra criar um novo canal.**"
        )


async def create_request_channel(
    bot: BotCore, parent: Union[disnake.CategoryChannel, disnake.Guild], kind: str, channel_kwargs: dict
):
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
            logger.exception("Falha em _archive_previous_message")
            return

        try:
            await original_message.edit(content=None, embed=embed_archived, view=None)
        except Exception:
            pass

        try:
            await original_message.thread.edit(archived=True, locked=True, reason=f"Player reconfigurado por {actor}.")
        except Exception:
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

    if (
        existing_channel
        and not guild.me.guild_permissions.administrator
        and not target.permissions_for(guild.me).manage_permissions
    ):
        raise MissingManagePermissions(
            f"**{guild.me.mention} não possui permissão de administrador ou permissão de "
            f"gerenciar permissões do canal {target.mention}** para editar as permissões "
            f"necessárias para o sistema de pedir música funcionar devidamente.\n\n"
            f"Caso não queira fornecer a permissão de administrador ou editar as permissões do"
            f" canal {target.mention} para me permitir gerenciar permissões do canal. Você pode usar o comando "
            f"sem selecionar um canal de destino."
        )


async def apply_request_channel(
    bot: BotCore,
    guild: disnake.Guild,
    actor: Any,
    target,
    *,
    existing_channel: bool,
    purge: bool,
    channel_kwargs: dict,
    channel_name: str,
    original_message,
    player,
    config: RequestConfig,
    ask_forum_title: Optional[AskForumTitle] = None,
    send_idle_embed=default_send_idle_embed,
) -> Optional[RequestChannelResult]:
    """Configura ``target`` como canal de pedidos e grava no banco (passos pós-escolha do ``/setup``).

    Devolve ``None`` se ``ask_forum_title`` informou que o tempo esgotou (nada foi gravado).
    """
    await ensure_panel_bot(bot, guild.id)
    guild_data = config_as_data(config)

    embed_archived = disnake.Embed(
        description=f"**Este canal de pedir música foi reconfigurado pelo membro {actor.mention}.**",
        color=bot.get_color(guild.me),
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
                    f"você pode remover essa permissão.`"
                )

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

        message = await send_idle_embed(target=message, bot=bot, force=True, guild_data=guild_data)

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

    if existing_channel and channel_kwargs:
        try:
            await target.edit(**channel_kwargs)
        except Exception:
            logger.exception("Falha em apply_request_channel")

    channel = target

    message = await _switch_player_and_thread(bot, guild, actor, channel, message, player, guild_data, send_idle_embed)

    # canal e mensagem juntos, no documento do servidor; se mudaram desde que o comando leu, ServerConfigConflict (nada é sobrescrito)
    await bot.pool.servers.request.set(guild.id, channel.id, message.id, expected=config.current)

    await _rebind_other_players(bot, channel, message)

    return RequestChannelResult(channel, message)


async def _switch_player_and_thread(bot, guild, actor, channel, message, player, guild_data, send_idle_embed):
    """Religa o player ativo ao novo canal e garante a thread "Song-Requests"; devolve a mensagem final."""

    if player and player.text_channel != channel:
        if player.static:
            try:
                await player.message.thread.edit(
                    archived=True, locked=True, reason=f"Player reconfigurado por {actor}."
                )
            except Exception:
                pass
        else:
            try:
                await player.message.delete()
            except Exception:
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
    elif (
        player
        and isinstance(channel, (disnake.VoiceChannel, disnake.StageChannel))
        and player.guild.me.voice.channel != channel
    ):
        await player.connect(channel.id)

    return message


# ============================================================================ reset


def ensure_can_reset(guild: disnake.Guild) -> None:
    if not guild.me.guild_permissions.manage_threads:
        raise GenericError(f"Não tenho permissão de **{perms_translations['manage_threads']}** no servidor.")


async def find_request_channel(bot: BotCore, guild_id: int, config: RequestConfig):
    """Canal de pedidos configurado no banco (cache ou API); ``GenericError`` se não há/foi apagado/é de outro servidor."""
    try:
        channel = bot.get_channel(config.channel) or await bot.fetch_channel(config.channel)  # type: ignore[arg-type]
    except Exception:
        channel = None

    if not channel or channel.guild.id != guild_id:
        raise GenericError(
            f"**Não há canais de pedido de música configurado no bot {bot.user.mention} (ou o canal foi deletado).**"
        )

    return channel


def _other_static_players(bot: BotCore, guild_id: int):
    """Os players estáticos dos OUTROS bots do pool: o canal é único, então eles também seguem o /setup e o /reset."""
    panel = getattr(bot.pool, "request_panel", None)
    return [(b, p) for b, p in panel.players(guild_id) if b is not bot] if panel else []


async def _rebind_other_players(bot: BotCore, channel, message) -> None:
    """Depois do /setup: os players dos outros bots passam a usar o novo canal e a mensagem do painel (que é do bot do painel)."""
    for other, player in _other_static_players(bot, channel.guild.id):
        try:
            player.text_channel = other.get_channel(channel.id) or channel
            player.message = message
            player.setup_hints()
            player.setup_features()
        except Exception:
            logger.exception("Falha ao religar o player de outro bot ao novo canal de pedidos")
    if panel := getattr(bot.pool, "request_panel", None):
        await panel.refresh(channel.guild.id, now=True)


async def _reset_other_players(bot: BotCore, guild_id: int, channel_inter) -> None:
    """Depois do /reset: os players dos outros bots deixam de ser estáticos, como o do bot do painel."""
    for other, player in _other_static_players(bot, guild_id):
        try:
            await _reset_player(player, other.get_channel(channel_inter.id) or channel_inter)
        except Exception:
            logger.exception("Falha ao resetar o player de outro bot")


async def _reset_player(player, channel_inter):
    player.static = False
    player.message = None
    player.text_channel = channel_inter
    player.process_hint()
    await player.invoke_np(force=True)


MSG_RESET_DISCORD_FAILED = (
    "**Não foi possível concluir o reset do canal de pedir música no Discord. "
    "A configuração foi mantida; confira as permissões do bot no canal e tente novamente.**"
)


async def _fetch_configured_message(channel, config: RequestConfig):
    """Mensagem do canal de pedidos registrada no banco; ``None`` se não existe mais ou o registro é inválido."""
    try:
        return await channel.fetch_message(config.message_id)
    except disnake.HTTPException, TypeError, ValueError:
        return None


async def _clear_in_discord(actor: Any, channel, delete_channel: Optional[str], config: RequestConfig) -> bool:
    """Apaga o post/canal ou devolve a mensagem ao estado "reconfigurar". ``True`` se era um post de fórum."""
    if isinstance(getattr(channel, "parent", None), disnake.ForumChannel):
        await channel.delete(reason=f"{actor.id} resetou player")
        return True

    original_message = await _fetch_configured_message(channel, config)

    if delete_channel == "sim":
        await channel.delete(reason=f"Player resetado por: {actor}")

    elif original_message:
        await original_message.edit(
            content=f"Canal de pedir música foi resetado pelo membro {actor.mention}.",
            embed=None,
            components=[
                disnake.ui.Button(label="Reconfigurar este canal", emoji="💠", custom_id="musicplayer_request_channel")
            ],
        )
        if original_message.thread:
            await original_message.thread.edit(archived=True, reason=f"Player resetado por {actor}.")

    return False


async def reset_request_channel(
    bot: BotCore,
    guild: disnake.Guild,
    actor: Any,
    channel,
    *,
    delete_channel: Optional[str],
    channel_inter,
    config: RequestConfig,
    notify: Notify,
) -> None:
    """Passos do ``/reset`` depois de achar o canal. ``delete_channel == "sim"`` apaga o canal.

    Ordem: Discord primeiro, banco depois; só então o aviso (``notify``) e o reset do player. Se o Discord falhar, o
    banco continua intacto e o usuário recebe uma ``GenericError`` genérica (o detalhe vai para o log).
    """
    await ensure_panel_bot(bot, guild.id)

    try:
        was_forum = await _clear_in_discord(actor, channel, delete_channel, config)
    except Exception as exc:
        logger.error(
            "Reset do canal de pedidos: falha no Discord (servidor=%s, canal=%s): %s",
            guild.id,
            getattr(channel, "id", None),
            exc,
            exc_info=True,
        )
        raise GenericError(MSG_RESET_DISCORD_FAILED) from exc

    await bot.pool.servers.request.clear(guild.id, expected=config.current)

    await notify("forum_deleted" if was_forum else "reset_done")

    await _reset_other_players(bot, guild.id, channel_inter)

    try:
        player: LavalinkPlayer = bot.music.players[guild.id]
    except KeyError:
        return

    await _reset_player(player, channel_inter)

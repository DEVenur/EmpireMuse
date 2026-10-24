# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção até a KI-29b (song_requests, 310 linhas, e parse_song_request formam um fluxo coeso).
import asyncio
import datetime
import traceback
from typing import Union, Optional

import disnake
from disnake.ext import commands

from empiremuse.utils.client import BotCore
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.checks import (
    can_connect,
    check_player_perm,
)
from empiremuse.utils.music.converters import (
    time_format,
    fix_characters,
    URL_REG,
    YOUTUBE_VIDEO_REG,
    music_source_image,
)
from empiremuse.utils.music.errors import (
    GenericError,
    PoolException,
    parse_error,
    error_code_text,
    log_unexpected_error,
)
from empiremuse.utils.music.interactions import (
    SelectInteraction,
    ButtonInteraction,
)
from empiremuse.utils.music.models import (
    LavalinkPlayer,
)
from empiremuse.utils.others import (
    send_idle_embed,
    CustomContext,
    PlayerControls,
    string_to_file,
    song_request_buttons,
    update_inter,
)

# O corpo da classe usa estes nomes, então eles precisam existir neste módulo.
from empiremuse.music_cog.shared import (
    logger,
)


class SongRequestsMixin:
    @commands.Cog.listener("on_modal_submit")
    async def song_request_modal(self, inter: disnake.ModalInteraction):
        if inter.custom_id.startswith("modal_add_song"):
            try:
                query = inter.values["song_input"]
                position = inter.values["song_position"]

                try:
                    selected_fav = inter.values["fav_links"][0]
                except (KeyError, IndexError):
                    selected_fav = None

                try:
                    selected_integration = inter.values["integration_links"][0]
                except (KeyError, IndexError):
                    selected_integration = None

                multichoice_opts = []

                if query:
                    multichoice_opts.append(
                        disnake.SelectOption(
                            label="Nome/Link:",
                            emoji="🔍",
                            description=fix_characters(query, limit=45),
                            value="music_query",
                        )
                    )

                if selected_fav:
                    multichoice_opts.append(
                        disnake.SelectOption(
                            label="Favorito:",
                            emoji="⭐",
                            description=fix_characters(selected_fav[6:], 45),
                            value="music_fav",
                        )
                    )

                if selected_integration:
                    multichoice_opts.append(
                        disnake.SelectOption(
                            label="Integração:",
                            emoji="💠",
                            description=fix_characters(selected_integration[13:], 45),
                            value="music_integration",
                        )
                    )

                if not multichoice_opts:
                    raise GenericError("Você deve incluir pelo menos uma informação")

                if len(multichoice_opts) > 1:
                    view = SelectInteraction(user=inter.author, opts=multichoice_opts, timeout=30)

                    embed = disnake.Embed(
                        description="**Você usou dois itens na sua requisição...**\n"
                        f"Selecione uma opção para prosseguir (tempo limite: <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=30)).timestamp())}:R>).",
                        color=self.bot.get_color(inter.guild.me),
                    )

                    await inter.send(inter.author.mention, embed=embed, view=view, ephemeral=True)

                    await view.wait()

                    if not view.inter:
                        await inter.edit_original_message(
                            content=f"{inter.author.mention}, tempo esgotado!", embed=None, view=None
                        )
                        return

                    update_inter(inter, view.inter)

                    inter = view.inter

                    selected_opt = view.selected

                    await inter.response.defer(ephemeral=True)

                else:
                    selected_opt = multichoice_opts[0].value

                match selected_opt:
                    case "music_fav":
                        query = selected_fav
                    case "music_integration":
                        query = selected_integration

                kwargs = {
                    "query": query,
                    "position": int(position) if position else 0,
                    "options": False,
                    "manual_selection": True,
                    "server": None,
                    "force_play": "no",
                }

                await self.process_player_interaction(
                    interaction=inter,
                    command=self.bot.get_slash_command("play"),
                    kwargs=kwargs,
                )
            except Exception as e:
                self.bot.dispatch("interaction_player_error", inter, e)

    async def delete_message(self, message: disnake.Message, delay: int = None, ignore=False):
        if ignore:
            return

        try:
            is_forum = isinstance(message.channel.parent, disnake.ForumChannel)
        except AttributeError:
            is_forum = False

        if message.is_system() and is_forum:
            return

        if message.channel.permissions_for(message.guild.me).manage_messages or message.author.id == self.bot.user.id:
            try:
                await message.delete(delay=delay)
            except Exception:
                traceback.print_exc()

    @commands.Cog.listener("on_song_request")
    async def song_requests(self, ctx: Optional[CustomContext], message: disnake.Message):
        if ctx.command or message.mentions:
            return

        if message.author.bot and not isinstance(message.channel, disnake.StageChannel):
            return

        try:
            data = await self.bot.get_data(message.guild.id, db_name=DBModel.guilds)
        except AttributeError:
            return

        player: Optional[LavalinkPlayer] = self.bot.music.players.get(message.guild.id)

        if player and isinstance(message.channel, disnake.Thread) and not player.static:
            try:
                if player.text_channel.id != message.id:
                    return
            except AttributeError:
                return

            if not player.controller_mode:
                return

            text_channel = message.channel

        else:
            static_player = data["player_controller"]

            channel_id = static_player["channel"]

            if not channel_id:
                return

            if isinstance(message.channel, disnake.Thread):
                if isinstance(message.channel.parent, disnake.TextChannel):
                    if str(message.channel.parent.id) != channel_id:
                        return
                elif str(message.channel.id) != channel_id:
                    return
            elif str(message.channel.id) != channel_id:
                return

            try:
                text_channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
            except disnake.NotFound:
                text_channel = None

            if not text_channel:
                await self.reset_controller_db(message.guild.id, data)
                return

            if isinstance(text_channel, disnake.Thread):
                send_message_perm = text_channel.parent.permissions_for(message.guild.me).send_messages_in_threads
            else:
                send_message_perm = text_channel.permissions_for(message.guild.me).send_messages

            if not send_message_perm:
                return

            if not self.bot.intents.message_content:
                if self.song_request_cooldown.get_bucket(message).update_rate_limit():
                    return

                await message.channel.send(
                    message.author.mention,
                    embed=disnake.Embed(
                        description="Infelizmente não posso conferir o conteúdo de sua mensagem...\n"
                        "Tente adicionar música usando **/play** ou clique em um dos botões abaixo:",
                        color=self.bot.get_color(message.guild.me),
                    ),
                    components=song_request_buttons,
                    delete_after=20,
                )
                return

        if message.content.startswith("/") or message.is_system():
            await self.delete_message(message)
            return

        try:
            if isinstance(message.channel, disnake.Thread):
                if isinstance(message.channel.parent, disnake.ForumChannel):
                    if data["player_controller"]["channel"] != str(message.channel.id):
                        return
                    await self.delete_message(message)

        except AttributeError:
            pass

        msg = None
        error = None
        error_code = ""
        has_exception = None

        try:
            if message.author.bot:
                await self.delete_message(message)
                return

            if not message.content:
                if message.type == disnake.MessageType.thread_starter_message:
                    return

                if message.is_system():
                    await self.delete_message(message)
                    return

                try:
                    attachment = message.attachments[0]
                except IndexError:
                    await message.channel.send(
                        f"{message.author.mention} você deve enviar um link/nome da música.", delete_after=8
                    )
                    return

                else:
                    if attachment.size > 18000000:
                        await message.channel.send(
                            f"{message.author.mention} o arquivo que você enviou deve ter o tamanho inferior a 18mb.",
                            delete_after=8,
                        )
                        return

                    if attachment.content_type not in self.audio_formats:
                        await message.channel.send(
                            f"{message.author.mention} o arquivo que você enviou deve ter o tamanho inferior a 18mb.",
                            delete_after=8,
                        )
                        return

                    message.content = attachment.url

            try:
                await self.song_request_concurrency.acquire(message)
            except Exception:
                await message.channel.send(
                    f"{message.author.mention} você deve aguardar seu pedido de música anterior carregar...",
                )

                await self.delete_message(message)
                return

            message.content = message.content.strip("<>")

            urls = URL_REG.findall(message.content)

            if not urls:
                source = None

            else:
                source = False
                message.content = urls[0]

                if "&list=" in message.content:
                    view = ButtonInteraction(
                        user=message.author,
                        timeout=45,
                        buttons=[
                            disnake.ui.Button(label="Carregar apenas a música", emoji="🎵", custom_id="music"),
                            disnake.ui.Button(label="Carregar playlist", emoji="🎶", custom_id="playlist"),
                        ],
                    )

                    embed = disnake.Embed(
                        description="**O link contém vídeo com playlist.**\n"
                        f"Selecione uma opção em até <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=45)).timestamp())}:R> para prosseguir.\n"
                        f"-# Nota: Caso o link seja de uma playlist privada, apenas o vídeo do link atual será carregado.",
                        color=self.bot.get_color(message.guild.me),
                    )

                    msg = await message.channel.send(message.author.mention, embed=embed, view=view)

                    await view.wait()

                    try:
                        await view.inter.response.defer()
                    except Exception:
                        pass

                    if view.selected == "music":
                        message.content = YOUTUBE_VIDEO_REG.search(message.content).group()

            await self.parse_song_request(message, text_channel, data, response=msg, source=source)

        except GenericError as e:
            error = f"{message.author.mention}. {e}"

        except Exception as e:
            if isinstance(e, PoolException):
                return

            try:
                error_msg = parse_error(ctx, e, no_log=True)[0]
            except Exception:
                error_msg = None

            if error_msg:
                error = f"{message.author.mention}. {error_msg}"
            else:
                has_exception = e
                error_code = log_unexpected_error(logger, e, "pedido de música (song-request)")
                error = (
                    f"{message.author.mention} **ocorreu um erro ao tentar obter resultados para sua busca.**"
                    f"{error_code_text(error_code)}"
                )

        if error:
            await self.delete_message(message)

            try:
                if msg:
                    await msg.edit(content=error, embed=None, view=None)
                else:
                    await message.channel.send(error, delete_after=9)
            except Exception:
                traceback.print_exc()

        await self.song_request_concurrency.release(message)

        if has_exception and self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"]:
            cog = self.bot.get_cog("ErrorHandler")

            if not cog:
                return

            max_concurrency = cog.webhook_max_concurrency

            await max_concurrency.acquire(message)

            try:
                full_error_msg = cog.mask_token(
                    "".join(traceback.format_exception(type(has_exception), has_exception, has_exception.__traceback__))
                )

                embed = disnake.Embed(
                    title="Ocorreu um erro em um servidor (song-request):",
                    timestamp=disnake.utils.utcnow(),
                    description=f"Erro inesperado no pedido de música.{error_code_text(error_code)}",
                )

                embed.set_footer(
                    text=f"{message.author} [{message.author.id}]",
                    icon_url=message.author.display_avatar.with_static_format("png").url,
                )

                embed.add_field(
                    name="Servidor:",
                    inline=False,
                    value=f"```\n{disnake.utils.escape_markdown(ctx.guild.name)}\nID: {ctx.guild.id}```",
                )

                embed.add_field(name="Conteúdo do pedido de música:", inline=False, value=f"```\n{message.content}```")

                embed.add_field(
                    name="Canal de texto:",
                    inline=False,
                    value=f"```\n{disnake.utils.escape_markdown(ctx.channel.name)}\nID: {ctx.channel.id}```",
                )

                if vc := ctx.author.voice:
                    embed.add_field(
                        name="Canal de voz (user):",
                        inline=False,
                        value=f"```\n{disnake.utils.escape_markdown(vc.channel.name)}"
                        + (
                            f" ({len(vc.channel.voice_states)}/{vc.channel.user_limit})"
                            if vc.channel.user_limit
                            else ""
                        )
                        + f"\nID: {vc.channel.id}```",
                    )

                if vcbot := ctx.guild.me.voice:
                    if vcbot.channel != vc.channel:
                        embed.add_field(
                            name="Canal de voz (bot):",
                            inline=False,
                            value=f"{vc.channel.name}"
                            + (
                                f" ({len(vc.channel.voice_states)}/{vc.channel.user_limit})"
                                if vc.channel.user_limit
                                else ""
                            )
                            + f"\nID: {vc.channel.id}```",
                        )

                if ctx.guild.icon:
                    embed.set_thumbnail(url=ctx.guild.icon.with_static_format("png").url)

                await cog.send_webhook(
                    embed=embed,
                    file=string_to_file(
                        full_error_msg,
                        f"error_traceback_songrequest_{error_code}.txt"
                        if error_code
                        else "error_traceback_songrequest.txt",
                    ),
                )

            except Exception:
                traceback.print_exc()

            await asyncio.sleep(20)

            try:
                await max_concurrency.release(message)
            except Exception:
                pass

    async def parse_song_request(
        self,
        message: disnake.Message,
        text_channel,
        data,
        *,
        response=None,
        attachment: disnake.Attachment = None,
        source=None,
    ):
        if not message.author.voice:
            raise GenericError("Você deve entrar em um canal de voz para pedir uma música.")

        can_connect(
            channel=message.author.voice.channel,
            guild=message.guild,
            check_other_bots_in_vc=data["check_other_bots_in_vc"],
            bot=self.bot,
        )

        try:
            if message.guild.me.voice.channel != message.author.voice.channel:
                raise GenericError(
                    f"Você deve entrar no canal <#{message.guild.me.voice.channel.id}> para pedir uma música."
                )
        except AttributeError:
            pass

        try:
            message_id = int(data["player_controller"]["message_id"])
        except TypeError:
            message_id = None

        try:
            player = self.bot.music.players[message.guild.id]
            await check_player_perm(message, self.bot, message.channel, guild_data=data)
            destroy_message = True
        except KeyError:
            destroy_message = False
            player = await self.create_player(
                inter=message, bot=self.bot, guild=message.guild, channel=text_channel, guild_data=data
            )

        tracks, node = await self.get_tracks(message.content, message, message.author, source=source)
        tracks = await self.check_player_queue(message.author, self.bot, message.guild.id, tracks)

        if not player.message:
            try:
                cached_message = await text_channel.fetch_message(message_id)
            except Exception:
                cached_message = await send_idle_embed(message, bot=self.bot, guild_data=data)
                data["player_controller"]["message_id"] = str(cached_message.id)
                await self.bot.update_data(message.guild.id, data, db_name=DBModel.guilds)

            player.message = cached_message

        embed = disnake.Embed(color=self.bot.get_color(message.guild.me))

        try:
            components = [disnake.ui.Button(emoji="🎛️", label="Player-controller", url=player.message.jump_url)]
        except AttributeError:
            components = []

        if not isinstance(tracks, list):
            player.queue.extend(tracks.tracks)

            if isinstance(message.channel, disnake.Thread) and not isinstance(
                message.channel.parent, disnake.ForumChannel
            ):
                tcount = len(tracks.tracks)
                embed.description = (
                    f"✋ **⠂ Pedido por:** {message.author.mention}\n🎼 **⠂ Música{'s'[: tcount ^ 1]}:** `[{tcount}]`"
                )
                embed.set_thumbnail(url=tracks.tracks[0].thumb)
                embed.set_author(
                    name="⠂" + fix_characters(tracks.tracks[0].playlist_name, 35),
                    url=message.content,
                    icon_url=music_source_image(tracks.tracks[0].info["sourceName"]),
                )

                try:
                    embed.description += f"\n🔊 **⠂ Canal de voz:** {message.author.voice.channel.mention}"
                except AttributeError:
                    pass

                try:
                    self.bot.pool.enqueue_playlist_embed_cooldown.get_bucket(message).update_rate_limit()
                except Exception:
                    pass

                components.extend(
                    [
                        disnake.ui.Button(emoji="💗", label="Favoritar", custom_id=PlayerControls.embed_add_fav),
                        disnake.ui.Button(
                            emoji="➕", label="Adicionar na fila", custom_id=PlayerControls.embed_enqueue_playlist
                        ),
                    ]
                )

                if response:
                    await response.edit(content=None, embed=embed, components=components)
                else:
                    await message.reply(embed=embed, fail_if_not_exists=False, mention_author=False)

            else:
                player.set_command_log(
                    text=f"{message.author.mention} adicionou a playlist [`{fix_characters(tracks.data['playlistInfo']['name'], 20)}`]"
                    f"(<{tracks.tracks[0].playlist_url}>) `({len(tracks.tracks)})`.",
                    emoji="🎶",
                )
            if destroy_message:
                await self.delete_message(message)

        else:
            track = tracks[0]

            if track.info.get("sourceName") == "http":
                if track.title == "Unknown title":
                    if attachment:
                        track.info["title"] = attachment.filename
                    else:
                        track.info["title"] = track.uri.split("/")[-1]
                    track.title = track.info["title"]

                track.info["uri"] = ""

            player.queue.append(track)

            if isinstance(message.channel, disnake.Thread) and not isinstance(
                message.channel.parent, disnake.ForumChannel
            ):
                embed.description = (
                    f"💠 **⠂ Uploader:** `{track.author}`\n"
                    f"✋ **⠂ Pedido por:** {message.author.mention}\n"
                    f"⏰ **⠂ Duração:** `{time_format(track.duration) if not track.is_stream else '🔴 Livestream'}`"
                )

                try:
                    embed.description += f"\n🔊 **⠂ Canal de voz:** {message.author.voice.channel.mention}"
                except AttributeError:
                    pass

                try:
                    self.bot.pool.enqueue_track_embed_cooldown.get_bucket(message).update_rate_limit()
                except Exception:
                    pass

                components.extend(
                    [
                        disnake.ui.Button(emoji="💗", label="Favoritar", custom_id=PlayerControls.embed_add_fav),
                        disnake.ui.Button(
                            emoji="▶️",
                            label="Tocar" + (" agora" if (player.current and player.current.autoplay) else ""),
                            custom_id=PlayerControls.embed_forceplay,
                        ),
                        disnake.ui.Button(
                            emoji="➕", label="Adicionar na fila", custom_id=PlayerControls.embed_enqueue_track
                        ),
                    ]
                )

                embed.set_thumbnail(url=track.thumb)
                embed.set_author(
                    name=fix_characters(track.title, 35),
                    url=track.uri or track.search_uri,
                    icon_url=music_source_image(track.info["sourceName"]),
                )
                if response:
                    await response.edit(content=None, embed=embed, components=components)
                else:
                    await message.reply(
                        embed=embed, fail_if_not_exists=False, mention_author=False, components=components
                    )

            else:
                duration = time_format(tracks[0].duration) if not tracks[0].is_stream else "🔴 Livestream"
                player.set_command_log(
                    text=f"{message.author.mention} adicionou [`{fix_characters(tracks[0].title, 20)}`](<{tracks[0].uri or tracks[0].search_uri}>) `({duration})`.",
                    emoji="🎵",
                )
                if destroy_message:
                    await self.delete_message(message)

        if not player.is_connected:
            await self.do_connect(
                message, channel=message.author.voice.channel, check_other_bots_in_vc=data["check_other_bots_in_vc"]
            )

        if not player.current:
            await player.process_next()
        else:
            await player.update_message()

        await asyncio.sleep(1)

    async def interaction_message(
        self,
        inter: Union[disnake.Interaction, CustomContext],
        txt,
        emoji: str = "✅",
        rpc_update: bool = False,
        data: dict = None,
        store_embed: bool = False,
        force=False,
        defered=False,
        thumb=None,
        components=None,
    ):
        try:
            txt, txt_ephemeral = txt
        except Exception:
            txt_ephemeral = False

        try:
            bot = inter.music_bot
            guild = inter.music_guild
        except AttributeError:
            bot = inter.bot
            guild = inter.guild

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        component_interaction = isinstance(inter, disnake.MessageInteraction)

        ephemeral = await self.is_request_channel(inter, data=data)

        if ephemeral:
            player.set_command_log(text=f"{inter.author.mention} {txt}", emoji=emoji)
            player.update = True

        await player.update_message(
            interaction=inter if (bot.user.id == self.bot.user.id and component_interaction) else False,
            rpc_update=rpc_update,
            force=force,
        )

        if isinstance(inter, CustomContext):
            embed = disnake.Embed(
                color=self.bot.get_color(guild.me), description=f"{txt_ephemeral or txt}{player.controller_link}"
            )

            if thumb:
                embed.set_thumbnail(url=thumb)

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(
                        text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url
                    )
            except AttributeError:
                pass

            if store_embed and not player.controller_mode and len(player.queue) > 0:
                player.temp_embed = embed

            else:
                kwargs = {"components": components} if components else {}
                try:
                    await inter.store_message.edit(embed=embed, view=None, content=None, **kwargs)
                except AttributeError:
                    await inter.send(embed=embed, **kwargs)

        elif not component_interaction:
            kwargs = {"components": components} if components else {}

            embed = disnake.Embed(
                color=self.bot.get_color(guild.me),
                description=(txt_ephemeral or f"{inter.author.mention} **{txt}**") + player.controller_link,
            )

            if thumb:
                embed.set_thumbnail(url=thumb)

            try:
                if bot.user.id != self.bot.user.id:
                    embed.set_footer(
                        text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url
                    )
            except AttributeError:
                pass

            if not inter.response.is_done():
                await inter.send(embed=embed, ephemeral=ephemeral, **kwargs)

            elif defered:
                await inter.edit_original_response(embed=embed, **kwargs)

    @commands.Cog.listener("on_thread_create")
    async def thread_song_request(self, thread: disnake.Thread, reopen: bool = False, bot: BotCore = None):
        if not bot:
            bot = self.bot

        try:
            player: LavalinkPlayer = bot.music.players[thread.guild.id]
        except KeyError:
            return

        if player.static or player.message.id != thread.id:
            return

        if not thread.parent.permissions_for(thread.guild.me).send_messages_in_threads:
            await player.text_channel.send(
                embed=disnake.Embed(
                    color=self.bot.get_color(thread.guild.me),
                    description="**Não tenho permissão de enviar mensagens em conversas do canal atual para ativar "
                    "o sistema de song-request...**\n\n"
                    f"Mensagens enviadas na conversa {thread.mention} serão ignoradas.",
                ),
                delete_after=30,
            )
            return

        embed = disnake.Embed(color=bot.get_color(thread.guild.me))

        if not bot.intents.message_content:
            embed.description = (
                "**Aviso! Não estou com a intent de message_content ativada por meu desenvolvedor...\n"
                "A funcionalidade de pedir música aqui pode não ter um resultado esperado...**"
            )

        elif not player.controller_mode:
            embed.description = (
                "**A skin/aparência atual não é compatível com o sistem de song-request "
                "via thread/conversa\n\n"
                "Nota:** `Esse sistema requer uma skin que use botões.`"
            )

        else:
            if reopen:
                embed.description = "**A sessão para pedidos de música nessa conversa foi reaberta na conversa atual.**"
            else:
                embed.description = (
                    "**Essa conversa será usada temporariamente para pedido de músicas.**\n\n"
                    "**Peça sua música aqui enviando o nome dela ou o link de uma música/vídeo "
                    "que seja de uma das seguintes plataformas suportadas:**\n"
                    "[`Youtube`](<https://www.youtube.com/>), [`Soundcloud`](<https://soundcloud.com/>), "
                    "[`Spotify`](<https://open.spotify.com/>), [`Twitch`](<https://www.twitch.tv/>)"
                )

        await thread.send(embed=embed)

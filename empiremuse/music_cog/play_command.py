# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção até a KI-29b (Music.play, 1.588 linhas, é um comando coeso).
import asyncio
import datetime
import pprint
import traceback
from io import BytesIO
from random import shuffle
from typing import Union, Optional
from urllib.parse import urlparse, parse_qs

import aiohttp
import disnake
from async_timeout import timeout
from disnake.ext import commands
from yt_dlp import YoutubeDL

import empiremuse.wavelink as wavelink
from empiremuse import paths
from empiremuse.utils.branding import asset_url
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.audio_sources.deezer import deezer_regex
from empiremuse.utils.music.audio_sources.spotify import spotify_regex_w_user
from empiremuse.utils.music.checks import (
    check_voice,
    can_send_message_check,
    can_send_message,
    can_connect,
    check_pool_bots,
    check_channel_limit,
    check_player_perm,
)
from empiremuse.utils.music.converters import (
    time_format,
    fix_characters,
    URL_REG,
    YOUTUBE_VIDEO_REG,
    google_search,
    music_source_image,
)
from empiremuse.utils.music.errors import (
    GenericError,
    NoVoice,
    EmptyFavIntegration,
    DiffVoiceChannel,
)
from empiremuse.utils.music.saved_queue import has_saved_queue, load_saved_queue
from empiremuse.utils.music.interactions import (
    SelectInteraction,
    SelectBotVoice,
    youtube_regex,
    ButtonInteraction,
)
from empiremuse.utils.others import (
    CustomContext,
    PlayerControls,
    music_source_emoji_url,
    song_request_buttons,
    update_inter,
    get_source_emoji_cfg,
    music_source_emoji,
)

# O corpo da classe usa estes nomes, então eles precisam existir neste módulo.
from empiremuse.music_cog.shared import (
    DESC_PREFIX as desc_prefix,
    play_cd,
    play_mc,
    playlist_opts,
    sc_profile_regex,
    is_discord_attachment_url,
)


class PlayCommandMixin:
    @can_send_message_check()
    @check_voice()
    @commands.slash_command(
        description=f"{desc_prefix}Tocar música em um canal de voz.",
        extras={"check_player": False},
        cooldown=play_cd,
        max_concurrency=play_mc,
    )
    @commands.contexts(guild=True)
    async def play(
        self,
        inter: Union[disnake.ApplicationCommandInteraction, CustomContext],
        query: str = commands.Param(name="busca", desc="Nome ou link da música."),
        *,
        position: int = commands.Param(
            name="posição", description="Colocar a música em uma posição específica", default=0
        ),
        force_play: str = commands.Param(
            name="tocar_agora",
            description="Tocar a música imediatamente (ao invés de adicionar na fila).",
            default="no",
            choices=[
                disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
            ],
        ),
        mix: str = commands.Param(
            name="recomendadas",
            description="Tocar músicas recomendadas com base no nome do artista - música informado",
            default=False,
            choices=[
                disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
            ],
        ),
        manual_selection: bool = commands.Param(
            name="selecionar_manualmente",
            description="Escolher uma música manualmente entre os resultados encontrados",
            default=False,
        ),
        options: str = commands.Param(
            name="opções", description="Opções para processar playlist", choices=playlist_opts, default=False
        ),
        server: str = commands.Param(
            name="server", desc="Usar um servidor de música específico na busca.", default=None
        ),
        manual_bot_choice: str = commands.Param(
            name="selecionar_bot",
            description="Selecionar um bot disponível manualmente.",
            default="no",
            choices=[
                disnake.OptionChoice(disnake.Localized("Yes", data={disnake.Locale.pt_BR: "Sim"}), "yes"),
            ],
        ),
    ):
        try:
            bot = inter.music_bot
            guild = inter.music_guild
            author = guild.get_member(inter.author.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            author = inter.author

        original_bot = bot

        mix = mix == "yes" or mix is True

        msg = None
        guild_data = await bot.get_data(inter.author.id, db_name=DBModel.guilds)
        ephemeral = None

        if not inter.response.is_done():
            try:
                async with timeout(1.5):
                    ephemeral = await self.is_request_channel(inter, data=guild_data, ignore_thread=True)
            except asyncio.TimeoutError:
                ephemeral = True
            await inter.response.defer(ephemeral=ephemeral, with_message=True)

        """if not inter.author.voice:
            raise NoVoice()

            if not (c for c in guild.channels if c.permissions_for(inter.author).connect):
                raise GenericError(f"**Você não está conectado a um canal de voz, e não há canais de voz/palcos "
                                   "disponíveis no servidor que concedam a permissão para você se conectar.**")

            color = self.bot.get_color(guild.me)

            if isinstance(inter, CustomContext):
                func = inter.send
            else:
                func = inter.edit_original_message

            msg = await func(
                embed=disnake.Embed(
                    description=f"**{inter.author.mention} entre em um canal de voz para tocar sua música.**\n"
                                f"**Caso não conecte em um canal em até 25 segundos essa operação será cancelada.**",
                    color=color
                )
            )

            if msg:
                inter.store_message = msg

            try:
                await bot.wait_for("voice_state_update", timeout=25, check=lambda m, b, a: m.id == inter.author.id and m.voice)
            except asyncio.TimeoutError:
                try:
                    func = msg.edit
                except Exception:
                    func = inter.edit_original_message
                await func(
                    embed=disnake.Embed(
                        description=f"**{inter.author.mention} operação cancelada.**\n"
                                    f"**Você demorou para conectar em um canal de voz/palco.**", color=color
                    )
                )
                return

            await asyncio.sleep(1)

        else:
            channel = bot.get_channel(inter.channel.id)
            if not channel:
                raise GenericError(f"**O canal <#{inter.channel.id}> não foi encontrado (ou foi excluido).**")
            await check_pool_bots(inter, check_player=False, bypass_prefix=True)"""

        if guild.me.voice and bot.user.id not in author.voice.channel.voice_states:
            if str(inter.channel.id) == guild_data["player_controller"]["channel"]:
                try:
                    if inter.author.id not in bot.music.players[guild.id].last_channel.voice_states:
                        raise DiffVoiceChannel()
                except (KeyError, AttributeError):
                    pass

            else:
                free_bots = await self.check_available_bot(inter=inter, guild=guild, bot=bot, message=msg)

                if len(free_bots) > 1 and manual_bot_choice == "yes":
                    v = SelectBotVoice(inter, guild, free_bots)

                    try:
                        func = msg.edit
                    except AttributeError:
                        try:
                            func = inter.edit_original_message
                        except AttributeError:
                            func = inter.send

                    newmsg = await func(
                        embed=disnake.Embed(
                            description=f"**Escolha qual bot você deseja usar no canal {author.voice.channel.mention}**",
                            color=self.bot.get_color(guild.me),
                        ),
                        view=v,
                    )
                    await v.wait()

                    if newmsg:
                        msg = newmsg

                    if v.status is None:
                        try:
                            func = msg.edit
                        except AttributeError:
                            func = inter.edit_original_message
                        try:
                            await func(
                                embed=disnake.Embed(
                                    description="### Tempo esgotado...", color=self.bot.get_color(guild.me)
                                ),
                                view=None,
                            )
                        except Exception:
                            traceback.print_exc()
                        return

                    if v.status is False:
                        try:
                            func = msg.edit
                        except AttributeError:
                            func = inter.edit_original_message
                        await func(
                            embed=disnake.Embed(
                                description="### Operação cancelada.", color=self.bot.get_color(guild.me)
                            ),
                            view=None,
                        )
                        return

                    if not author.voice:
                        try:
                            func = msg.edit
                        except AttributeError:
                            func = inter.edit_original_message
                        await func(
                            embed=disnake.Embed(
                                description="### Você não está conectado em um canal de voz...",
                                color=self.bot.get_color(guild.me),
                            ),
                            view=None,
                        )
                        return

                    update_inter(inter, v.inter)

                    current_bot = v.bot
                    inter = v.inter
                    guild = v.guild

                    await inter.response.defer()

                else:
                    try:
                        current_bot = free_bots.pop(0)
                    except Exception:
                        return

                if bot != current_bot:
                    guild_data = await current_bot.get_data(guild.id, db_name=DBModel.guilds)

                bot = current_bot

        channel = bot.get_channel(inter.channel.id)

        can_send_message(channel, bot.user)

        await check_player_perm(inter=inter, bot=bot, channel=channel, guild_data=guild_data)

        if not guild.voice_client and not check_channel_limit(guild.me, author.voice.channel):
            raise GenericError(f"**O canal {author.voice.channel.mention} está lotado!**")

        await self.check_player_queue(inter.author, bot, guild.id)

        query = query.replace("\n", " ").strip()
        warn_message = None
        queue_loaded = False
        reg_query = None
        image_file = None

        try:
            if isinstance(inter.message, disnake.Message):
                message_inter = inter.message
            else:
                message_inter = None
        except AttributeError:
            message_inter = None

        try:
            modal_message_id = int(inter.data.custom_id[15:])
        except Exception:
            modal_message_id = None

        attachment: Optional[disnake.Attachment] = None

        try:
            voice_channel: disnake.VoiceChannel = bot.get_channel(author.voice.channel.id)
        except AttributeError:
            raise NoVoice()

        try:
            player = bot.music.players[guild.id]

            if not server:
                node = player.node
            else:
                node = bot.music.get_node(server) or player.node

            guild_data = {}

        except KeyError:
            node = bot.music.get_node(server)

            if not node:
                node = await self.get_best_node(bot)

            guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

            if not guild.me.voice:
                can_connect(voice_channel, guild, guild_data["check_other_bots_in_vc"], bot=bot)

            static_player = guild_data["player_controller"]

            if not inter.response.is_done():
                ephemeral = await self.is_request_channel(inter, data=guild_data, ignore_thread=True)
                await inter.response.defer(ephemeral=ephemeral)

            if static_player["channel"]:
                channel, warn_message, message = await self.check_channel(guild_data, inter, channel, guild, bot)

        if ephemeral is None:
            ephemeral = await self.is_request_channel(inter, data=guild_data, ignore_thread=True)

        is_pin = None

        original_query = query or ""

        if not query:
            if self.bot.config["ENABLE_DISCORD_URLS_PLAYBACK"]:
                try:
                    attachment = inter.message.attachments[0]

                    if attachment.size > 18000000:
                        raise GenericError("**O arquivo que você enviou deve ter o tamanho igual ou inferior a 18mb.**")

                    if attachment.content_type not in self.audio_formats:
                        raise GenericError("**O arquivo que você enviou não é um arquivo de música válido...**")

                    query = attachment.url

                except IndexError:
                    pass

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        try:
            fav_slashcmd = (
                f"</fav_manager:"
                + str(
                    self.bot.get_global_command_named(
                        "fav_manager", cmd_type=disnake.ApplicationCommandType.chat_input
                    ).id
                )
                + ">"
            )
        except AttributeError:
            fav_slashcmd = "/fav_manager"

        try:
            savequeue_slashcmd = (
                f"</save_queue:"
                + str(
                    self.bot.get_global_command_named(
                        "save_queue", cmd_type=disnake.ApplicationCommandType.chat_input
                    ).id
                )
                + ">"
            )
        except AttributeError:
            savequeue_slashcmd = "/save_queue"

        if not query:
            opts = []

            txt = "### `[⭐] Favoritos [⭐]`\n"

            if user_data["fav_links"]:
                opts.append(disnake.SelectOption(label="Usar favorito", value=">> [⭐ Favoritos ⭐] <<", emoji="⭐"))
                txt += f"`Tocar música ou playlist que você curtiu ou que você tenha adicionado nos seus favoritos.`\n"

            else:
                txt += f"`Você não possui favoritos...`\n"

            txt += (
                f"-# Você pode gerenciar seus favoritos usando o comando {fav_slashcmd}.\n### `[💠] Integrações [💠]`\n"
            )

            if user_data["integration_links"]:
                opts.append(
                    disnake.SelectOption(label="Usar integração", value=">> [💠 Integrações 💠] <<", emoji="💠")
                )
                txt += f"`Tocar playlist pública de um canal do youtube (ou de um perfil de usuário de alguma plataforma de música) da sua lista de integrações.`\n"

            else:
                txt += (
                    f"`Você não possui integração adicionada... "
                    f"Use as integrações para adicionar links de canais do youtube (ou link de perfil de algum usuário de alguma plataforma de música) para ter acesso facilita a todas a playlists públicas que o mesmo possui.`\n"
                )

            txt += (
                f'-# Para gerenciar suas integrações use o comando {fav_slashcmd} e em seguida selecione a opção "integrações".\n'
                f"### `[💾] Fila Salva [💾]`\n"
            )

            if has_saved_queue(inter.author.id):
                txt += f"`Usar fila de música que você salvou via comando` {savequeue_slashcmd}.\n"
                opts.append(disnake.SelectOption(label="Usar fila salva", value=">> [💾 Fila Salva 💾] <<", emoji="💾"))

            else:
                txt += (
                    "`Você não possui uma fila de música salva`\n"
                    f"-# Pra ter uma fila salva você pode usar o comando {savequeue_slashcmd} quando houver no mínimo 3 músicas adicionadas no player."
                )

            if user_data["last_tracks"]:
                txt += (
                    "### `[📑] Músicas recentes [📑]`\n"
                    "`Tocar uma música que você tenha ouvido/adicionado recentemente.`\n"
                )
                opts.append(
                    disnake.SelectOption(
                        label="Adicionar música recente", value=">> [📑 Músicas recentes 📑] <<", emoji="📑"
                    )
                )

            if isinstance(inter, disnake.MessageInteraction) and not inter.response.is_done():
                await inter.response.defer(ephemeral=ephemeral)

            if not guild_data:
                guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

            if guild_data["player_controller"]["fav_links"]:
                txt += (
                    "### `[📌] Favoritos do servidor [📌]`\n"
                    "`Usar favorito do servidor (adicionados por staffs do servidor).`\n"
                )
                opts.append(
                    disnake.SelectOption(
                        label="Usar favorito do servidor", value=">> [📌 Favoritos do servidor 📌] <<", emoji="📌"
                    )
                )

            if not opts:
                raise EmptyFavIntegration()

            embed = disnake.Embed(
                color=self.bot.get_color(guild.me),
                description=f"{txt}## Selecione uma opção abaixo:"
                f"\n-# Nota: Essa solicitação será cancelada automaticamente <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=180)).timestamp())}:R> caso não seja selecionado uma opção abaixo.",
            )

            kwargs = {"content": "", "embed": embed}

            try:
                if inter.message.author.bot:
                    kwargs["content"] = inter.author.mention
            except AttributeError:
                pass

            view = SelectInteraction(user=inter.author, timeout=180, opts=opts)

            try:
                await msg.edit(view=view, **kwargs)
            except AttributeError:
                try:
                    await inter.edit_original_message(view=view, **kwargs)
                except AttributeError:
                    msg = await inter.send(view=view, **kwargs)

            await view.wait()

            select_interaction = view.inter

            try:
                func = inter.edit_original_message
            except AttributeError:
                func = msg.edit

            if not select_interaction or view.selected is False:
                embed.set_footer(
                    text="⚠️ "
                    + ("Tempo de seleção esgotado!" if view.selected is not False else "Cancelado pelo usuário.")
                )

                try:
                    await func(embed=embed, components=song_request_buttons)
                except AttributeError:
                    traceback.print_exc()
                    pass
                return

            if select_interaction.data.values[0] == "cancel":
                await func(
                    embed=disnake.Embed(description="**Seleção cancelada!**", color=self.bot.get_color(guild.me)),
                    components=None,
                )
                return

            try:
                inter.store_message = msg
            except AttributeError:
                pass

            inter.token = select_interaction.token
            inter.id = select_interaction.id
            inter.response = select_interaction.response
            query = select_interaction.data.values[0]
            await inter.response.defer()

        fav_opts = []

        menu = None
        selected_title = ""

        if query.startswith(">> [💠 Integrações 💠] <<"):
            query = ""
            menu = "integrations"
            for k, v in user_data["integration_links"].items():
                update = False

                if not isinstance(v, dict):
                    v = {"url": v, "avatar": None}
                    user_data["integration_links"][k] = v
                    update = True

                if update:
                    await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

                emoji, platform = music_source_emoji_url(v["url"])

                fav_opts.append(
                    {
                        "url": v["url"],
                        "option": disnake.SelectOption(
                            label=fix_characters(k[6:], 45),
                            value=f"> itg: {k}",
                            description=f"[💠 Integração 💠] -> {platform}",
                            emoji=emoji,
                        ),
                    }
                )

        elif query.startswith(">> [⭐ Favoritos ⭐] <<"):
            query = ""
            menu = "favs"
            for k, v in user_data["fav_links"].items():
                emoji, platform = music_source_emoji_url(v)
                fav_opts.append(
                    {
                        "url": v,
                        "option": disnake.SelectOption(
                            label=fix_characters(k, 45),
                            value=f"> fav: {k}",
                            description=f"[⭐ Favorito ⭐] -> {platform}",
                            emoji=emoji,
                        ),
                    }
                )

        elif query.startswith(">> [📑 Músicas recentes 📑] <<"):
            if not user_data["last_tracks"]:
                raise GenericError(
                    "**Você não possui músicas registradas no seu histórico...**\n"
                    "Elas vão aparecer a medida que for adicionando músicas via busca ou link."
                )

            query = ""
            menu = "latest"
            for i, d in enumerate(user_data["last_tracks"]):
                emoji, platform = music_source_emoji_url(d["url"])
                fav_opts.append(
                    {
                        "url": d["url"],
                        "option": disnake.SelectOption(
                            label=d["name"],
                            value=f"> lst: {i}",
                            description=f"[📑 Músicas recentes 📑] -> {platform}",
                            emoji=emoji,
                        ),
                    }
                )

        elif query.startswith(">> [📌 Favoritos do servidor 📌] <<"):
            if not guild_data:
                guild_data = await bot.get_data(guild.id, db_name=DBModel.guilds)

            if not guild_data["player_controller"]["fav_links"]:
                raise GenericError("**O servidor não possui links fixos/favoritos.**")

            menu = "guild_favs"

            for name, v in guild_data["player_controller"]["fav_links"].items():
                fav_opts.append(
                    {
                        "url": v["url"],
                        "option": disnake.SelectOption(
                            label=fix_characters(name, 45),
                            value=f"> pin: {name}",
                            description="[📌 Favorito do servidor 📌]",
                            emoji=music_source_emoji_url(v["url"])[0],
                        ),
                    }
                )

            is_pin = False

        if fav_opts:
            if len(fav_opts) == 1:
                query = list(fav_opts)[0]["option"].value

            else:
                check_url = lambda i: f"{i}/playlists" if (".spotify." in i or ".deezer." in i) else i

                embed = disnake.Embed(
                    color=self.bot.get_color(guild.me),
                    description="\n".join(
                        f"{get_source_emoji_cfg(bot, i['url']) or ''} [`{fix_characters(i['option'].label, 45)}`]({check_url(i['url'])})"
                        for i in fav_opts
                    ),
                )

                if menu == "favs":
                    embed.description = (
                        "### `[⭐] ⠂Favoritos ⠂[⭐]`\n"
                        "`Tocar música ou playlist que você curtiu ou que você tenha adicionado na sua lista de favoritos.`\n"
                        f"-# Você pode gerenciar seus favoritos usando o comando {fav_slashcmd}.\n\n"
                        f"{embed.description}\n\n**Selecione um favorito abaixo:**"
                    )

                elif menu == "integrations":
                    embed.description = (
                        "### `[💠] ⠂Integrações ⠂[💠]`\n"
                        "`Tocar playlist pública de um canal do youtube (ou de um perfil de usuário de alguma plataforma de música) da sua lista de integrações.`\n"
                        f'-# Para gerenciar suas integrações use o comando {fav_slashcmd} e em seguida selecione a opção "integrações".\n\n'
                        f"{embed.description}\n\n**Selecione uma integração abaixo:**"
                    )

                elif menu == "guild_favs":
                    embed.description = (
                        f"### `[📌] ⠂Favoritos do servidor ⠂[📌]\n"
                        "`Usar favorito do servidor (adicionados por staffs do servidor).`\n\n"
                        f"{embed.description}\n\n**Selecione um favorito abaixo:**"
                    )

                elif menu == "latest":
                    embed.description = (
                        f"### 📑 ⠂Tocar música/playlist recente:\n{embed.description}\n\n**Selecione um item abaixo:**"
                    )

                embed.description += f"\n-# Nota: Essa solicitação será cancelada automaticamente <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=75)).timestamp())}:R> caso não seja selecionado uma opção abaixo."

                try:
                    if bot.user.id != self.bot.user.id:
                        embed.set_footer(
                            text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url
                        )
                except AttributeError:
                    pass

                kwargs = {"content": "", "embed": embed}

                try:
                    if inter.message.author.bot:
                        kwargs["content"] = inter.author.mention
                except AttributeError:
                    pass

                view = SelectInteraction(user=inter.author, timeout=75, opts=[i["option"] for i in fav_opts])

                if isinstance(inter, disnake.MessageInteraction) and not inter.response.is_done():
                    await inter.response.defer(ephemeral=ephemeral)

                try:
                    func = msg.edit
                except AttributeError:
                    try:
                        if inter.response.is_done():
                            func = inter.edit_original_message
                        else:
                            func = inter.response.send_message
                            kwargs["ephemeral"] = ephemeral
                    except AttributeError:
                        kwargs["ephemeral"] = ephemeral
                        try:
                            func = inter.followup.send
                        except AttributeError:
                            func = inter.send

                msg = await func(view=view, **kwargs)

                await view.wait()

                select_interaction = view.inter

                if not select_interaction or view.selected is False:
                    embed.description = "\n".join(embed.description.split("\n")[:-3])
                    embed.set_footer(
                        text="⚠️ Tempo esgotado!" if not view.selected is False else "⚠️ Cancelado pelo usuário."
                    )

                    try:
                        await msg.edit(embed=embed, components=song_request_buttons)
                    except AttributeError:
                        try:
                            await select_interaction.response.edit_message(embed=embed, components=song_request_buttons)
                        except AttributeError:
                            traceback.print_exc()
                    return

                if select_interaction.data.values[0] == "cancel":
                    embed.description = "\n".join(embed.description.split("\n")[:-3])
                    embed.set_footer(text="⚠️ Seleção cancelada!")
                    await msg.edit(embed=embed, components=None)
                    return

                try:
                    inter.store_message = msg
                except AttributeError:
                    pass

                inter.token = select_interaction.token
                inter.id = select_interaction.id
                inter.response = select_interaction.response
                query = select_interaction.data.values[0]
                selected_title = ":".join(query.split(":")[2:])

        elif not query:
            raise EmptyFavIntegration()

        loadtype = None
        tracks = []

        source = None

        if query.startswith("> pin: "):
            if is_pin is None:
                is_pin = True
            if not guild_data:
                guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)
            query = guild_data["player_controller"]["fav_links"][query[7:]]["url"]
            source = False

        elif query.startswith("> lst: "):
            query = user_data["last_tracks"][int(query[7:])]["url"]
            source = False

        if not user_data:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        yt_match = None
        sc_match = None
        profile_avatar = None
        info = {"entries": []}
        node: Optional[wavelink.Node] = None

        if query.startswith("> fav:"):
            query = user_data["fav_links"][query[7:]]

        elif query.startswith("> itg:"):
            integration_data = user_data["integration_links"][query[7:]]

            if not isinstance(integration_data, dict):
                integration_data = {"url": integration_data, "avatar": None}
                user_data["integration_links"][query[7:]] = integration_data
                await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

            query = integration_data["url"]

            profile_avatar = integration_data.get("avatar")

        if matches := spotify_regex_w_user.match(query):
            if not self.bot.spotify:
                raise GenericError("**O suporte ao spotify não está disponível no momento...**")

            url_type, user_id = matches.groups()

            if url_type == "user":
                try:
                    await inter.response.defer(ephemeral=True)
                except Exception:
                    pass

                cache_key = f"partial:spotify:{url_type}:{user_id}"

                if not (info := self.bot.pool.integration_cache.get(cache_key)):
                    result = await self.bot.spotify.get_user_playlists(user_id)
                    info = {
                        "entries": [
                            {"title": t["name"], "url": f"{t['external_urls']['spotify']}"} for t in result["items"]
                        ]
                    }
                    self.bot.pool.integration_cache[cache_key] = info

        elif matches := deezer_regex.match(query):
            url_type, user_id = matches.groups()[-2:]

            if url_type == "profile":
                try:
                    await inter.response.defer(ephemeral=True)
                except Exception:
                    pass

                cache_key = f"partial:deezer:{url_type}:{user_id}"

                if not (info := self.bot.pool.integration_cache.get(cache_key)):
                    result = await bot.deezer.get_user_playlists(user_id)
                    info = {"entries": [{"title": t["title"], "url": f"{t['link']}"} for t in result]}
                    self.bot.pool.integration_cache[cache_key] = info

        elif matches := (yt_match := youtube_regex.search(query)) or (sc_match := sc_profile_regex.match(query)):
            if yt_match:
                query = f"{yt_match.group()}/playlists"
                remove_chars = 12
            else:
                query = f"{sc_match.group(0).strip('<>')}/sets"
                remove_chars = 6

            try:
                await inter.response.defer(ephemeral=True)
            except Exception:
                pass

            if not (info := self.bot.pool.integration_cache.get(query)):
                info = await self.bot.loop.run_in_executor(
                    None, lambda: self.bot.pool.ytdl.extract_info(query.split("\n")[0], download=False)
                )

                try:
                    if not info["entries"]:
                        pprint.pprint(info)
                        raise GenericError(f"**Conteúdo indisponível (ou privado):**\n{query}")
                except KeyError:
                    raise GenericError("**Ocorreu um erro ao tentar obter resultados para a opção selecionada...**")

                self.bot.pool.integration_cache[query] = info

            try:
                profile_avatar = [a["url"] for a in info["thumbnails"] if a["id"] == "avatar_uncropped"][0]
            except (KeyError, IndexError):
                pass

            try:
                selected_title = info["channel"]
            except KeyError:
                selected_title = info["title"][:-remove_chars]

            info = {
                "entries": [{"title": t["title"], "url": f"{t['url']}"} for t in info["entries"]],
                "thumbnails": info.get("thumbnails"),
            }

        if matches and info["entries"]:
            if len(info["entries"]) == 1:
                query = info["entries"][0]["url"]

            else:
                emoji, platform = music_source_emoji_url(query)

                view = SelectInteraction(
                    user=inter.author,
                    max_itens=15,
                    opts=[
                        disnake.SelectOption(
                            label=e["title"][:90], value=f"entrie_select_{c}", emoji=emoji, description=platform
                        )
                        for c, e in enumerate(info["entries"])
                    ],
                    timeout=120,
                )

                embed_title = (
                    f"do canal: {(info.get('title') or selected_title)}"
                    if platform == "youtube"
                    else f"do usuário: {info.get('title') or selected_title}"
                )

                embeds = []

                for page_index, page in enumerate(disnake.utils.as_chunks(info["entries"], 15)):
                    embed = disnake.Embed(
                        description="\n".join(
                            f"-# ` {(15 * page_index) + n + 1}. `[`{i['title']}`]({i['url']})"
                            for n, i in enumerate(page)
                        )
                        + "\n\n**Selecione uma playlist abaixo:**\n"
                        f"-# Essa solicitação será cancelada automaticamente <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=120)).timestamp())}:R> caso não seja selecionado uma opção abaixo.",
                        color=self.bot.get_color(guild.me),
                    ).set_author(
                        name=f"Tocar playlist pública {embed_title}", icon_url=music_source_image(platform), url=query
                    )

                    if profile_avatar:
                        embed.set_thumbnail(profile_avatar)
                        try:
                            if len(info["thumbnails"]) > 2:
                                embed.set_image(info["thumbnails"][0]["url"])
                        except Exception:
                            pass

                    embeds.append(embed)

                kwargs = {}

                view.embeds = embeds

                try:
                    func = msg.edit
                except AttributeError:
                    try:
                        func = inter.edit_original_message
                    except AttributeError:
                        kwargs["ephemeral"] = True
                        try:
                            func = inter.followup.send
                        except AttributeError:
                            func = inter.send

                msg = await func(embed=embeds[0], view=view, **kwargs)

                await view.wait()

                if not view.inter or view.selected is False:
                    try:
                        func = msg.edit
                    except Exception:
                        func = view.inter.response.edit_message

                    try:
                        embed = view.embeds[view.current_page]
                    except Exception:
                        embed = embeds[0]

                    embed.description = "\n".join(embed.description.split("\n")[:-3])
                    embed.set_footer(
                        text="⚠️ Tempo esgotado!" if not view.selected is False else "⚠️ Cancelado pelo usuário."
                    )

                    try:
                        await func(embed=embed, components=song_request_buttons)
                    except Exception:
                        traceback.print_exc()
                    return

                query = info["entries"][int(view.selected[14:])]["url"]

                if not isinstance(inter, disnake.ModalInteraction):
                    inter.token = view.inter.token
                    inter.id = view.inter.id
                    inter.response = view.inter.response
                else:
                    inter = view.inter

            source = False

        if query.startswith(">> [💾 Fila Salva 💾] <<"):
            data = await load_saved_queue(inter.author.id, inter.guild_id)

            tracks = await self.check_player_queue(
                inter.author, bot, guild.id, self.bot.pool.process_track_cls(data["tracks"])[0]
            )
            node = await self.get_best_node(bot)
            queue_loaded = True
            source = False

        else:
            query = query.strip("<>")

            urls = URL_REG.findall(query)

            reg_query = {}

            if urls:
                query = urls[0]
                source = False

                if not self.bot.config["ENABLE_DISCORD_URLS_PLAYBACK"] and is_discord_attachment_url(query):
                    raise GenericError("**O suporte a links do discord está desativado.**")

                if query.startswith("https://www.youtube.com/results"):
                    try:
                        query = f"ytsearch:{parse_qs(urlparse(query).query)['search_query'][0]}"
                    except Exception:
                        raise GenericError(f"**Não há suporte para o link informado:** {query}")
                    manual_selection = True

                elif "&list=" in query and (link_re := YOUTUBE_VIDEO_REG.search(query)):
                    view = ButtonInteraction(
                        user=inter.author,
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
                        color=self.bot.get_color(guild.me),
                    )

                    try:
                        if bot.user.id != self.bot.user.id:
                            embed.set_footer(
                                text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url
                            )
                    except AttributeError:
                        pass

                    try:
                        func = inter.edit_original_message
                        kwargs = {}
                    except AttributeError:
                        func = inter.send
                        kwargs = {"ephemeral": ephemeral}

                    msg = await func(embed=embed, view=view, **kwargs)

                    await view.wait()

                    if not view.inter or view.selected is False:
                        try:
                            func = inter.edit_original_message
                        except AttributeError:
                            func = msg.edit

                        embed.description = "\n".join(embed.description.split("\n")[:-3])
                        embed.set_footer(
                            text="⚠️ Tempo esgotado!" if not view.selected is False else "⚠️ Cancelado pelo usuário."
                        )

                        try:
                            await func(embed=embed, components=song_request_buttons)
                        except Exception:
                            traceback.print_exc()
                        return

                    if view.selected == "music":
                        query = link_re.group()

                    try:
                        inter.store_message = msg
                    except AttributeError:
                        pass

                    if not isinstance(inter, disnake.ModalInteraction):
                        inter.token = view.inter.token
                        inter.id = view.inter.id
                        inter.response = view.inter.response
                    else:
                        inter = view.inter

            else:
                music_sources = {"deezer", "spotify"}

                for b in self.bot.pool.get_guild_bots(inter.guild_id):
                    if not b.get_guild(inter.guild_id):
                        continue

                    for n in b.music.nodes.values():
                        for s in n.info["sourceManagers"]:
                            if s in self.providers_info:
                                music_sources.add(s)

                view = ButtonInteraction(
                    user=inter.author,
                    timeout=45,
                    buttons=[
                        disnake.ui.Button(label=ms.title(), custom_id=ms, emoji=music_source_emoji(ms))
                        for ms in sorted(music_sources)
                    ],
                )

                embed = disnake.Embed(
                    color=inter.bot.get_color(guild.me),
                    description="**Selecione o serviço você deseja priorizar a busca da música?**\n"
                    "-# Nota: Caso não retorne a musica desejada no serviço escolhido será usado outro selecionado automaticamente.\n"
                    f"-# Nota 2: Caso não escolha alguma opção abaixo <t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=45)).timestamp())}:R> será usado o serviço padrão automaticamente.",
                )

                if inter.response.is_done():
                    await inter.edit_original_message(embed=embed, view=view)
                else:
                    msg = await inter.send(embed=embed, view=view)

                await view.wait()

                if view.selected:
                    inter = view.inter
                    source = self.providers_info[view.selected]

                elif view.selected is False:
                    for c in view.children:
                        c.disabled = True
                    embed.description = "\n".join(embed.description.split("\n")[:-1])
                    embed.set_footer(text="Interação cancelada.")
                    func = view.inter.response.edit_message
                    await func(view=view, embed=embed)
                    return

                update_inter(inter, view.inter)

        if not inter.response.is_done():
            await inter.response.defer(ephemeral=ephemeral)

        if not queue_loaded:
            tracks, node = await self.get_tracks(query, inter, inter.author, node=node, source=source, bot=bot, mix=mix)
            tracks = await self.check_player_queue(inter.author, bot, guild.id, tracks)

        try:
            player = bot.music.players[guild.id]
        except KeyError:
            new_bot, guild = await check_pool_bots(inter, check_player=False, bypass_prefix=True, bypass_attribute=True)
            channel = bot.get_channel(inter.channel.id)

            try:
                new_bot.music.players[guild.id]
            except KeyError:
                if new_bot != bot or not guild_data:
                    guild_data = await new_bot.get_data(guild.id, db_name=DBModel.guilds)

                static_player = guild_data["player_controller"]

                if static_player["channel"]:
                    channel, warn_message, message = await self.check_channel(
                        guild_data, inter, channel, guild, new_bot
                    )

            bot = new_bot

        channel = bot.get_channel(inter.channel.id)

        can_send_message(channel, bot.user)

        pos_txt = ""

        embed = disnake.Embed(color=disnake.Colour.red())

        embed.colour = self.bot.get_color(guild.me)

        position -= 1

        embed_description = ""

        track_url = ""

        if isinstance(tracks, list):
            if self.bot.pool.song_select_cooldown.get_bucket(inter).get_retry_after() > 0:
                manual_selection = True

            if not queue_loaded and len(tracks) > 1 and manual_selection:
                embed.description = f"**Selecione a(s) música(s) desejada(s) abaixo:**"

                try:
                    func = inter.edit_original_message
                except AttributeError:
                    func = inter.send

                try:
                    add_id = f"_{inter.id}"
                except AttributeError:
                    add_id = ""

                tracks = tracks[:25]

                msg = await func(
                    embed=embed,
                    components=[
                        disnake.ui.Select(
                            placeholder="Resultados:",
                            custom_id=f"track_selection{add_id}",
                            min_values=1,
                            max_values=len(tracks),
                            required=False,
                            options=[
                                disnake.SelectOption(
                                    label=f"{n + 1}. {t.title[:96]}",
                                    value=f"track_select_{n}",
                                    description=f"{t.author[:70]} [{time_format(t.duration)}]",
                                )
                                for n, t in enumerate(tracks)
                            ],
                        )
                    ],
                )

                def check_song_selection(i: Union[CustomContext, disnake.MessageInteraction]):
                    try:
                        return i.data.custom_id == f"track_selection_{inter.id}" and i.author == inter.author
                    except AttributeError:
                        return i.author == inter.author and i.message.id == msg.id

                try:
                    select_interaction: disnake.MessageInteraction = await self.bot.wait_for(
                        "dropdown", timeout=45, check=check_song_selection
                    )
                except asyncio.TimeoutError:
                    try:
                        func = inter.edit_original_message
                    except AttributeError:
                        func = msg.edit
                    try:
                        await func(
                            embed=disnake.Embed(color=disnake.Colour.red(), description="**Tempo esgotado!**"),
                            view=None,
                        )
                    except disnake.NotFound:
                        pass
                    return

                update_inter(inter, select_interaction)

                if len(select_interaction.data.values) > 1:
                    indexes = set(int(v[13:]) for v in select_interaction.data.values)

                    selected_tracks = []

                    for i in indexes:
                        for n, t in enumerate(tracks):
                            if i == n:
                                selected_tracks.append(t)
                                break

                    tracks = selected_tracks

                else:
                    tracks = tracks[int(select_interaction.data.values[0][13:])]

                if isinstance(inter, CustomContext):
                    inter.message = msg

                if reg_query is not None:
                    try:
                        reg_query = {"name": tracks.title, "url": tracks.uri}
                    except AttributeError:
                        reg_query = {"name": tracks[0].title, "url": tracks[0].uri}

                    if not reg_query["url"]:
                        reg_query = None

                await select_interaction.response.defer()

                inter = select_interaction

            elif not queue_loaded:
                tracks = tracks[0]

                if tracks.info.get("sourceName") == "http":
                    if tracks.title == "Unknown title":
                        if attachment:
                            tracks.info["title"] = attachment.filename
                        else:
                            tracks.info["title"] = tracks.uri.split("/")[-1]
                        tracks.title = tracks.info["title"]

                    tracks.info["uri"] = ""

                elif url_check := URL_REG.match(original_query.strip("<>")):
                    track_url = url_check.group()

            if not author.voice:
                raise NoVoice()

            if inter.author.id not in voice_channel.voice_states and bot.user.id not in voice_channel.voice_states:
                if not (free_bots := await self.check_available_bot(inter=inter, guild=guild, bot=bot, message=msg)):
                    return

                if free_bots[0] != bot:
                    try:
                        voice_channel = bot.get_channel(author.voice.channel.id)
                    except AttributeError:
                        raise NoVoice()
                    bot = free_bots.pop(0)
                    channel = bot.get_channel(channel.id)
                    guild = bot.get_guild(guild.id)
                    guild_data = await bot.get_data(guild.id, db_name=DBModel.guilds)
                    node = None

            await check_player_perm(inter=inter, bot=bot, channel=channel, guild_data=guild_data)

            try:
                player = bot.music.players[guild.id]
            except KeyError:
                player = await self.create_player(
                    inter=inter,
                    bot=bot,
                    guild=guild,
                    guild_data=guild_data,
                    channel=channel,
                    message_inter=message_inter,
                    node=node,
                    modal_message_id=modal_message_id,
                )

            if not isinstance(tracks, list):
                if force_play == "yes":
                    player.queue.insert(0, tracks)
                elif position < 0:
                    player.queue.append(tracks)
                else:
                    player.queue.insert(position, tracks)
                    pos_txt = f" na posição {position + 1} da fila"

                duration = time_format(tracks.duration) if not tracks.is_stream else "🔴 Livestream"

                if not track_url:
                    track_url = tracks.uri or tracks.search_uri

                log_text = f"{inter.author.mention} adicionou [`{fix_characters(tracks.title, 20)}`](<{track_url}>){pos_txt} `({duration})`."

                loadtype = "track"

                embed.set_author(
                    name="⠂" + fix_characters(tracks.single_title, 35),
                    url=track_url,
                    icon_url=music_source_image(tracks.info["sourceName"]),
                )
                embed.set_thumbnail(url=tracks.thumb)
                embed.description = f"`{fix_characters(tracks.author, 15)}`**┃**`{time_format(tracks.duration) if not tracks.is_stream else '🔴 Livestream'}`**┃**{inter.author.mention}"
                emoji = "🎵"
                if reg_query is not None and tracks.uri:
                    reg_query = {"name": tracks.title, "url": tracks.uri}

            else:
                if options == "shuffle":
                    shuffle(tracks)

                if position < 0 or len(tracks) < 2:
                    if options == "reversed":
                        tracks.reverse()
                    for track in tracks:
                        player.queue.append(track)
                else:
                    if options != "reversed":
                        tracks.reverse()
                    for track in tracks:
                        player.queue.insert(position, track)

                    pos_txt = f" (Pos. {position + 1})"

                total_duration = 0

                for t in tracks:
                    if not t.is_stream:
                        total_duration += t.duration

                if queue_loaded:
                    log_text = f"{inter.author.mention} adicionou `{len(tracks)} músicas` via: {query[7:]}."
                    title = f"Usando músicas salvas de {inter.author.display_name}"
                    icon_url = asset_url("ui_floppy_save_icon.png")

                    desc = ""

                    tracks_playlists = {}

                    for t in tracks:
                        if t.playlist_name:
                            try:
                                tracks_playlists[t.playlist_url]["count"] += 1
                            except KeyError:
                                tracks_playlists[t.playlist_url] = {"name": t.playlist_name, "count": 1}

                    if tracks_playlists:
                        embed_description += (
                            "\n### Playlists carregadas:\n"
                            + "\n".join(
                                f"[`{info['name']}`]({url}) `- {info['count']} música{'s'[: info['count'] ^ 1]}` "
                                for url, info in tracks_playlists.items()
                            )
                            + "\n"
                        )

                else:
                    query = fix_characters(query.replace(f"{source}:", "", 1), 25)
                    title = "Músicas adicionadas:"
                    icon_url = music_source_image(tracks[0].info["sourceName"])
                    log_text = (
                        f"{inter.author.mention} adicionou `{len(tracks)} músicas` via busca: `{query}`{pos_txt}."
                    )
                    desc = "\n".join(
                        f"` {c + 1}. ` [`{fix_characters(t.title, 75)}`](<{t.uri}>) `{time_format(t.duration)}`"
                        for c, t in enumerate(tracks)
                    )

                embed.set_author(name="⠂" + title, icon_url=icon_url)
                embed.set_thumbnail(url=tracks[0].thumb)
                embed.description = (
                    desc
                    or f"`{(tcount := len(tracks))} música{'s'[: tcount ^ 1]}`**┃**`{time_format(total_duration)}`**┃**{inter.author.mention}"
                )
                emoji = "🎶"

        else:
            if not author.voice:
                raise NoVoice()

            if inter.author.id not in voice_channel.voice_states and bot.user.id not in voice_channel.voice_states:
                if not (free_bots := await self.check_available_bot(inter=inter, guild=guild, bot=bot, message=msg)):
                    return

                if free_bots[0] != bot:
                    try:
                        voice_channel = bot.get_channel(author.voice.channel.id)
                    except AttributeError:
                        raise NoVoice()
                    bot = free_bots.pop(0)
                    channel = bot.get_channel(channel.id)
                    guild = bot.get_guild(guild.id)
                    guild_data = await bot.get_data(guild.id, db_name=DBModel.guilds)
                    node = None

            await check_player_perm(inter=inter, bot=bot, channel=channel, guild_data=guild_data)

            try:
                player = bot.music.players[guild.id]
            except KeyError:
                player = await self.create_player(
                    inter=inter,
                    bot=bot,
                    guild=guild,
                    guild_data=guild_data,
                    channel=channel,
                    message_inter=message_inter,
                    node=node,
                    modal_message_id=modal_message_id,
                )

            if options == "shuffle":
                shuffle(tracks.tracks)

            if position < 0 or len(tracks.tracks) < 2:
                if options == "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.append(track)
            else:
                if options != "reversed":
                    tracks.tracks.reverse()
                for track in tracks.tracks:
                    player.queue.insert(position, track)

                pos_txt = f" (Pos. {position + 1})"

            if tracks.tracks[0].info["sourceName"] == "youtube":
                try:
                    q = f"https://www.youtube.com/playlist?list={query.split('&list=')[1]}"
                except Exception:
                    q = query

                if not await bot.is_owner(inter.author):
                    try:
                        async with bot.session.get((oembed_url := f"https://www.youtube.com/oembed?url={q}")) as r:
                            try:
                                playlist_data = await r.json()
                            except Exception:
                                raise Exception(f"{r.status} | {await r.text()}")
                            else:
                                tracks.data["playlistInfo"]["thumb"] = playlist_data["thumbnail_url"]
                    except Exception as e:
                        print(f"Falha ao obter artwork da playlist (oembed): {oembed_url} | {repr(e)}")

                else:
                    try:
                        with YoutubeDL(
                            {
                                "extract_flat": True,
                                "quiet": True,
                                "no_warnings": True,
                                "lazy_playlist": True,
                                "simulate": True,
                                "playlistend": 0,
                                "cachedir": str(paths.RUNTIME_DIR / ".ytdl_cache"),
                                "allowed_extractors": [
                                    r".*youtube.*",
                                ],
                                "extractor_args": {"youtubetab": {"skip": ["webpage"]}},
                            }
                        ) as ydl:
                            playlist_data = await bot.loop.run_in_executor(
                                None, lambda: ydl.extract_info(q, download=False)
                            )

                        async with aiohttp.ClientSession() as session:
                            async with session.get(playlist_data["thumbnails"][0]["url"]) as response:
                                if response.status != 200:
                                    response.raise_for_status()

                                image_file = disnake.File(
                                    fp=BytesIO(await response.read()), filename=f"{playlist_data['id']}.jpg"
                                )

                        tracks.data["playlistInfo"]["thumb"] = playlist_data["thumbnails"][0]["url"]
                    except Exception as e:
                        print(f"Falha ao obter artwork da playlist: {q} | {repr(e)}")

            loadtype = "playlist"

            log_text = f"{inter.author.mention} adicionou a playlist [`{fix_characters(tracks.name, 20)}`](<{tracks.url}>){pos_txt} `({len(tracks.tracks)})`."

            total_duration = 0

            for t in tracks.tracks:
                if not t.is_stream:
                    total_duration += t.duration

            try:
                embed.set_author(
                    name="⠂" + fix_characters(tracks.name, 35),
                    url=tracks.url,
                    icon_url=music_source_image(tracks.tracks[0].info["sourceName"]),
                )
            except KeyError:
                embed.set_author(
                    name="⠂ Spotify Playlist", icon_url=music_source_image(tracks.tracks[0].info["sourceName"])
                )

            if image_file:
                embed.set_thumbnail(f"attachment://{image_file.filename}")
            else:
                embed.set_thumbnail(url=tracks.thumb)
            embed.description = f"`{(tcount := len(tracks.tracks))} música{'s'[: tcount ^ 1]}`**┃**`{time_format(total_duration)}`**┃**{inter.author.mention}"
            emoji = "🎶"

            if reg_query is not None and tracks.uri:
                reg_query = {"name": tracks.name, "url": tracks.uri}

        embed.description += player.controller_link

        player.queue_autoplay.clear()

        if not is_pin:
            if not player.is_connected:
                try:
                    embed.description += f"\n`Canal de voz:` {voice_channel.mention}"
                except AttributeError:
                    pass

            embed.description += embed_description

            try:
                func = inter.edit_original_message
            except AttributeError:
                if msg:
                    func = msg.edit
                elif inter.message.author.id == bot.user.id:
                    func = inter.message.edit
                else:
                    func = inter.send

            footer_txt = (
                f"`♾️` [`{user_data['lastfm']['username']}`](https://www.last.fm/user/{user_data['lastfm']['username']})"
                if user_data["lastfm"]["sessionkey"] and user_data["lastfm"]["scrobble"]
                else ""
            )

            try:
                if original_bot.user.id != self.bot.user.id:
                    embed.description += f"\n-# **Via:** {bot.user.mention}" + (f" ⠂{footer_txt}" if footer_txt else "")
                elif footer_txt:
                    embed.description += f"\n-# {footer_txt}"
            except AttributeError:
                if footer_txt:
                    embed.description += f"\n-# {footer_txt}"

            if mix:
                components = []

            elif loadtype == "track":
                components = [
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

            elif loadtype == "playlist":
                try:
                    self.bot.pool.enqueue_playlist_embed_cooldown.get_bucket(inter).update_rate_limit()
                except Exception:
                    pass
                components = [
                    disnake.ui.Button(emoji="💗", label="Favoritar", custom_id=PlayerControls.embed_add_fav),
                    disnake.ui.Button(
                        emoji="➕", label="Adicionar na fila", custom_id=PlayerControls.embed_enqueue_playlist
                    ),
                ]
            else:
                components = None

            kw_embed = {"components": components} if components else {"view": None}
            if image_file:
                kw_embed["file"] = image_file
            await func(embed=embed, **kw_embed)

        if not player.is_connected:
            try:
                guild_data["check_other_bots_in_vc"]
            except KeyError:
                guild_data = await bot.get_data(guild.id, db_name=DBModel.guilds)

            if isinstance(voice_channel, disnake.StageChannel):
                player.stage_title_event = False

            await self.do_connect(
                inter,
                channel=voice_channel,
                check_other_bots_in_vc=guild_data["check_other_bots_in_vc"],
                bot=bot,
                me=player.guild.me,
            )

        await self.process_music(
            inter=inter,
            force_play=force_play,
            ephemeral=ephemeral,
            user_data=user_data,
            player=player,
            log_text=log_text,
            emoji=emoji,
            warn_message=warn_message,
            reg_query=reg_query,
        )

    @play.autocomplete("busca")
    async def fav_add_autocomplete(self, inter: disnake.Interaction, query: str):
        if not self.bot.is_ready() or URL_REG.match(query) or URL_REG.match(query):
            return [query] if len(query) < 100 else []

        favs = [">> [⭐ Favoritos ⭐] <<", ">> [💠 Integrações 💠] <<", ">> [📌 Favoritos do servidor 📌] <<"]

        if has_saved_queue(inter.author.id):
            favs.append(">> [💾 Fila Salva 💾] <<")

        if not inter.guild_id:
            try:
                await check_pool_bots(inter, return_first=True)
            except Exception:
                return [query] if len(query) < 100 else []

        try:
            vc = inter.author.voice
        except AttributeError:
            vc = True

        user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        favs.extend(
            reversed(
                [
                    (f"{rec['url']} || {rec['name']}"[:100] if len(rec["url"]) < 101 else rec["name"][:100])
                    for rec in user_data["last_tracks"]
                    if rec.get("url")
                ]
            )
        )

        if not vc or not query:
            return favs[:20]

        return await google_search(self.bot, query, max_entries=20) or favs[:20]

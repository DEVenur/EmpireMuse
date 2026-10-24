# -*- coding: utf-8 -*-
import asyncio
import datetime
import itertools
import logging
import os.path
import pprint
import re
import sys
import traceback
from copy import deepcopy
from io import BytesIO
from random import shuffle
from typing import Union, Optional
from urllib.parse import urlparse, parse_qs, quote

import aiohttp
import disnake
from async_timeout import timeout
from disnake.ext import commands
from yt_dlp import YoutubeDL

import empiremuse.wavelink as wavelink
from empiremuse import paths
from empiremuse.rules.errors import RuleError
from empiremuse.rules.favorites import save_track
from empiremuse.utils.branding import asset_url
from empiremuse.utils.client import BotCore
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.audio_sources.deezer import deezer_regex
from empiremuse.utils.music.audio_sources.spotify import spotify_link_regex, spotify_regex_w_user
from empiremuse.utils.music.checks import (
    check_voice,
    has_player,
    has_source,
    is_requester,
    is_dj,
    can_send_message_check,
    check_requester_channel,
    can_send_message,
    can_connect,
    check_deafen,
    check_pool_bots,
    check_channel_limit,
    check_stage_topic,
    check_queue_loading,
    check_player_perm,
    check_yt_cooldown,
)
from empiremuse.utils.music.converters import (
    time_format,
    fix_characters,
    string_to_seconds,
    URL_REG,
    YOUTUBE_VIDEO_REG,
    google_search,
    percentage,
    music_source_image,
)
from empiremuse.utils.music.errors import (
    GenericError,
    MissingVoicePerms,
    NoVoice,
    PoolException,
    parse_error,
    EmptyFavIntegration,
    DiffVoiceChannel,
    NoPlayer,
    error_code_text,
    log_unexpected_error,
)
from empiremuse.utils.music.user_limits import quota_for, track_fav_error_text
from empiremuse.utils.music.skin_store import load_custom_skins
from empiremuse.utils.music.saved_queue import has_saved_queue, load_saved_queue, store_saved_queue
from empiremuse.utils.music.interactions import (
    VolumeInteraction,
    QueueInteraction,
    SelectInteraction,
    FavMenuView,
    ViewMode,
    SetStageTitle,
    SelectBotVoice,
    youtube_regex,
    ButtonInteraction,
)
from empiremuse.utils.music.models import (
    LavalinkPlayer,
    LavalinkTrack,
    LavalinkPlaylist,
    PartialTrack,
    PartialPlaylist,
    native_sources,
    CustomYTDL,
)
from empiremuse.utils.others import (
    check_cmd,
    send_idle_embed,
    CustomContext,
    PlayerControls,
    queue_track_index,
    pool_command,
    string_to_file,
    CommandArgparse,
    music_source_emoji_url,
    song_request_buttons,
    select_bot_pool,
    ProgressBar,
    update_inter,
    get_source_emoji_cfg,
    music_source_emoji,
)

# Os mixins são reexecutados a cada carga da extensão (um bot por vez), como o corpo de ``Music``: assim
# cada bot mantém os próprios cooldowns/concorrência, e o reload enxerga edições nos mixins.
for _nome in [m for m in sys.modules if m.startswith("empiremuse.music_cog.")]:
    del sys.modules[_nome]

from empiremuse.music_cog.shared import (  # noqa: E402
    DESC_PREFIX,
    EMOJI,
    NAME,
    DISCORD_ATTACHMENT_PATH_PREFIXES,
    DISCORD_CDN_HOSTS,
    case_sensitive_args,
    is_discord_attachment_url,
    play_cd,
    play_mc,
    playlist_opts,
    queue_manipulation_cd,
    remove_mc,
    sc_profile_regex,
    sc_recommended,
)
from empiremuse.music_cog.skip import SkipMixin  # noqa: E402
from empiremuse.music_cog.playback_controls import PlaybackControlsMixin  # noqa: E402
from empiremuse.music_cog.queue_edit import QueueEditMixin  # noqa: E402
from empiremuse.music_cog.player_session import PlayerSessionMixin  # noqa: E402
from empiremuse.music_cog.now_playing import NowPlayingMixin  # noqa: E402
from empiremuse.music_cog.player_modes import PlayerModesMixin  # noqa: E402
from empiremuse.music_cog.favorites import FavoritesMixin  # noqa: E402
from empiremuse.music_cog.play_entry import PlayEntryMixin  # noqa: E402
from empiremuse.music_cog.play_command import PlayCommandMixin  # noqa: E402
from empiremuse.music_cog.queue_group import QueueGroupMixin  # noqa: E402
from empiremuse.music_cog.autocompletes import AutocompletesMixin  # noqa: E402
from empiremuse.music_cog.voice_status import VoiceStatusMixin  # noqa: E402

logger = logging.getLogger(__name__)


class Music(
    FavoritesMixin,
    PlayerModesMixin,
    AutocompletesMixin,
    QueueGroupMixin,
    NowPlayingMixin,
    PlayerSessionMixin,
    QueueEditMixin,
    PlaybackControlsMixin,
    SkipMixin,
    PlayCommandMixin,
    PlayEntryMixin,
    VoiceStatusMixin,
    commands.Cog,
):
    emoji = EMOJI
    name = NAME
    desc_prefix = DESC_PREFIX
    remove_mc = remove_mc
    queue_manipulation_cd = queue_manipulation_cd
    case_sensitive_args = case_sensitive_args
    play_cd = play_cd
    play_mc = play_mc
    playlist_opts = playlist_opts

    audio_formats = ("audio/mpeg", "audio/ogg", "audio/mp4", "audio/aac")

    providers_info = {
        "youtube": "ytsearch",
        "soundcloud": "scsearch",
        "spotify": "spsearch",
        "tidal": "tdsearch",
        "bandcamp": "bcsearch",
        "applemusic": "amsearch",
        "deezer": "dzsearch",
        "jiosaavn": "jssearch",
    }

    def __init__(self, bot: BotCore):
        self.bot = bot

        self.modules = [
            "empiremuse.utils.music.models",
            "empiremuse.utils.music.audio_sources.spotify",
            "empiremuse.utils.music.audio_sources.deezer",
            "empiremuse.utils.music.filters",
            "empiremuse.utils.music.local_lavalink",
            "empiremuse.utils.music.skin_utils",
            "empiremuse.utils.music.errors",
            "empiremuse.utils.music.interactions",
        ]

        self.extra_hints = bot.config["EXTRA_HINTS"].split("||")

        self.song_request_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

        self.player_interaction_concurrency = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

        self.song_request_cooldown = commands.CooldownMapping.from_cooldown(
            rate=1, per=300, type=commands.BucketType.member
        )

        self.music_settings_cooldown = commands.CooldownMapping.from_cooldown(
            rate=3, per=15, type=commands.BucketType.guild
        )

        if self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"]:
            self.error_report_queue = asyncio.Queue()
            self.error_report_task = bot.loop.create_task(self.error_report_loop())
        else:
            self.error_report_queue = None

    @check_voice()
    @has_player()
    @is_dj()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.slash_command(description=f"{desc_prefix}Migrar o player para outro servidor de música.")
    @commands.contexts(guild=True)
    async def change_node(
        self,
        inter: disnake.ApplicationCommandInteraction,
        node: str = commands.Param(name="servidor", description="Servidor de música"),
    ):
        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        if node not in bot.music.nodes:
            raise GenericError(f"O servidor de música **{node}** não foi encontrado.")

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if node == player.node.identifier:
            raise GenericError(f"O player já está no servidor de música **{node}**.")

        await inter.response.defer(ephemeral=True)

        await player.change_node(node)

        player.native_yt = True

        embed = disnake.Embed(
            description=f"**O player foi migrado para o servidor de música:** `{node}`",
            color=self.bot.get_color(player.guild.me),
        )

        try:
            if bot.user.id != self.bot.user.id:
                embed.set_footer(text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
        except AttributeError:
            pass

        player.set_command_log(
            text=f"{inter.author.mention} migrou o player para o servidor de música **{node}**", emoji="🌎"
        )

        player.update = True

        await inter.edit_original_message(embed=embed)

    @PlayEntryMixin.search.autocomplete("server")
    @PlayCommandMixin.play.autocomplete("server")
    @change_node.autocomplete("servidor")
    async def node_suggestions(self, inter: disnake.Interaction, query: str):
        if not self.bot.bot_ready or not self.bot.is_ready():
            return []

        try:
            await check_pool_bots(inter)
            bot = inter.music_bot
        except GenericError:
            return
        except Exception:
            bot = inter.bot

        try:
            node = bot.music.players[inter.guild_id].node
        except KeyError:
            node = None

        if not query:
            return [n.identifier for n in bot.music.nodes.values() if n != node and n.available and n.is_available]

        return [
            n.identifier
            for n in bot.music.nodes.values()
            if n != node and query.lower() in n.identifier.lower() and n.available and n.is_available
        ]

    @commands.command(aliases=["puptime"], description="Ver informações de tempo que o player está ativo no servidor.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def playeruptime(self, ctx: CustomContext):
        uptime_info = []
        for bot in self.bot.pool.get_guild_bots(ctx.guild.id):
            try:
                player = bot.music.players[ctx.guild.id]
                uptime_info.append(
                    f"**Bot:** {bot.user.mention}\n"
                    f"**Uptime:** <t:{player.uptime}:R>\n"
                    f"**Canal:** {player.guild.me.voice.channel.mention}"
                )
            except KeyError:
                continue

        if not uptime_info:
            raise GenericError("**Não há players ativos no servidor.**")

        await ctx.reply(
            embed=disnake.Embed(
                title="**Player Uptime:**",
                description="\n-----\n".join(uptime_info),
                color=self.bot.get_color(ctx.guild.me),
            ),
            fail_if_not_exists=False,
        )

    @commands.Cog.listener("on_message_delete")
    async def player_message_delete(self, message: disnake.Message):
        if not message.guild:
            return

        try:
            player: LavalinkPlayer = self.bot.music.players[message.guild.id]

            if message.id != player.message.id:
                return

        except (AttributeError, KeyError):
            return

        thread = self.bot.get_channel(message.id)

        if not thread:
            return

        player.message = None
        await thread.edit(archived=True, locked=True, name=f"arquivado: {thread.name}")

    @commands.Cog.listener("on_ready")
    async def resume_players_ready(self):
        if not self.bot.bot_ready:
            return

        for guild_id in list(self.bot.music.players):
            try:
                player: LavalinkPlayer = self.bot.music.players[guild_id]

                try:
                    channel_id = player.guild.me.voice.channel.id
                except AttributeError:
                    channel_id = player.channel_id

                vc = self.bot.get_channel(channel_id) or player.last_channel

                try:
                    player.guild.voice_client.cleanup()
                except Exception:
                    pass

                if not vc:
                    print(
                        f"{self.bot.user} - {player.guild.name} [{guild_id}] - Player finalizado por falta de canal de voz"
                    )
                    try:
                        await player.destroy()
                    except Exception:
                        traceback.print_exc()
                    continue

                await player.connect(vc.id)

                if not player.is_paused and not player.is_playing:
                    await player.process_next()
                print(f"{self.bot.user} - {player.guild.name} [{guild_id}] - Player Reconectado no canal de voz")
            except Exception:
                traceback.print_exc()

    async def is_request_channel(
        self,
        ctx: Union[disnake.ApplicationCommandInteraction, disnake.MessageInteraction, CustomContext],
        *,
        data: dict = None,
        ignore_thread=False,
    ) -> bool:
        if isinstance(ctx, (CustomContext, disnake.MessageInteraction)):
            return True

        try:
            bot = ctx.music_bot
            channel_ctx = bot.get_channel(ctx.channel_id)
        except AttributeError:
            bot = ctx.bot
            channel_ctx = ctx.channel

        if not self.bot.check_bot_forum_post(channel_ctx):
            return True

        try:
            player: LavalinkPlayer = bot.music.players[ctx.guild_id]

            if not player.static:
                return False

            if isinstance(channel_ctx, disnake.Thread) and player.text_channel == channel_ctx.parent:
                return not ignore_thread

            return player.text_channel == channel_ctx

        except KeyError:
            if not data:
                data = await bot.get_data(ctx.guild_id, db_name=DBModel.guilds)

            try:
                channel = bot.get_channel(int(data["player_controller"]["channel"]))
            except Exception:
                channel = None

            if not channel:
                return False

            if isinstance(channel_ctx, disnake.Thread) and channel == channel_ctx.parent:
                return not ignore_thread

            return channel.id == channel_ctx.id

    async def check_channel(
        self,
        guild_data: dict,
        inter: Union[disnake.ApplicationCommandInteraction, CustomContext],
        channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.Thread],
        guild: disnake.Guild,
        bot: BotCore,
    ):
        static_player = guild_data["player_controller"]

        warn_message = None
        message: Optional[disnake.Message] = None

        try:
            channel_db = bot.get_channel(int(static_player["channel"])) or await bot.fetch_channel(
                int(static_player["channel"])
            )
        except (TypeError, disnake.NotFound):
            channel_db = None
        except disnake.Forbidden:
            channel_db = bot.get_channel(inter.channel_id)
            warn_message = f"Não tenho permissão de acessar o canal <#{static_player['channel']}>, o player será usado no modo tradicional."
            static_player["channel"] = None

        if not channel_db or channel_db.guild.id != inter.guild_id:
            await self.reset_controller_db(inter.guild_id, guild_data, inter)

        else:
            if channel_db.id != channel.id:
                try:
                    if isinstance(channel_db, disnake.Thread):
                        if not channel_db.parent:
                            await self.reset_controller_db(inter.guild_id, guild_data, inter)
                            channel_db = None

                        else:
                            if channel_db.owner != bot.user.id:
                                if (
                                    not isinstance(channel_db.parent, disnake.ForumChannel)
                                    or not channel_db.parent.permissions_for(channel_db.guild.me).create_forum_threads
                                ):
                                    await self.reset_controller_db(inter.guild_id, guild_data, inter)
                                    channel_db = None
                                else:
                                    thread = None

                                    for t in channel_db.parent.threads:
                                        if t.owner_id == bot.user.id:
                                            try:
                                                message = await t.fetch_message(t.id)
                                            except disnake.NotFound:
                                                continue
                                            if not message or message.author.id != bot.user.id:
                                                continue
                                            thread = t
                                            break

                                    if not thread and guild.me.guild_permissions.read_message_history:
                                        async for t in channel_db.parent.archived_threads(limit=100):
                                            if t.owner_id == bot.user.id:
                                                try:
                                                    message = await t.fetch_message(t.id)
                                                except disnake.NotFound:
                                                    continue
                                                if not message or message.author.id != bot.user.id:
                                                    continue
                                                thread = t
                                                break

                                    if not thread:
                                        thread_wmessage = await channel_db.parent.create_thread(
                                            name=f"{bot.user} song-request",
                                            content="Post para pedido de músicas.",
                                            auto_archive_duration=10080,
                                            slowmode_delay=5,
                                        )
                                        channel_db = thread_wmessage.thread
                                        message = thread_wmessage.message
                                    else:
                                        channel_db = thread

                            thread_kw = {}

                            if channel_db.locked and channel_db.permissions_for(guild.me).manage_threads:
                                thread_kw.update({"locked": False, "archived": False})

                            elif channel_db.archived and channel_db.owner_id == bot.user.id:
                                thread_kw["archived"] = False

                            if thread_kw:
                                await channel_db.edit(**thread_kw)

                            elif isinstance(channel.parent, disnake.ForumChannel):
                                warn_message = (
                                    f"**{bot.user.mention} não possui permissão de gerenciar tópicos "
                                    f"para desarquivar/destrancar o tópico: {channel_db.mention}**"
                                )

                except AttributeError:
                    pass

                if channel_db:
                    channel_db_perms = channel_db.permissions_for(guild.me)

                    channel = bot.get_channel(inter.channel.id)

                    if isinstance(channel, disnake.Thread):
                        send_message_perm = (
                            getattr(channel_db, "parent", channel_db)
                            .permissions_for(channel.guild.me)
                            .send_messages_in_threads
                        )
                    else:
                        send_message_perm = channel_db.permissions_for(channel.guild.me).send_messages

                    if not send_message_perm:
                        raise GenericError(
                            f"**{bot.user.mention} não possui permissão para enviar mensagens no canal <#{static_player['channel']}>**\n"
                            "Caso queira resetar a configuração do canal de pedir música, use o comando /reset ou /setup "
                            "novamente..."
                        )

                    if not channel_db_perms.embed_links:
                        raise GenericError(
                            f"**{bot.user.mention} não possui permissão para anexar links/embeds no canal <#{static_player['channel']}>**\n"
                            "Caso queira resetar a configuração do canal de pedir música, use o comando /reset ou /setup "
                            "novamente..."
                        )

        return channel_db, warn_message, message

    async def process_player_interaction(
        self,
        interaction: Union[disnake.MessageInteraction, disnake.ModalInteraction],
        command: Optional[disnake.ApplicationCommandInteraction],
        kwargs: dict,
    ):
        if not command:
            raise GenericError("comando não encontrado/implementado.")

        try:
            interaction.application_command = command
            await command._max_concurrency.acquire(interaction)
        except AttributeError:
            pass

        await check_cmd(command, interaction)

        await command(interaction, **kwargs)

        try:
            await command._max_concurrency.release(interaction)
        except Exception:
            pass

        try:
            player: LavalinkPlayer = self.bot.music.players[interaction.guild_id]
            player.interaction_cooldown = True
            await asyncio.sleep(1)
            player.interaction_cooldown = False
        except (KeyError, AttributeError):
            pass

    @commands.Cog.listener("on_dropdown")
    async def guild_pin(self, interaction: disnake.MessageInteraction):
        if not self.bot.bot_ready:
            await interaction.send("Ainda estou inicializando...\nPor favor aguarde mais um pouco...", ephemeral=True)
            return

        if interaction.data.custom_id != "player_guild_pin":
            return

        if not interaction.data.values:
            await interaction.response.defer()
            return

        if not interaction.user.voice:
            await interaction.send("Você deve entrar em um canal de voz para usar isto.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild_data = await self.bot.get_data(interaction.guild_id, db_name=DBModel.guilds)

        try:
            query = interaction.data.values[0]
        except KeyError:
            await interaction.send("**O item selecionado não foi encontrado na base de dados...**", ephemeral=True)
            await send_idle_embed(interaction.message, bot=self.bot, guild_data=guild_data, force=True)
            return

        kwargs = {
            "query": f"> pin: {query}",
            "position": 0,
            "options": False,
            "manual_selection": True,
            "server": None,
            "force_play": "no",
        }

        try:
            await self.play.callback(self=self, inter=interaction, **kwargs)
        except Exception as e:
            self.bot.dispatch("interaction_player_error", interaction, e)

    @commands.Cog.listener("on_dropdown")
    async def player_dropdown_event(self, interaction: disnake.MessageInteraction):
        if interaction.data.custom_id == "musicplayer_queue_dropdown":
            await self.process_player_interaction(
                interaction=interaction,
                command=self.bot.get_slash_command("skipto"),
                kwargs={"query": interaction.values[0][3:], "case_sensitive": True},
            )
            return

        if not interaction.data.custom_id.startswith("musicplayer_dropdown_"):
            return

        if not interaction.values:
            await interaction.response.defer()
            return

        await self.player_controller(interaction, interaction.values[0])

    @commands.Cog.listener("on_button_click")
    async def player_button_event(self, interaction: disnake.MessageInteraction):
        if not interaction.data.custom_id.startswith("musicplayer_"):
            return

        await self.player_controller(interaction, interaction.data.custom_id)

    async def check_stage_title(self, inter, bot: BotCore, player: LavalinkPlayer):
        time_limit = 30 if isinstance(player.guild.me.voice.channel, disnake.VoiceChannel) else 120

        if (
            player.stage_title_event
            and (time_ := int((disnake.utils.utcnow() - player.start_time).total_seconds())) < time_limit
            and not (await bot.is_owner(inter.author))
        ):
            raise GenericError(
                f"**Você terá que aguardar {time_format((time_limit - time_) * 1000, use_names=True)} para usar essa função "
                f"com o anúncio automático do palco ativo...**"
            )

    async def player_controller(self, interaction: disnake.MessageInteraction, control: str, **kwargs):
        if not self.bot.bot_ready or not self.bot.is_ready():
            await interaction.send("Ainda estou inicializando...", ephemeral=True)
            return

        if not interaction.guild_id:
            await interaction.response.edit_message(components=None)
            return

        cmd_kwargs = {}

        cmd: Optional[disnake.ApplicationCommandInteraction] = None

        if control in (
            PlayerControls.embed_forceplay,
            PlayerControls.embed_enqueue_track,
            PlayerControls.embed_enqueue_playlist,
        ):
            try:
                try:
                    if not (url := interaction.message.embeds[0].author.url):
                        if not (matches := URL_REG.findall(interaction.message.embeds[0].description)):
                            return
                        url = matches[0].split(">")[0]
                except Exception:
                    return

                try:
                    await self.player_interaction_concurrency.acquire(interaction)
                except Exception:
                    raise GenericError("Há uma música sendo processada no momento...")

                bot: Optional[BotCore] = None
                player: Optional[LavalinkPlayer] = None
                channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.StageChannel, disnake.Thread] = None
                author: Optional[disnake.Member] = None

                for b in sorted(
                    self.bot.pool.get_guild_bots(interaction.guild_id), key=lambda b: b.identifier, reverse=True
                ):
                    try:
                        p = b.music.players[interaction.guild_id]
                    except KeyError:
                        if c := b.get_channel(interaction.channel_id):
                            bot = b
                            channel = c
                            author = c.guild.get_member(interaction.author.id)
                        continue

                    if p.guild.me.voice and interaction.author.id in p.guild.me.voice.channel.voice_states:
                        if p.locked:
                            raise GenericError(
                                "**Não é possível executar essa ação com o processamento da música em andamento "
                                "(por favor aguarde mais alguns segundos e tente novamente).**"
                            )

                        player = p
                        bot = b
                        channel = player.text_channel
                        author = p.guild.get_member(interaction.author.id)
                        break

                if not channel:
                    raise GenericError("Não há bots disponíveis no momento.")

                if not author.voice:
                    raise GenericError("Você deve entrar em um canal de voz pra usar esse botão....")

                try:
                    node = player.node
                except Exception:
                    node: Optional[wavelink.Node] = None

                try:
                    interaction.author = author
                except AttributeError:
                    pass

                await check_player_perm(inter=interaction, bot=bot, channel=interaction.channel)

                vc_id: int = author.voice.channel.id

                can_connect(channel=author.voice.channel, guild=channel.guild)

                await interaction.response.defer()

                if control == PlayerControls.embed_enqueue_playlist:
                    if retry_after := self.bot.pool.enqueue_playlist_embed_cooldown.get_bucket(
                        interaction
                    ).update_rate_limit():
                        raise GenericError(
                            f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} pra adicionar uma playlist no player atual.**"
                        )

                    if not player:
                        player = await self.create_player(
                            inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                        )

                    await self.check_player_queue(interaction.author, bot, interaction.guild_id)
                    result, node = await self.get_tracks(
                        url, interaction, author, source=False, node=player.node, bot=bot
                    )
                    result = await self.check_player_queue(interaction.author, bot, interaction.guild_id, tracks=result)
                    player.queue.extend(result.tracks)
                    await interaction.send(
                        f"{interaction.author.mention}, a playlist [`{result.name}`](<{url}>) foi adicionada com sucesso!{player.controller_link}",
                        ephemeral=True,
                    )

                    if not player.is_connected:
                        await player.connect(vc_id)

                    try:
                        vc = interaction.author.voice.channel
                    except AttributeError:
                        vc = player.bot.get_channel(vc_id)

                    if isinstance(vc, disnake.StageChannel):
                        retries = 5

                        while retries > 0:
                            await asyncio.sleep(1)

                            if not player.guild.me.voice:
                                retries -= 1
                                continue

                            break

                        if player.guild.me not in vc.speakers:
                            stage_perms = vc.permissions_for(player.guild.me)
                            if stage_perms.manage_permissions:
                                await asyncio.sleep(1.5)
                                await player.guild.me.edit(suppress=False)

                    if not player.current:
                        await player.process_next()

                else:
                    track = []
                    seek_status = False

                    if player:
                        if (
                            control == PlayerControls.embed_forceplay
                            and player.current
                            and (player.current.uri.startswith(url) or url.startswith(player.current.uri))
                        ):
                            await self.check_stage_title(inter=interaction, bot=bot, player=player)
                            await player.seek(0)
                            player.set_command_log("voltou para o início da música.", emoji="⏪")
                            await asyncio.sleep(3)
                            await player.update_stage_topic()
                            await asyncio.sleep(7)
                            seek_status = True

                        else:
                            for t in list(player.queue):
                                if t.uri.startswith(url) or url.startswith(t.uri):
                                    track = [t]
                                    player.queue.remove(t)
                                    break

                            if not track:
                                for t in list(player.played):
                                    if t.uri.startswith(url) or url.startswith(t.uri):
                                        track = [t]
                                        player.played.remove(t)
                                        break

                                if not track:
                                    for t in list(player.failed_tracks):
                                        if t.uri.startswith(url) or url.startswith(t.uri):
                                            track = [t]
                                            player.failed_tracks.remove(t)
                                            break

                    if not seek_status:
                        if not track:
                            if retry_after := self.bot.pool.enqueue_track_embed_cooldown.get_bucket(
                                interaction
                            ).update_rate_limit():
                                raise GenericError(
                                    f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} para adicionar uma nova música na fila.**"
                                )

                            if control == PlayerControls.embed_enqueue_track:
                                await self.check_player_queue(interaction.author, bot, interaction.guild_id)

                            result, node = await self.get_tracks(
                                url, interaction, author, source=False, node=node, bot=bot
                            )

                            track = result

                        if control == PlayerControls.embed_enqueue_track:
                            if not player:
                                player = await self.create_player(
                                    inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                                )
                            await self.check_player_queue(interaction.author, bot, interaction.guild_id)
                            player.update = True
                            if isinstance(track, list):
                                t = track[0]
                                player.queue.append(t)
                                await interaction.send(
                                    f"{author.mention}, a música [`{t.title}`](<{t.uri}>) foi adicionada na fila.{player.controller_link}",
                                    ephemeral=True,
                                )
                            else:
                                player.queue.extend(track.tracks)
                                await interaction.send(
                                    f"{author.mention}, a playlist [`{track.name}`](<{track.url}>) foi adicionada na fila.{player.controller_link}",
                                    ephemeral=True,
                                )
                            if not player.is_connected:
                                await player.connect(vc_id)
                            if not player.current:
                                await player.process_next()

                        else:
                            if not player:
                                player = await self.create_player(
                                    inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                                )
                            else:
                                await self.check_stage_title(inter=interaction, bot=bot, player=player)

                            if isinstance(track, list):
                                player.queue.insert(0, track[0])
                            else:
                                index = len(player.queue)
                                player.queue.extend(track.tracks)
                                if index:
                                    player.queue.rotate(index * -1)
                            if not player.is_connected:
                                await player.connect(vc_id)
                            await self.process_music(inter=interaction, player=player, force_play="yes")

            except Exception as e:
                self.bot.dispatch("interaction_player_error", interaction, e)
                if not isinstance(e, GenericError):
                    await asyncio.sleep(5)
            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass
            return

        if control == PlayerControls.embed_add_fav:
            try:
                embed = interaction.message.embeds[0]
            except IndexError:
                await interaction.send("A embed da mensagem foi removida...", ephemeral=True)
                return

            if retry_after := self.bot.pool.add_fav_embed_cooldown.get_bucket(interaction).update_rate_limit():
                await interaction.send(
                    f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} para adicionar um novo favorito.**",
                    ephemeral=True,
                )
                return

            await interaction.response.defer()

            user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

            limit = await quota_for(self.bot, interaction.author, "MAX_USER_FAVS")

            saved = save_track(user_data["fav_links"], embed.author.name[1:], embed.author.url, limit=limit)

            if isinstance(saved, RuleError):
                await interaction.edit_original_message(track_fav_error_text(saved))
                return

            fav_name = saved.name
            user_data["fav_links"] = saved.entries

            await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

            global_data = await self.bot.get_global_data(interaction.guild_id, db_name=DBModel.guilds)

            try:
                cmd = (
                    f"</play:"
                    + str(
                        self.bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id
                    )
                    + ">"
                )
            except AttributeError:
                cmd = "/play"

            try:
                interaction.message.embeds[0].fields[0].value = (
                    f"{interaction.author.mention} "
                    + interaction.message.embeds[0].fields[0].value.replace(interaction.author.mention, "")
                )
            except IndexError:
                interaction.message.embeds[0].add_field(
                    name="**Membros que favoritaram o link:**", value=interaction.author.mention
                )

            await interaction.send(
                embed=disnake.Embed(
                    description=f"[`{fav_name}`](<{embed.author.url}>) **foi adicionado nos seus favoritos!**\n\n"
                    "**Como usar?**\n"
                    f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                    "* Clicando no botão/select de tocar favorito/integração do player.\n"
                    f"* Usando o comando {global_data['prefix'] or self.bot.default_prefix}{self.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                ).set_footer(
                    text=f"Caso queira ver todos os seus favoritos use o comando {global_data['prefix'] or self.bot.default_prefix}{self.fav_manager_legacy.name}"
                ),
                ephemeral=True,
            )

            if not interaction.message.flags.ephemeral:
                if not interaction.guild:
                    await (await interaction.original_response()).edit(embed=interaction.message.embeds[0])
                else:
                    await interaction.message.edit(embed=interaction.message.embeds[0])
            return

        if not interaction.guild:
            await interaction.response.edit_message(components=None)
            return

        try:
            if control == "musicplayer_request_channel":
                cmd = self.bot.get_slash_command("setup")
                cmd_kwargs = {"target": interaction.channel}
                await self.process_player_interaction(interaction, cmd, cmd_kwargs)
                return

            if control == PlayerControls.fav_manager:
                if str(interaction.user.id) not in interaction.message.content:
                    await interaction.send("Você não pode interagir aqui!", ephemeral=True)
                    return

                cmd = self.bot.get_slash_command("fav_manager")
                await self.process_player_interaction(interaction, cmd, cmd_kwargs)
                return

            if control in (PlayerControls.add_song, PlayerControls.enqueue_fav):
                if not interaction.user.voice:
                    raise GenericError("**Você deve entrar em um canal de voz para usar esse botão.**")

                user_data = await self.bot.get_global_data(id_=interaction.user.id, db_name=DBModel.users)

                modal_components = []

                if user_data["fav_links"]:
                    fav_opts = []

                    for k, v in list(user_data["fav_links"].items())[:25]:
                        emoji, platform = music_source_emoji_url(v)
                        fav_opts.append(
                            disnake.SelectOption(
                                label=fix_characters(k, 35),
                                value=f"> fav: {k}",
                                description=f"⭐ -> {platform}",
                                emoji=emoji,
                            )
                        )

                    modal_components.append(
                        disnake.ui.Label(
                            text="⭐⠂Favoritos:",
                            component=disnake.ui.StringSelect(
                                options=fav_opts, required=False, min_values=0, custom_id="fav_links"
                            ),
                        ),
                    )

                if user_data["integration_links"]:
                    integration_opts = []

                    update = False

                    for k, v in list(user_data["integration_links"].items())[:25]:
                        if not isinstance(v, dict):
                            v = {"url": v, "avatar": None}
                            user_data["integration_links"][k] = v
                            update = True

                        emoji, platform = music_source_emoji_url(v["url"])

                        integration_opts.append(
                            disnake.SelectOption(
                                label=fix_characters(k[6:], 35),
                                value=f"> itg: {k}",
                                description=f"💠 -> {platform}",
                                emoji=emoji,
                            )
                        )

                    modal_components.append(
                        disnake.ui.Label(
                            text="💠⠂Integrações:",
                            component=disnake.ui.StringSelect(
                                options=integration_opts, required=False, min_values=0, custom_id="integration_links"
                            ),
                        )
                    )

                    if update:
                        await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

                modal_components = [
                    disnake.ui.Label(
                        text="Nome ou link do youtube/spotify/soundcloud...",
                        component=disnake.ui.TextInput(
                            custom_id="song_input", max_length=150, required=not modal_components
                        ),
                    ),
                    disnake.ui.Label(
                        text="Posição da fila (número).",
                        component=disnake.ui.TextInput(custom_id="song_position", max_length=3, required=False),
                    ),
                ] + modal_components

                await interaction.response.send_modal(
                    title="Pedir uma música",
                    custom_id="modal_add_song" + (f"_{interaction.message.id}" if interaction.message.thread else ""),
                    components=modal_components,
                )

                return

            if control == PlayerControls.lastfm_scrobble:
                await interaction.response.defer(ephemeral=True, with_message=True)
                user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

                if not user_data["lastfm"]["sessionkey"]:
                    try:
                        cmd = (
                            f"</lastfm:"
                            + str(
                                self.bot.get_global_command_named(
                                    "lastfm", cmd_type=disnake.ApplicationCommandType.chat_input
                                ).id
                            )
                            + ">"
                        )
                    except AttributeError:
                        cmd = "/lastfm"

                    await interaction.edit_original_message(
                        content=f"Você não possui uma conta do last.fm vinculada nos meus dados. "
                        f"Você pode vincular uma conta do last.fm usando o comando {cmd}."
                    )
                    return

                user_data["lastfm"]["scrobble"] = not user_data["lastfm"]["scrobble"]
                self.bot.pool.lastfm_sessions[interaction.author.id] = user_data["lastfm"]
                await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)
                await interaction.edit_original_message(
                    embed=disnake.Embed(
                        description=f"**O scrobble/registro de músicas foi {'ativado' if user_data['lastfm']['scrobble'] else 'desativado'} na conta: [{user_data['lastfm']['username']}](<https://www.last.fm/user/{user_data['lastfm']['username']}>).**",
                        color=self.bot.get_color(),
                    )
                )
                return

            try:
                player: LavalinkPlayer = self.bot.music.players[interaction.guild_id]
            except KeyError:
                await interaction.send("Não há player ativo no servidor...", ephemeral=True)
                await send_idle_embed(interaction.message, bot=self.bot)
                return

            if interaction.message != player.message:
                if control != PlayerControls.queue:
                    return

            if player.interaction_cooldown:
                raise GenericError("O player está em cooldown, tente novamente em instantes.")

            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                await player.destroy(force=True)
                return

            if control == PlayerControls.help_button:
                embed = disnake.Embed(
                    description="📘 **IFORMAÇÕES SOBRE OS BOTÕES** 📘\n\n"
                    "⏯️ `= Pausar/Retomar a música.`\n"
                    "⏮️ `= Voltar para a música tocada anteriormente.`\n"
                    "⏭️ `= Pular para a próxima música.`\n"
                    "🔀 `= Misturar as músicas da fila.`\n"
                    "🎶 `= Adicionar música/playlist/favorito.`\n"
                    "⏹️ `= Parar o player e me desconectar do canal.`\n"
                    "📑 `= Exibir a fila de música.`\n"
                    "🛠️ `= Alterar algumas configurações do player:`\n"
                    "`volume / efeito nightcore / repetição / modo restrito.`\n",
                    color=self.bot.get_color(interaction.guild.me),
                )

                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if not interaction.author.voice or interaction.author.voice.channel != vc:
                raise GenericError(f"Você deve estar no canal <#{vc.id}> para usar os botões do player.")

            if control == PlayerControls.miniqueue:
                await is_dj().predicate(interaction)
                player.mini_queue_enabled = not player.mini_queue_enabled
                player.set_command_log(
                    emoji="📑",
                    text=f"{interaction.author.mention} {'ativou' if player.mini_queue_enabled else 'desativou'} "
                    f"a mini-fila do player.",
                )
                await player.invoke_np(interaction=interaction)
                return

            if control != PlayerControls.queue:
                try:
                    await self.player_interaction_concurrency.acquire(interaction)
                except commands.MaxConcurrencyReached:
                    raise GenericError(
                        '**Você tem uma interação em aberto!**\n`Se for uma mensagem oculta, evite clicar em "ignorar".`'
                    )

            if control == PlayerControls.add_favorite:
                if not player.current:
                    await interaction.send("**Não há música tocando atualmente...**", ephemeral=True)
                    return

                choices = {}
                msg = ""

                if player.current.uri:
                    choices["Track"] = {"name": player.current.title, "url": player.current.uri, "emoji": "🎵"}
                    msg += f"**Música:** [`{player.current.title}`]({player.current.uri})\n"

                if player.current.album_url:
                    choices["Album"] = {
                        "name": player.current.album_name,
                        "url": player.current.album_url,
                        "emoji": "💽",
                    }
                    msg += f"**Album:** [`{player.current.album_name}`]({player.current.album_url})\n"

                if player.current.playlist_url:
                    choices["Playlist"] = {
                        "name": player.current.playlist_name,
                        "url": player.current.playlist_url,
                        "emoji": "📑",
                    }
                    msg += f"**Playlist:** [`{player.current.playlist_name}`]({player.current.playlist_url})\n"

                if not choices:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me),
                            description="### Não há itens para favoritar na música atual.",
                        ),
                        ephemeral=True,
                    )
                    return

                if len(choices) == 1:
                    select_type, info = list(choices.items())[0]

                else:
                    view = SelectInteraction(
                        user=interaction.author,
                        timeout=30,
                        opts=[
                            disnake.SelectOption(label=k, description=v["name"][:50], emoji=v["emoji"])
                            for k, v in choices.items()
                        ],
                    )

                    await interaction.send(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me),
                            description=f"### Selecione um item da música atual para adicionar nos seus favoritos:"
                            f"\n\n{msg}",
                        ),
                        view=view,
                        ephemeral=True,
                    )

                    await view.wait()

                    select_interaction = view.inter

                    if not select_interaction or view.selected is False:
                        try:
                            await self.player_interaction_concurrency.release(interaction)
                        except Exception:
                            pass
                        await interaction.edit_original_message(
                            embed=disnake.Embed(
                                color=self.bot.get_color(interaction.guild.me), description="### Operação cancelada!"
                            ),
                            view=None,
                        )
                        return

                    interaction = select_interaction

                    select_type = view.selected
                    info = choices[select_type]

                await interaction.response.defer()

                user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

                limit = await quota_for(self.bot, interaction.author, "MAX_USER_FAVS")

                saved = save_track(user_data["fav_links"], info["name"], info["url"], limit=limit)

                if isinstance(saved, RuleError):
                    await interaction.edit_original_message(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me), description=track_fav_error_text(saved)
                        ),
                        view=None,
                    )
                    return

                user_data["fav_links"] = saved.entries

                await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

                self.bot.dispatch("fav_add", interaction.user, user_data, f"[`{info['name']}`]({info['url']})")

                global_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.guilds)

                try:
                    slashcmd = (
                        f"</play:"
                        + str(
                            self.bot.get_global_command_named(
                                "play", cmd_type=disnake.ApplicationCommandType.chat_input
                            ).id
                        )
                        + ">"
                    )
                except AttributeError:
                    slashcmd = "/play"

                await interaction.edit_original_response(
                    embed=disnake.Embed(
                        color=self.bot.get_color(interaction.guild.me),
                        description="### Item adicionado/editado com sucesso nos seus favoritos:\n\n"
                        f"**{select_type}:** [`{info['name']}`]({info['url']})\n\n"
                        f"### Como usar?\n"
                        f"* Usando o comando {slashcmd} (no preenchimento automático da busca)\n"
                        f"* Clicando no botão/select de tocar favorito/integração do player.\n"
                        f"* Usando o comando {global_data['prefix'] or self.bot.default_prefix}{self.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.",
                    ),
                    view=None,
                )

                try:
                    await self.player_interaction_concurrency.release(interaction)
                except Exception:
                    pass

                return

            if control == PlayerControls.lyrics:
                if not player.current:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send("**Não estou tocando algo no momento...**", ephemeral=True)
                    return

                if not player.current.ytid:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send("No momento apenas músicas do youtube são suportadas.", ephemeral=True)
                    return

                not_found_msg = "Não há letras disponíveis para a música atual..."

                await interaction.response.defer(ephemeral=True, with_message=True)

                if player.current.info["extra"].get("lyrics") is None:
                    lyrics_data = await player.node.fetch_ytm_lyrics(player.current.ytid)
                    player.current.info["extra"]["lyrics"] = {} if lyrics_data.get("track") is None else lyrics_data

                elif not player.current.info["extra"]["lyrics"]:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.edit_original_message(f"**{not_found_msg}**")
                    return

                if not player.current.info["extra"]["lyrics"]:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.edit_original_message(f"**{not_found_msg}**")
                    return

                player.current.info["extra"]["lyrics"]["track"]["albumArt"] = player.current.info["extra"]["lyrics"][
                    "track"
                ]["albumArt"][:-1]

                try:
                    lyrics_string = "\n".join([d["line"] for d in player.current.info["extra"]["lyrics"]["lines"]])
                except KeyError:
                    lyrics_string = player.current.info["extra"]["lyrics"]["text"]

                try:
                    await self.player_interaction_concurrency.release(interaction)
                except Exception:
                    pass

                await interaction.edit_original_message(
                    embed=disnake.Embed(
                        description=f"### Letras da música: [{player.current.title}](<{player.current.uri}>)\n{lyrics_string}",
                        color=self.bot.get_color(player.guild.me),
                    )
                )
                return

            if control == PlayerControls.volume:
                cmd_kwargs = {"value": None}

            elif control == PlayerControls.queue:
                cmd = self.bot.get_slash_command("queue").children.get("display")

            elif control == PlayerControls.shuffle:
                cmd = self.bot.get_slash_command("queue").children.get("shuffle")

            elif control == PlayerControls.seek_to_start:
                cmd = self.bot.get_slash_command("seek")
                cmd_kwargs = {"position": "0"}

            elif control == PlayerControls.pause_resume:
                control = PlayerControls.pause if not player.paused else PlayerControls.resume

            elif control == PlayerControls.loop_mode:
                if player.loop == "current":
                    cmd_kwargs["mode"] = "queue"
                elif player.loop == "queue":
                    cmd_kwargs["mode"] = "off"
                else:
                    cmd_kwargs["mode"] = "current"

            elif control == PlayerControls.skip:
                cmd_kwargs = {"query": None, "play_only": "no"}

            if not cmd:
                cmd = self.bot.get_slash_command(control[12:])

            await self.process_player_interaction(interaction=interaction, command=cmd, kwargs=cmd_kwargs)

            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass

        except Exception as e:
            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass
            self.bot.dispatch("interaction_player_error", interaction, e)

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

    async def process_music(
        self,
        inter: Union[
            disnake.Message,
            disnake.MessageInteraction,
            disnake.ApplicationCommandInteraction,
            CustomContext,
            disnake.ModalInteraction,
        ],
        player: LavalinkPlayer,
        force_play: str = "no",
        ephemeral=True,
        log_text="",
        emoji="",
        warn_message: str = "",
        user_data: dict = None,
        reg_query: dict = None,
    ):
        if not player.current:
            if warn_message:
                player.set_command_log(emoji="⚠️", text=warn_message)
            await player.process_next()
        elif force_play == "yes":
            player.set_command_log(
                emoji="▶️", text=f"{inter.author.mention} adicionou a música atual para tocar imediatamente."
            )
            await player.track_end()
            await player.process_next()
        # elif player.current.autoplay:
        #    player.set_command_log(text=log_text, emoji=emoji)
        #    await player.track_end()
        #    await player.process_next()
        else:
            if ephemeral:
                player.set_command_log(text=log_text, emoji=emoji)
            player.update = True

        if reg_query is not None:
            if not user_data:
                user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

            try:
                user_data["last_tracks"].remove(reg_query)
            except Exception:
                pass

            if len(user_data["last_tracks"]) > 6:
                user_data["last_tracks"].pop(0)

            user_data["last_tracks"].append(reg_query)

            await self.bot.update_global_data(inter.author.id, user_data, db_name=DBModel.users)

    async def create_player(
        self,
        inter: Union[
            disnake.Message,
            disnake.MessageInteraction,
            disnake.ApplicationCommandInteraction,
            CustomContext,
            disnake.ModalInteraction,
        ],
        bot: BotCore,
        guild: disnake.Guild,
        channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.Thread],
        guild_data: dict = None,
        message_inter=None,
        node: wavelink.Node = None,
        modal_message_id: int = None,
    ):
        try:
            return bot.music.players[guild.id]
        except KeyError:
            pass

        if not guild_data:
            guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        skin = guild_data["player_controller"]["skin"]
        static_skin = guild_data["player_controller"]["static_skin"]
        static_player = guild_data["player_controller"]

        if not node:
            node = await self.get_best_node(bot)

        global_data = await bot.get_global_data(guild.id, db_name=DBModel.guilds)

        try:
            vc = inter.author.voice.channel
        except AttributeError:
            vc = None

        if global_data["global_skin"]:
            skin = global_data["player_skin"] or skin
            static_skin = global_data["player_skin_static"] or guild_data["player_controller"]["static_skin"]

        try:
            invite = global_data["listen_along_invites"][str(vc.id)]
        except (AttributeError, KeyError):
            invite = ""

        if invite:
            try:
                invite = (await bot.fetch_invite(invite)).url
            except disnake.NotFound:
                invite = None
            except Exception:
                traceback.print_exc()
            else:
                try:
                    if invite.channel.id != vc.id:
                        invite = None
                except AttributeError:
                    pass

        if invite is None:
            try:
                del global_data["listen_along_invites"][str(vc.id)]
            except KeyError:
                pass
            else:
                print(
                    f"{'-' * 15}\n"
                    f"Removendo invite: {invite} \n"
                    + (f"Servidor: {vc.guild.name} [{vc.guild.id}]\nCanal: {vc.name} [{vc.id}]\n" if vc else "")
                    + f"{'-' * 15}"
                )
                await self.bot.update_global_data(inter.guild_id, global_data, db_name=DBModel.guilds)

        try:
            guild_id = inter.guild.id
        except AttributeError:
            guild_id = inter.guild_id

        skins = await load_custom_skins(bot, guild_id, global_data)

        static_channel = None

        if static_player["channel"]:
            try:
                static_channel = bot.get_channel(int(static_player["channel"])) or await bot.fetch_channel(
                    int(static_player["channel"])
                )
            except disnake.Forbidden:
                pass
            except disnake.NotFound:
                await self.reset_controller_db(inter.guild_id, guild_data, inter)

            allowed_channel = None

            for ch in (static_channel, channel):
                if not ch:
                    continue

                if isinstance(ch, disnake.Thread):
                    if not ch.parent:
                        await self.reset_controller_db(inter.guild_id, guild_data, inter)
                        continue

                    channel_check = ch.parent

                else:
                    channel_check = ch

                bot_perms = channel_check.permissions_for(guild.me)

                if bot_perms.read_message_history:
                    allowed_channel = ch
                    break

                elif bot_perms.manage_permissions:
                    overwrites = {
                        guild.me: disnake.PermissionOverwrite(
                            embed_links=True,
                            send_messages=True,
                            send_messages_in_threads=True,
                            read_messages=True,
                            create_public_threads=True,
                            read_message_history=True,
                            manage_messages=True,
                            manage_channels=True,
                            attach_files=True,
                        )
                    }

                    await channel_check.edit(overwrites=overwrites)
                    allowed_channel = ch
                    break

            channel = allowed_channel

        player: LavalinkPlayer = bot.music.get_player(
            guild_id=guild_id,
            cls=LavalinkPlayer,
            player_creator=inter.author.id,
            guild=guild,
            channel=channel,
            last_message_id=guild_data["player_controller"]["message_id"],
            node_id=node.identifier,
            static=bool(static_channel),
            skin=bot.pool.check_skin(skin),
            skin_static=bot.pool.check_static_skin(static_skin),
            custom_skin_data=skins.normal,
            custom_skin_static_data=skins.static,
            extra_hints=self.extra_hints,
            restrict_mode=guild_data["enable_restrict_mode"],
            listen_along_invite=invite,
            autoplay=guild_data["autoplay"],
            prefix=global_data["prefix"] or bot.default_prefix,
            stage_title_template=global_data["voice_channel_status"],
        )

        if (vol := int(guild_data["default_player_volume"])) != 100:
            await player.set_volume(vol)

        if not player.message and player.text_channel:
            try:
                player.message = await player.text_channel.fetch_message(int(static_player["message_id"]))
            except TypeError:
                player.message = None
            except Exception:
                traceback.print_exc()
                if (
                    hasattr(player.text_channel, "parent")
                    and isinstance(player.text_channel.parent, disnake.ForumChannel)
                    and str(player.text_channel.id) == static_player["message_id"]
                ):
                    pass
                elif player.static:
                    player.text_channel = None

        if not player.static and player.text_channel:
            if message_inter and inter.bot != bot:
                player.message = message_inter
            elif modal_message_id:
                try:
                    player.message = await player.text_channel.fetch_message(modal_message_id)
                except Exception:
                    pass

            if not player.has_thread:
                player.message = None
            else:
                await self.thread_song_request(message_inter.thread, reopen=True, bot=bot)

        return player

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

    async def cog_check(self, ctx: CustomContext) -> bool:
        return await check_requester_channel(ctx)

    def cog_unload(self):
        try:
            self.error_report_task.cancel()
        except Exception:
            pass

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

    @commands.Cog.listener("on_wavelink_node_connection_closed")
    async def node_connection_closed(self, node: wavelink.Node):
        try:
            self.bot.wavelink_node_reconnect_tasks[node.identifier].cancel()
        except Exception:
            pass

        self.bot.wavelink_node_reconnect_tasks[node.identifier] = self.bot.loop.create_task(self.node_reconnect(node))

    async def node_reconnect(self, node: wavelink.Node):
        retries = 0
        backoff = 7

        if ((dt_now := datetime.datetime.now(datetime.timezone.utc)) - node._retry_dt).total_seconds() < 7:
            node._retry_count += 1
        if node._retry_count >= 4:
            print(f"❌ - {self.bot.user} - [{node.identifier} / v{node.version}] Reconexão cancelada.")
            node._retry_count = 0
            return
        else:
            node._retry_dt = dt_now

        print(
            f"⚠️ - {self.bot.user} - [{node.identifier} / v{node.version}] Conexão perdida - reconectando em {int(backoff)} segundos."
        )

        while True:
            if node.is_available:
                return

            for player in list(node.players.values()):
                try:
                    player._new_node_task.cancel()
                except Exception:
                    pass

                player._new_node_task = player.bot.loop.create_task(player._wait_for_new_node())

            if (
                self.bot.config["LAVALINK_RECONNECT_RETRIES"]
                and retries == self.bot.config["LAVALINK_RECONNECT_RETRIES"]
            ):
                print(f"❌ - {self.bot.user} - [{node.identifier}] Todas as tentativas de reconectar falharam...")
                return

            await self.bot.wait_until_ready()

            try:
                async with self.bot.session.get(f"{node.rest_uri}/v4/info", timeout=45, headers=node.headers) as r:
                    if r.status == 200:
                        node.version = 4
                        node.update_info(await r.json())
                    elif r.status != 404:
                        raise Exception(f"{self.bot.user} - [{r.status}]: {await r.text()}"[:300])
                    else:
                        node.version = 3
                        node.info["sourceManagers"] = ["youtube", "soundcloud", "http"]

                await node._websocket._connect()
                return
            except Exception as e:
                error = repr(e)

            backoff *= 1.5
            if node.identifier != "LOCAL":
                print(
                    f"⚠️ - {self.bot.user} - Falha ao reconectar no servidor [{node.identifier}] nova tentativa em {int(backoff)}"
                    f" segundos. Erro: {error}"[:300]
                )
            await asyncio.sleep(backoff)
            retries += 1

    def remove_provider(self, lst, queries: list):
        for q in queries:
            try:
                lst.remove(q)
            except Exception:
                continue

    def add_provider(self, lst, queries: list):
        for q in queries:
            if q in lst:
                lst.remove(q)
            lst.append(q)

    @commands.Cog.listener("on_wavelink_node_ready")
    async def node_ready(self, node: wavelink.Node):
        print(f"🌋 - {self.bot.user} - Servidor de música: [{node.identifier} / v{node.version}] está pronto para uso!")
        retries = 25
        while retries > 0:
            if not node._websocket.is_connected:
                return

            if not node.stats:
                await asyncio.sleep(5)
                retries -= 1
                continue

            if "deezer" not in node.info["sourceManagers"]:
                self.remove_provider(node.search_providers, ["dzsearch"])
                self.remove_provider(
                    node.partial_providers,
                    ["dzisrc:{isrc}", "dzsearch:{author} - {title}", "dzsearch:{title} - {author}"],
                )
                try:
                    node.native_sources.remove("deezer")
                except Exception:
                    pass
            elif "dzsearch" not in node.search_providers:
                node.native_sources.add("deezer")
                self.add_provider(node.search_providers, ["dzsearch"])
                self.add_provider(node.partial_providers, ["dzisrc:{isrc}", "dzsearch:{title} - {author}"])
            else:
                node.native_sources.add("deezer")

            if "tidal" not in node.info["sourceManagers"] or node.only_use_native_search_providers is True:
                self.remove_provider(node.search_providers, ["tdsearch"])
                self.remove_provider(
                    node.partial_providers, ["tdsearch:{author} - {title}", "tdsearch:{title} - {author}"]
                )
            elif "tdsearch" not in node.search_providers and node.only_use_native_search_providers is False:
                self.add_provider(node.search_providers, ["tdsearch"])
                self.add_provider(node.partial_providers, ["tdsearch:{title} - {author}"])

            if "applemusic" not in node.info["sourceManagers"] or node.only_use_native_search_providers is True:
                self.remove_provider(node.search_providers, ["amsearch"])
                self.remove_provider(
                    node.partial_providers, ["amsearch:{author} - {title}", "amsearch:{title} - {author}"]
                )
            elif "amsearch" not in node.search_providers and node.only_use_native_search_providers is False:
                self.add_provider(node.search_providers, ["amsearch"])
                self.add_provider(node.partial_providers, ["amsearch:{title} - {author}"])

            if "bandcamp" not in node.info["sourceManagers"]:
                self.remove_provider(node.search_providers, ["bcsearch"])
                self.remove_provider(
                    node.partial_providers, ["bcsearch:{author} - {title}", "bcsearch:{title} - {author}"]
                )

            if "spotify" not in node.info["sourceManagers"] or node.only_use_native_search_providers is True:
                self.remove_provider(node.search_providers, ["spsearch"])
                self.remove_provider(
                    node.partial_providers, ["spsearch:{author} - {title}", "spsearch:{title} - {author}"]
                )
            elif "spsearch" not in node.search_providers and node.only_use_native_search_providers is False:
                self.add_provider(node.search_providers, ["spsearch"])
                self.add_provider(node.partial_providers, ["spsearch:{title} - {author}"])

            if "youtube" not in node.info["sourceManagers"] and "ytsearch" not in node.original_providers:
                self.remove_provider(node.search_providers, ["ytsearch"])
                self.remove_provider(node.partial_providers, ['ytsearch:"{isrc}"', 'ytsearch:"{title} - {author}"'])
            elif "ytsearch" not in node.search_providers:
                if "ytsearch" in node.original_providers:
                    self.add_provider(node.search_providers, ["ytsearch"])
                    self.add_provider(node.partial_providers, ['ytsearch:"{isrc}"', 'ytsearch:"{title} - {author}"'])

            if "youtube" not in node.info["sourceManagers"] and "ytmsearch" not in node.original_providers:
                self.remove_provider(node.search_providers, ["ytmsearch"])
                self.remove_provider(node.partial_providers, ['ytmsearch:"{isrc}"', 'ytmsearch:"{title} - {author}"'])
            elif "ytmsearch" not in node.search_providers:
                if "ytmsearch" in node.original_providers:
                    self.add_provider(node.search_providers, ["ytmsearch"])
                    self.add_provider(node.partial_providers, ['ytmsearch:"{isrc}"', 'ytmsearch:"{title} - {author}"'])

            if "soundcloud" not in node.info["sourceManagers"]:
                self.remove_provider(node.search_providers, ["scsearch"])
                self.remove_provider(
                    node.partial_providers, ["scsearch:{author} - {title}", "scsearch:{title} - {author}"]
                )
            elif "scsearch" not in node.search_providers:
                self.add_provider(node.search_providers, ["scsearch"])
                self.add_provider(node.partial_providers, ["scsearch:{title} - {author}"])

            if "jiosaavn" not in node.info["sourceManagers"]:
                self.remove_provider(node.search_providers, ["jssearch"])
                # self.remove_provider(node.partial_providers, ["jssearch:{title} - {author}"])
            elif "jssearch" not in node.search_providers:
                self.add_provider(node.search_providers, ["jssearch"])
                # self.add_provider(node.partial_providers, ["jssearch:{title} {author}"])

            if node.stats.uptime < 600000:
                node.open()
            return

    async def connect_node(self, data: dict):
        if data["identifier"] in self.bot.music.nodes:
            node = self.bot.music.nodes[data["identifier"]]
            try:
                if not node._websocket.is_connected:
                    await node.connect()
            except AttributeError:
                pass
            return

        data = deepcopy(data)

        data["rest_uri"] = ("https" if data.get("secure") else "http") + f"://{data['host']}:{data['port']}"
        # data['user_agent'] = self.bot.pool.current_useragent
        search = data.pop("search", True)
        node_website = data.pop("website", "")
        region = data.pop("region", "us_central")
        heartbeat = int(data.pop("heartbeat", 30))
        search_providers = data.pop("search_providers", None) or ["ytsearch", "scsearch"]
        info = data.pop("info", {})

        try:
            max_retries = int(data.pop("retries"))
        except (TypeError, KeyError):
            max_retries = 1

        node = await self.bot.music.initiate_node(
            auto_reconnect=False, region=region, heartbeat=heartbeat, max_retries=max_retries, **data
        )
        node.info = info
        node.search = search
        node.website = node_website
        node.search_providers = search_providers
        node.original_providers = set(node.search_providers)
        node.partial_providers = []
        node.native_sources = deepcopy(native_sources)
        node.prefer_youtube_native_playback = data.pop("prefer_youtube_native_playback", True)
        node.only_use_native_search_providers = data.pop("only_use_native_search_providers", True)

        for p in node.search_providers:
            if p == "dzsearch":
                node.partial_providers.append("dzisrc:{isrc}")
                node.partial_providers.append("dzsearch:{title} - {author}")
            elif p == "tdsearch":
                node.partial_providers.append("tdsearch:{title} - {author}")
            elif p == "amsearch":
                node.partial_providers.append("amsearch:{title} - {author}")
            elif p == "spsearch":
                node.partial_providers.append("spsearch:{title} - {author}")
            elif p == "bcsearch":
                node.partial_providers.append("bcsearch:{title} - {author}")
            elif p == "ytsearch":
                node.partial_providers.append('ytsearch:"{isrc}"')
                node.partial_providers.append('ytsearch:"{title} - {author}"')
            elif p == "ytmsearch":
                node.partial_providers.append('ytmsearch:"{isrc}"')
                node.partial_providers.append('ytmsearch:"{title} - {author}"')
            elif p == "scsearch":
                node.partial_providers.append("scsearch:{title} - {author}")

        await node.connect(info=info)

    async def get_partial_tracks(
        self,
        query: str,
        ctx: Union[disnake.ApplicationCommandInteraction, CustomContext, disnake.MessageInteraction, disnake.Message],
        user: disnake.Member,
        node: wavelink.Node = None,
        bot: BotCore = None,
    ):
        if not bot:
            bot = self.bot

        tracks = []

        exceptions = set()

        if bot.pool.config["FORCE_USE_DEEZER_CLIENT"] or [
            n for n in bot.music.nodes.values() if "deezer" not in n.info.get("sourceManagers", [])
        ]:
            try:
                tracks = await self.bot.pool.deezer.get_tracks(
                    url=query, requester=user.id, search=True, check_title=80
                )
            except Exception as e:
                self.bot.dispatch("custom_error", ctx=ctx, error=e)
                exceptions.add(repr(e))

        if (
            not tracks
            and bot.spotify
            and not [n for n in bot.music.nodes.values() if "spotify" in n.info.get("sourceManagers", [])]
        ):
            try:
                tracks = await self.bot.pool.spotify.get_tracks(self.bot, user.id, query, search=True, check_title=80)
            except Exception as e:
                self.bot.dispatch("custom_error", ctx=ctx, error=e)
                exceptions.add(repr(e))

        return tracks, node, exceptions

    async def get_lavalink_tracks(
        self,
        query: str,
        ctx: Union[disnake.ApplicationCommandInteraction, CustomContext, disnake.MessageInteraction, disnake.Message],
        user: disnake.Member,
        node: wavelink.Node = None,
        source=None,
        bot: BotCore = None,
    ):
        if not bot:
            bot = self.bot

        if not node:
            nodes = sorted(
                [n for n in bot.music.nodes.values() if n.is_available and n.available], key=lambda n: len(n.players)
            )
        else:
            nodes = sorted(
                [n for n in bot.music.nodes.values() if n != node and n.is_available and n.available],
                key=lambda n: len(n.players),
            )
            nodes.insert(0, node)

        if not nodes:
            raise GenericError("**Não há servidores de música disponível!**")

        exceptions = set()

        tracks = []

        is_spotify_url = bool(spotify_regex_w_user.match(query) or spotify_link_regex.match(query))

        for n in nodes:
            if is_spotify_url and "spotify" not in n.info.get("sourceManagers", []):
                if not node:
                    node = n
                continue

            node_retry = False

            if source is False:
                providers = n.search_providers[:1]
                if query.startswith("https://www.youtube.com/live/"):
                    query = query.split("?")[0].replace("/live/", "/watch?v=")

                elif query.startswith("https://listen.tidal.com/album/") and "/track/" in query:
                    query = f"http://www.tidal.com/track/{query.split('/track/')[-1]}"

                elif query.startswith(("https://youtu.be/", "https://www.youtube.com/")):
                    for p in ("&ab_channel=", "&start_radio="):
                        if p in query:
                            try:
                                query = f"https://www.youtube.com/watch?v={re.search(r'v=([a-zA-Z0-9_-]+)', query).group(1)}"
                            except Exception:
                                pass
                            break
            elif source:
                providers = [s for s in n.search_providers if s != source]
                providers.insert(0, source)
            else:
                source = True
                providers = n.search_providers

            for search_provider in providers:
                tracks = None

                search_query = query

                if source:
                    if search_provider not in n.search_providers:
                        try:
                            if search_provider.startswith("dzsearch"):
                                tracks = await self.bot.pool.deezer.get_tracks(
                                    url=query, requester=user.id, search=True, check_title=50
                                )
                            elif search_provider.startswith("spsearch"):
                                tracks = await self.bot.pool.spotify.get_tracks(
                                    self.bot, user.id, query, search=True, check_title=50
                                )
                            else:
                                continue

                            if tracks:
                                return tracks, node, exceptions
                            else:
                                continue

                        except Exception as e:
                            self.bot.dispatch("custom_error", ctx=ctx, error=e)
                            exceptions.add(repr(e))
                            continue
                    else:
                        search_query = f"{search_provider}:{query}"

                try:
                    tracks = await n.get_tracks(
                        search_query,
                        track_cls=LavalinkTrack,
                        playlist_cls=LavalinkPlaylist,
                        requester=user.id,
                        # check_title=80
                    )
                except Exception as e:
                    # traceback.print_exc()
                    exceptions.add(repr(e))

                    if not isinstance(e, wavelink.TrackNotFound):
                        print(f"Falha ao processar busca...\n{query}\n{traceback.format_exc()}")
                        node_retry = True
                    elif not isinstance(e, GenericError):
                        self.bot.dispatch("custom_error", ctx=ctx, error=e)

                if tracks or not source:
                    break

            if not node_retry:
                node = n
                break

        return tracks, node, exceptions

    async def get_tracks(
        self,
        query: str,
        ctx: Union[disnake.ApplicationCommandInteraction, CustomContext, disnake.MessageInteraction, disnake.Message],
        user: disnake.Member,
        node: wavelink.Node = None,
        source=None,
        bot: BotCore = None,
        mix=False,
    ):
        exceptions = set()

        if mix:
            if not self.bot.pool.last_fm:
                raise GenericError(
                    "**No momento não há suporte a mix/recomendações devido o Last.fm não ter sido configurado na minha estrutura.**"
                )

            query = query.title()

            try:
                artist, track = query.split(" - ", 1)
            except Exception:
                try:
                    artist, track = query.split(" ", 1)
                except Exception:
                    raise GenericError("Você deve informar sua busca dessa forma: nome do artista - nome da música")

            current = None

            try:
                info = await self.bot.pool.last_fm.get_similar_tracks(track=track, artist=artist)
            except Exception as e:
                exceptions.add(e)
                info = []

            if not info:
                try:
                    info = await self.bot.pool.last_fm.get_artist_toptracks(artist)
                except Exception as e:
                    exceptions.add(e)

                if not info:
                    txt = f"**Não houve resultados de mixes para sua busca: {artist} - {track}**"
                    raise GenericError(txt, error="\n".join(repr(e) for e in exceptions) or None)

                track_url = f"https://www.last.fm/music/{quote(artist)}"
                playlist_name = f"TopTracks: {artist}"

            else:
                track_url = f"https://www.last.fm/music/{quote(artist)}/_/{quote(track)}"
                playlist_name = f"Mix: {artist} - {track}"
                current = PartialTrack(
                    uri=track_url,
                    title=track,
                    author=artist,
                    requester=user.id,
                    source_name="last.fm",
                )

            playlist = PartialPlaylist(url=track_url, data={"playlistInfo": {"name": playlist_name}})

            playlist.tracks = [
                PartialTrack(
                    uri=i["url"],
                    title=i["name"],
                    author=i["artist"]["name"],
                    requester=user.id,
                    source_name="last.fm",
                )
                for i in info
            ]

            if current:
                playlist.tracks.insert(0, current)

            return playlist, node

        if bool(sc_recommended.search(query)):
            try:
                info = await bot.loop.run_in_executor(
                    None, lambda: self.bot.pool.ytdl.extract_info(query, download=False)
                )
            except AttributeError:
                raise GenericError("**O uso do yt-dlp está desativado...**")

            playlist = PartialPlaylist(url=info["webpage_url"], data={"playlistInfo": {"name": info["title"]}})

            playlist.tracks = [
                PartialTrack(
                    uri=i["url"],
                    title=i["title"],
                    requester=user.id,
                    source_name="soundcloud",
                    identifier=i["id"],
                    playlist=playlist,
                )
                for i in info["entries"]
            ]

            return playlist, node

        tracks, node, exceptions = await self.get_lavalink_tracks(
            query=query, user=user, ctx=ctx, node=node, bot=bot, source=source
        )

        if not tracks:
            tracks, node, exceptions = await self.get_partial_tracks(
                query=query, ctx=ctx, user=user, node=node, bot=bot
            )

            if not tracks:
                txt = "\n".join(exceptions)

                if txt:
                    if "This track is not readable. Available countries:" in txt:
                        raise GenericError(
                            "**A música informada não está disponível na minha região atual...**", error=txt
                        )
                    raise GenericError(
                        "**Não foi possível concluir sua busca agora. Tente novamente em instantes "
                        "ou use outro termo/link.**",
                        error=txt,
                    )
                raise GenericError("**Não houve resultados para sua busca.**")

        return tracks, node

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

    @commands.Cog.listener("on_voice_state_update")
    async def player_vc_disconnect(self, member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
        try:
            player: LavalinkPlayer = self.bot.music.players[member.guild.id]
        except KeyError:
            return

        if before.channel and not after.channel:
            if player.last_channel != before.channel:
                return

        elif after.channel and not before.channel:
            if player.last_channel != after.channel:
                return

        if member.bot:
            # ignorar outros bots
            if player.bot.user.id == member.id and not after.channel:
                await asyncio.sleep(3)

                if player.is_closing:
                    return

                try:
                    player.reconnect_voice_channel_task.cancel()
                except Exception:
                    pass
                player.reconnect_voice_channel_task = player.bot.loop.create_task(player.reconnect_voice_channel())

            return

        if before.channel == after.channel:
            try:
                vc = player.last_channel
                if vc != after.channel:
                    return
            except AttributeError:
                pass
            else:
                if after.channel == vc:
                    try:
                        player.members_timeout_task.cancel()
                    except Exception:
                        pass
                    try:
                        check = (m for m in vc.members if not m.bot and not (m.voice.deaf or m.voice.self_deaf))
                    except Exception:
                        check = None
                    player.start_members_timeout(check=bool(check))
            return

        try:
            player.members_timeout_task.cancel()
            player.members_timeout_task = None
        except AttributeError:
            pass

        if member.id == player.bot.user.id:
            """for b in self.bot.pool.get_guild_bots(member.guild.id):
                if b == player.bot:
                    if after.channel:
                        player._last_channel = after.channel
                    continue
                try:
                    try:
                        after.channel.voice_states[b.user.id]
                    except KeyError:
                        continue
                    if before.channel.permissions_for(member.guild.me).connect:
                        await asyncio.sleep(1)
                        await player.guild.voice_client.move_to(before.channel)
                    else:
                        player.set_command_log(text="O player foi finalizado porque me moveram ao canal "
                                                    f"{after.channel.mention} no qual o bot {b.user.mention} "
                                                    "também estava conectado gerando incompatibilidade com "
                                                    "meu sistema de multi-voice.", emoji="⚠️")
                        await player.destroy()
                    return
                except AttributeError:
                    pass
                except Exception:
                    traceback.print_exc()"""

            try:
                vc = member.guild.me.voice.channel
            except AttributeError:
                pass
            else:
                # tempfix para channel do voice_client não ser setado ao mover bot do canal.
                player.guild.voice_client.channel = vc
                player._last_channel = vc
                player.update = True

        try:
            check = [
                m
                for m in player.guild.me.voice.channel.members
                if not m.bot and not (m.voice.deaf or m.voice.self_deaf)
            ]
        except Exception:
            check = None

        if player.stage_title_event and member.bot and not player.is_closing:
            try:
                if isinstance(before.channel, disnake.StageChannel):
                    if before.channel.instance and member not in before.channel.members:
                        try:
                            await before.channel.instance.edit(topic="atualização automática desativada")
                        except Exception:
                            traceback.print_exc()
                        player.stage_title_event = False

                else:
                    if isinstance(before.channel, disnake.VoiceChannel) and member not in before.channel.members:
                        player.stage_title_event = False
                        if player.last_stage_title:
                            self.bot.loop.create_task(
                                player.bot.edit_voice_channel_status(status=None, channel_id=before.channel.id)
                            )
            except Exception:
                traceback.print_exc()

        if (
            member.bot
            and isinstance(after.channel, disnake.StageChannel)
            and after.channel.permissions_for(member).mute_members
        ):
            await asyncio.sleep(1.5)
            if member not in after.channel.speakers:
                try:
                    await member.guild.me.edit(suppress=False)
                except Exception:
                    traceback.print_exc()

        if check:
            try:
                player.auto_skip_track_task.cancel()
            except AttributeError:
                pass
            player.auto_skip_track_task = None

        player.start_members_timeout(check=bool(check))

        if not member.guild.me.voice:
            await asyncio.sleep(1)
            if not player.is_closing and not player._new_node_task:
                try:
                    await player.destroy(force=True)
                except Exception:
                    traceback.print_exc()

        # rich presence stuff

        if player.auto_pause:
            return

        if player.is_closing or (member.bot and not before.channel):
            return

        channels = set()

        try:
            channels.add(before.channel.id)
        except Exception:
            pass

        try:
            channels.add(after.channel.id)
        except Exception:
            pass

        try:
            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                vc = player.last_channel

            if vc.id not in channels:
                return
        except AttributeError:
            pass

        if not after or before.channel != after.channel:
            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                vc = before.channel

            if vc:
                try:
                    await player.process_rpc(
                        vc,
                        users=[member.id],
                        close=not player.guild.me.voice or after.channel != player.guild.me.voice.channel,
                        wait=True,
                    )
                except AttributeError:
                    traceback.print_exc()
                    pass

                await player.process_rpc(vc, users=[m for m in vc.voice_states if (m != member.id)])

    async def check_available_bot(
        self, inter, guild: disnake.Guild, bot: BotCore = None, message: disnake.Message = None
    ):
        free_bots = []
        voice_channels = []
        bot_count = 0

        if bot:
            try:
                player = bot.music.players[guild.id]
            except KeyError:
                pass
            else:
                if player.guild.me.voice and inter.author.id in player.guild.me.voice.channel.voice_states:
                    return [bot]

        for b in self.bot.pool.get_guild_bots(guild.id):
            if not b.bot_ready:
                continue

            g = b.get_guild(guild.id)

            if not g:
                bot_count += 1
                continue

            author = g.get_member(inter.author.id)

            if not author:
                continue

            inter.author = author

            if b.user in inter.author.voice.channel.members:
                free_bots.append(b)
                break

            p: LavalinkPlayer = b.music.players.get(guild.id)

            if p:
                try:
                    vc = g.me.voice.channel
                except AttributeError:
                    vc = p.last_channel

                if not vc:
                    continue

                if inter.author.id in vc.members:
                    free_bots.append(b)
                    break
                else:
                    voice_channels.append(vc.mention)
                    continue

            free_bots.append(b)

        if not free_bots:
            if bot_count:
                txt = "**Todos os bots estão em uso no nomento...**"
                if voice_channels:
                    txt += "\n\n**Você pode conectar em um dos canais abaixo onde há sessões ativas:**\n" + ", ".join(
                        voice_channels
                    )
                    if inter.author.guild_permissions.manage_guild:
                        txt += "\n\n**Ou se preferir: Adicione mais bots de música no servidor atual clicando no botão abaixo:**"
                    else:
                        txt += (
                            "\n\n**Ou se preferir: Solicite a um administrador/manager do servidor para clicar no botão abaixo "
                            "para adicionar mais bots de música no servidor atual.**"
                        )
            else:
                txt = (
                    "**Não há bots de música compatíveis no servidor...**"
                    "\n\nSerá necessário adicionar pelo menos um bot compatível clicando no botão abaixo:"
                )

            kwargs = {}

            try:
                func = inter.edit_original_message
            except Exception:
                try:
                    func = inter.store_message.edit
                except Exception:
                    try:
                        func = message.edit
                    except Exception:
                        func = inter.send
                        kwargs["ephemeral"] = True

            await func(txt, components=[disnake.ui.Button(custom_id="bot_invite", label="Adicionar bots")], **kwargs)
            return []

        return free_bots

    async def reset_controller_db(self, guild_id: int, data: dict, inter: disnake.ApplicationCommandInteraction = None):
        data["player_controller"]["channel"] = None
        data["player_controller"]["message_id"] = None

        if inter:
            try:
                bot = inter.music_bot
            except AttributeError:
                bot = inter.bot
        else:
            bot = self.bot

        try:
            await bot.update_data(guild_id, data, db_name=DBModel.guilds)
        except Exception:
            traceback.print_exc()

        try:
            player: LavalinkPlayer = bot.music.players[guild_id]
        except KeyError:
            return

        player.static = False

        if inter:
            try:
                if isinstance(inter.channel.parent, disnake.TextChannel):
                    player.text_channel = inter.channel.parent
                else:
                    player.text_channel = inter.channel
            except AttributeError:
                player.text_channel = inter.channel

    async def get_best_node(self, bot: BotCore = None):
        if not bot:
            bot = self.bot

        try:
            return sorted(
                [n for n in bot.music.nodes.values() if n.stats and n.is_available and n.available],
                key=lambda n: n.stats.players,
            )[0]

        except IndexError:
            try:
                node = bot.music.nodes["LOCAL"]
            except KeyError:
                pass
            else:
                if not node._websocket.is_connected:
                    await node.connect()
                return node

            raise GenericError("**Não há servidores de música disponível.**")

    async def error_report_loop(self):
        while True:
            data = await self.error_report_queue.get()

            async with aiohttp.ClientSession() as session:
                webhook = disnake.Webhook.from_url(self.bot.config["AUTO_ERROR_REPORT_WEBHOOK"], session=session)
                await webhook.send(
                    username=self.bot.user.display_name, avatar_url=self.bot.user.display_avatar.url, **data
                )

            await asyncio.sleep(15)


def setup(bot: BotCore):
    if not getattr(bot.pool, "ytdl", None):
        bot.pool.ytdl = CustomYTDL(
            {
                "format": "webm[abr>0]/bestaudio/best",
                "extract_flat": True,
                "quiet": True,
                "no_warnings": True,
                "lazy_playlist": True,
                "playlist_items": "1-700",
                "simulate": True,
                "download": False,
                "cachedir": False,
                "allowed_extractors": [
                    r".*youtube.*",
                    r".*soundcloud.*",
                ],
                "extractor_args": {
                    "youtube": {
                        #'player_client': [
                        #    'web',
                        #    'android',
                        #    'android_creator',
                        #    'web_creator',
                        # ],
                        "max_comments": [0],
                    },
                    "youtubetab": {"skip": ["webpage", "authcheck"]},
                },
            }
        )

    bot.add_cog(Music(bot))

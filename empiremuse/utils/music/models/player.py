# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import pprint
import traceback
from collections import deque
from itertools import cycle
from time import time
from typing import Optional, Union, TYPE_CHECKING

import disnake
from rapidfuzz import fuzz

import empiremuse.wavelink as wavelink
from empiremuse.rules.text import plain_snippet
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.checks import can_connect
from empiremuse.utils.music.converters import fix_characters, time_format
from empiremuse.utils.music.errors import (
    GenericError,
    PoolException,
    code_suffix,
    error_code_text,
    log_unexpected_error,
)
from empiremuse.utils.music.lastfm_tools import LastFmException
from empiremuse.utils.music.skin_utils import skin_converter
from empiremuse.utils.others import music_source_emoji, PlayerControls, string_to_file
from empiremuse.wavelink import TrackStart, TrackEnd

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

from empiremuse.utils.music.models.helpers import (
    exclude_tags,
    exclude_tags_2,
    TITLE_MATCH_THRESHOLD,
    emoji_pattern,
    logger,
    lavalink_text,
    log_lavalink_failure,
    providers_dict,
    native_sources,
    get_start_pos,
)
from empiremuse.utils.music.models.tracks import (
    PartialTrack,
    LavalinkPlaylist,
    LavalinkTrack,
)
from empiremuse.utils.music.models.player_filters import PlayerFiltersMixin
from empiremuse.utils.music.models.player_state import PlayerStateMixin
from empiremuse.utils.music.models.player_message import PlayerMessageMixin


class LavalinkPlayer(PlayerFiltersMixin, PlayerStateMixin, PlayerMessageMixin, wavelink.Player):
    bot: BotCore

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.version = 1.1
        self.volume = 100
        self.guild: disnake.Guild = kwargs.pop("guild")
        self.text_channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.Thread] = kwargs.pop("channel")
        self.message: Optional[disnake.Message] = kwargs.pop("message", None)
        self.static: bool = kwargs.pop("static", False)
        self.skin: str = kwargs.pop("skin", None) or self.bot.pool.default_skin
        self.skin_static: str = kwargs.pop("skin_static", None) or self.bot.pool.default_static_skin
        self.custom_skin_data = kwargs.pop("custom_skin_data", {})
        self.custom_skin_static_data = kwargs.pop("custom_skin_static_data", {})
        self.queue: deque = deque()
        self.played: deque = deque(maxlen=20)
        self.queue_autoplay: deque = deque(maxlen=30)
        self.failed_tracks: deque = deque(maxlen=30)
        self.command_log_list = deque(maxlen=10)
        self.autoplay: bool = kwargs.pop("autoplay", False)
        self.nightcore: bool = False
        self.loop = False
        self.last_track: Optional[LavalinkTrack] = None
        self.locked: bool = False
        self.is_previows_music: bool = False
        self.interaction_cooldown: bool = False
        self.votes: set = set()
        self.dj: set = set()
        self.player_creator: Optional[int] = kwargs.pop("player_creator", None)
        self.filters: dict = {}
        self.idle_task: Optional[asyncio.Task] = None
        self.members_timeout_task: Optional[asyncio.Task] = None
        self.reconnect_voice_channel_task: Optional[asyncio.Task] = None
        self.idle_endtime: Optional[datetime.datetime] = None
        self.idle_start_timestamp: Optional[int] = None
        self.hint_rate = self.bot.config["HINT_RATE"]
        self.command_log: str = ""
        self.command_log_emoji: str = ""
        self.is_closing: bool = False
        self.last_message_id: Optional[int] = kwargs.pop("last_message_id", None)
        self.keep_connected: bool = kwargs.pop("keep_connected", False)
        self.update: bool = False
        self.updating: bool = False
        self.auto_update: int = 0
        self.live_lyrics_enabled = False
        self.has_lyrics = False
        self.np_original_data = None
        self.lyric_task: Optional[asyncio.Task] = None
        self.listen_along_invite = kwargs.pop("listen_along_invite", "")
        self.message_updater_task: Optional[asyncio.Task] = None
        # limitar apenas para dj's e staff's
        self.restrict_mode = kwargs.pop("restrict_mode", False)
        self.ignore_np_once = False  # não invocar player controller em determinadas situações
        self.allowed_mentions = disnake.AllowedMentions(users=False, everyone=False, roles=False)
        self.uptime = kwargs.pop("uptime", None) or int(disnake.utils.utcnow().timestamp())
        # ativar/desativar modo controller (apenas para uso em skins)
        self.controller_mode = True
        self.mini_queue_feature = False
        self.mini_queue_enabled = False
        self.is_resuming = False
        self.is_purging = False
        self.auto_pause = False
        self._session_resuming = kwargs.pop("session_resuming", False)
        self._last_channel: Optional[disnake.VoiceChannel] = None
        self._last_channel_id: Optional[int] = None
        self._rpc_update_task: Optional[asyncio.Task] = None
        self._new_node_task: Optional[asyncio.Task] = None
        self._queue_updater_task: Optional[asyncio.Task] = None
        self.auto_skip_track_task: Optional[asyncio.Task] = None
        self.track_load_task: Optional[asyncio.Task] = None
        self.native_yt: bool = True
        self.stage_title_event = False
        self.stage_title_template: str = (
            kwargs.pop("stage_title_template", None) or "Tocando: {track.title} | {track.author}"
        )
        self.last_stage_title = ""

        self.channel_purged = False

        self.temp_embed: Optional[disnake.Embed] = None
        self.prefix_info = kwargs.pop("prefix", "")

        self.start_time = disnake.utils.utcnow()
        self.start_timestamp = self.start_time.timestamp()

        self.lastfm_artists = []

        self.event_queue = asyncio.Queue()

        self.extra_info = {}

        self.initial_hints = [
            f"É possível alterar a skin/aparência do player usando o comando /change_skin ou {self.prefix_info}skin "
            f"(Apenas membros com permissão de gerenciar servidor podem usar esse comando).",
            "Dê uma nova cara para o player de música no servidor criando skins personalizadas. Experimente usando "
            f"o comando /custom_skin ou {self.prefix_info}customskin (Apenas membros com permissão de administrador "
            "podem usar esse comando).",
            "É possível definir o status automático no canal de voz com informações sobre "
            "a música que está sendo tocada no momento. Experimente usando o comando /set_voice_status ou "
            f"{self.prefix_info}stageannounce (Apenas membros com permissão de gerenciar servidor podem usar esse recurso).",
            f"Caso a música esteja com lag, audio travando etc. Experimente alterar a região do canal de voz "
            f"(caso esteja em um palco/stage use o comando {self.prefix_info}stageregion).",
        ]

        self.retry_setup_hints = False

        hint_platforms = ["youtube, soundcloud"]

        if (self.bot.spotify and not self.bot.spotify.disabled) or "spotify" in self.node.info["sourceManagers"]:
            hint_platforms.append("spotify")

        hint_platforms.append("deezer")

        if self.bot.config["LASTFM_KEY"] and self.bot.config["LASTFM_SECRET"]:
            self.initial_hints.append(
                f"Você pode vincular uma conta do last.fm para registrar as músicas que você ouvir por aqui na sua "
                f"lista de músicas tocadas. Experimente usando o comando /lastfm ou {self.prefix_info}lastfm."
            )

        if hint_platforms:
            self.initial_hints.append(
                "Você pode adicionar/integrar link de perfis/canais do " + " e ".join(hint_platforms) + " para tocar "
                f"playlists pública que tem no canal/perfil via comando {self.prefix_info}play (sem incluir "
                "nome/link) ou no comando /play (via preenchimento automático da busca). Experimente usando o "
                f'comando /fav_manager ou {self.prefix_info}favmanager selecionando a opção "integrações".'
            )

        try:
            self.initial_hints.extend(kwargs.pop("extra_hints"))
        except Exception:
            pass

        self.lastfm_users = {}

        self.hints: cycle = []
        self.current_hint: str = ""
        self.last_data: dict = {}
        self.lyric_embed: Optional[disnake.Embed] = None
        self.event_queue_task = self.bot.loop.create_task(self.hook_events())
        self.check_skins()
        self.setup_features()
        self.setup_hints()

        self.bot.dispatch("player_create", player=self)

    def __str__(self) -> str:
        return f"Servidor de música atual: {self.node.identifier} (v{self.node.version})"

    def __repr__(self):
        return (
            f"<volume={self.volume} "
            f"current_position={time_format(self.position) if self.position else 'Idling'} "
            f'queue={len(self.queue)} loop={self.loop} EQ="{self.eq}" guild="{self.guild.name}" '
            f'node="{self.node.identifier}" keep_connected="{self.keep_connected}">'
        )

    @property
    def has_thread(self):
        try:
            if isinstance(self.message.channel.parent, disnake.ForumChannel):
                return
        except AttributeError:
            pass

        return (
            self.message and self.message.thread
        )  # and not (self.message.thread.locked or self.message.thread.archived)

    @property
    def controller_link(self):
        if self.controller_mode:
            try:
                return f" [`🎛️`](<{self.message.jump_url}>)"
            except AttributeError:
                try:
                    return f" [`#️⃣`](<{self.text_channel.jump_url}>)"
                except AttributeError:
                    pass
        return ""

    @property
    def position(self):
        if not self.current:
            return 0

        if not self.is_playing:
            return 0

        if self.paused and not self.auto_pause:
            return min(self.last_position, self.current.duration)

        difference = (time() * 1000) - self.last_update
        position = self.last_position + difference

        if position > self.current.duration:
            return 0

        return min(position, self.current.duration)

    async def update_state(self, state: dict) -> None:
        state = state["state"]

        if not self.auto_pause:
            self.last_position = state.get("position") or 0

        self.last_update = time() * 1000
        self.position_timestamp = state.get("time", 0)
        self.ping = state.get("ping", None)

    async def report_error(
        self, embed: disnake.Embed, track: Union[LavalinkTrack, PartialTrack], error: Exception = None
    ):
        cog = self.bot.get_cog("Music")

        if cog and cog.error_report_queue:
            embed.description += (
                f"\n**Fonte:** `{track.info['sourceName']}`"
                f"\n**Servidor:** `{disnake.utils.escape_markdown(self.guild.name)} [{self.guild.id}]`"
            )

            try:
                embed.description += f"\n**Canal:** `{disnake.utils.escape_markdown(self.guild.me.voice.channel.name)} [{self.guild.me.voice.channel.id}]`\n"
            except Exception:
                pass

            embed.description += f"**Data:** <t:{int(disnake.utils.utcnow().timestamp())}:F>"

            if self.guild.icon:
                embed.set_thumbnail(url=self.guild.icon.with_format("png").url)

            error_kwargs = {"embed": embed}

            if error:
                error_kwargs["file"] = string_to_file(
                    "".join(traceback.format_exception(type(error), error, error.__traceback__)),
                    "error_partialtrack.txt",
                )

            await cog.error_report_queue.put(error_kwargs)

    async def reconnect_voice_channel(self):
        channel_check_retries = 0

        while True:
            try:
                self.bot.music.players[self.guild_id]
            except KeyError:
                return

            try:
                vc = self.bot.get_channel(self.last_channel.id)
            except AttributeError:
                vc = None

            if not vc:
                if channel_check_retries < 3:
                    channel_check_retries += 1
                    await asyncio.sleep(3 * channel_check_retries)
                    continue

                msg = "O canal de voz foi excluido..."

                if self.static:
                    self.set_command_log(msg, controller=True)
                    await self.destroy()
                    return

                else:
                    if self.text_channel:
                        try:
                            self.bot.loop.create_task(
                                self.text_channel.send(
                                    embed=disnake.Embed(description=msg, color=self.bot.get_color(self.guild.me)),
                                    delete_after=7,
                                )
                            )
                        except Exception:
                            traceback.print_exc()
                    await self.destroy()
                    return

            if self.guild.me.voice:
                if (
                    isinstance(vc, disnake.StageChannel)
                    and self.guild.me not in vc.speakers
                    and vc.permissions_for(self.guild.me).mute_members
                ):
                    try:
                        await self.guild.me.edit(suppress=False)
                    except Exception:
                        traceback.print_exc()
                return

            if self.is_closing:
                return

            if not self._new_node_task:
                try:
                    can_connect(vc, self.guild, bot=self.bot)
                except (GenericError, PoolException) as e:
                    self.set_command_log(
                        f"Ocorreu uma falha ao reconectar o player no canal de voz: {e}.", controller=True
                    )
                    self.update = True
                except Exception as e:
                    code = log_unexpected_error(logger, e, "reconexão do player no canal de voz")
                    self.set_command_log(
                        f"Ocorreu uma falha ao reconectar o player no canal de voz{code_suffix(code)}.",
                        controller=True,
                    )
                    self.update = True
                else:
                    if (ping := round(self.bot.latency * 1000)) > 250:
                        voice_msg = f"Reconectei no canal de voz devido a um possível problema de instabilidade ne conexão (ping: {ping}ms)."
                    elif self.keep_connected:
                        voice_msg = f"Notei uma tentativa de me desconectarem do canal <#{vc.id}>."
                    else:
                        voice_msg = None

                    if not voice_msg:
                        self.set_command_log(
                            text=f"O plater foi finalizado por perca de conexão no canal <#{vc.id}>.",
                            emoji="⚠️",
                            controller=True,
                        )
                        await self.destroy()
                        return

                    try:
                        await self.connect(vc.id)
                        self.set_command_log(
                            text=f"{voice_msg}\nCaso realmente queira me desconectar, use o comando/botão: **stop**.",
                            emoji="⚠️",
                            controller=True,
                        )
                        self.update = True
                        await asyncio.sleep(5)
                        continue
                    except Exception:
                        traceback.print_exc()

            await asyncio.sleep(30)

    async def hook(self, event) -> None:
        if isinstance(event, wavelink.WebsocketClosed):
            if event.code == 1000:
                return

            if not self.guild.me or (
                event.code == 4014 and event.reason.startswith("Disconnected") and not self.keep_connected
            ):
                await self.destroy(force=True)
                return

            try:
                vc = self.last_channel or self.guild.me.voice.channel
            except AttributeError:
                vc = None

            if event.code == 4022:
                if self.keep_connected and vc:
                    await asyncio.sleep(5)
                    self.set_command_log(
                        emoji="⚠️",
                        text=f"Caso queira me desconectar do canal {vc.mention} com o modo 24/7 ativo, use o comando ou o botão **stop/parar**.",
                    )
                    await self.connect(vc.id)
                    self.update = True
                else:
                    await self.destroy(force=True)
                    print(f"Bot: {self.bot.user} | Desconectado do canal de voz: {self.guild_id}")
                return

            if event.code == 4014 and self.guild.me.voice:
                pass
            else:
                print(
                    ("-" * 15) + f"\nErro no canal de voz!"
                    f"\nBot: {self.bot.user} [{self.bot.user.id}] | "
                    + ("Online" if self.bot.is_ready() else "Offline")
                    + f"\nGuild: {self.guild.name} [{self.guild.id}]"
                    f"\nCanal: {vc.name} [{vc.id}]"
                    f"\nServer: {self.node.identifier} | code: {event.code} | reason: {event.reason}\n" + ("-" * 15)
                )

            if self.is_closing:
                return

            if event.code in (
                4000,  # internal error
                1006,
                1001,
                4016,  # Connection started elsewhere
                4005,  # Already authenticated.
            ):
                try:
                    vc_id = self.guild.me.voice.channel.id
                except AttributeError:
                    vc_id = self.last_channel.id

                await asyncio.sleep(3)

                if self.is_closing:
                    return

                await self.connect(vc_id)
                return

            if event.code in (
                4014,
                4006,  # Session is no longer valid.
            ):
                await asyncio.sleep(5)

                try:
                    self.bot.music.players[self.guild_id]
                except KeyError:
                    return

                if self.guild and self.guild.me.voice or self.is_closing:
                    return

                try:
                    vc_id = self.guild.me.voice.channel.id
                except AttributeError:
                    vc_id = self.last_channel.id

                await self.connect(vc_id)
                return

        else:
            await self.event_queue.put(event)

    async def hook_events(self):
        while True:
            try:
                event = await self.event_queue.get()

                if self.is_closing:
                    return

                await self.bot.wait_until_ready()

                if isinstance(event, wavelink.TrackEnd):
                    if event.node.identifier != self.node.identifier:
                        continue

                    self.bot.dispatch("wavelink_track_end", player=self, track=self.last_track, reason=event.reason)

                    if self.locked:
                        continue

                    if event.reason == "FINISHED":
                        self.set_command_log(controller=True)

                    elif event.reason == "STOPPED":
                        if len(self.queue) == 0:
                            continue

                        self.ignore_np_once = True

                    else:
                        continue

                    try:
                        self.message_updater_task.cancel()
                    except Exception:
                        pass

                    await self.track_end()

                    self.update = False

                    await self.process_next()

                    continue

                if isinstance(event, wavelink.TrackStart):
                    if event.node.identifier != self.node.identifier:
                        continue

                    self.bot.dispatch("wavelink_track_start", player=self)

                    if self.text_channel:
                        if isinstance(self.text_channel, disnake.Thread):
                            send_message_perm = self.text_channel.parent.permissions_for(
                                self.guild.me
                            ).send_messages_in_threads
                        else:
                            send_message_perm = self.text_channel.permissions_for(self.guild.me).send_messages

                        if not send_message_perm:
                            self.text_channel = None

                    if not self.guild.me.voice:
                        try:
                            await self.bot.wait_for(
                                "voice_state_update", check=lambda m, b, a: m == self.guild.me and m.voice, timeout=7
                            )
                        except asyncio.TimeoutError:
                            self.update = True
                            continue

                    try:
                        await self.process_save_queue()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        traceback.print_exc()

                    await asyncio.sleep(2)
                    await self.update_stage_topic()
                    continue

                if isinstance(event, wavelink.TrackException):
                    track = self.current or self.last_track
                    node_info = (
                        f"`{event.node.identifier}`"
                        if event.node.identifier == self.node.identifier
                        else f"`{self.node.identifier} | {event.node.identifier}`"
                    )
                    error_code = log_lavalink_failure(
                        "Falha ao reproduzir a música",
                        message=event.message,
                        cause=event.cause,
                        severity=event.severity,
                        node=event.node.identifier,
                    )
                    embed = disnake.Embed(
                        description=f"**Falha ao reproduzir música{' (parcial)' if isinstance(track, PartialTrack) else ''}:\n[{track.title}]({track.uri or track.search_uri})**\n"
                        f"**Motivo:** {lavalink_text(event.message)}\n"
                        f"**Nível:** `{event.severity}`\n"
                        f"**Servidor de música:** {node_info}{code_suffix(error_code)}",
                        color=disnake.Colour.red(),
                    )

                    error_format = pprint.pformat(event.data)

                    async def send_report():
                        print(
                            ("-" * 50) + f"\nErro ao reproduzir a música: {track.uri or track.search_uri}\n"
                            f"Servidor: {self.node.identifier}\n"
                            f"{error_format}\n" + ("-" * 50)
                        )

                        await self.report_error(embed, track)

                    if event.node.identifier != self.node.identifier:
                        await send_report()
                        continue

                    if self.locked:
                        self.set_command_log(
                            text=f"A reprodução da música falhou (tentando tocar novamente): [`{fix_characters(track.title, 15)}`](<{track.uri or track.search_uri}>). **Motivo:** `{plain_snippet(event.message, 50)}`{code_suffix(error_code)}",
                            controller=True,
                        )
                        self.update = True
                        await send_report()
                        continue

                    self.locked = True

                    self.current = None

                    self.current_encoded = None

                    cooldown = 10

                    start_position = 0

                    if ignore_error_log := event.cause.startswith(
                        (
                            "java.lang.IllegalStateException: Failed to get media URL: 2000: An error occurred while decoding track token",
                            "java.net.SocketTimeoutException: Connect timed out",
                            "java.net.SocketTimeoutException: Read timed out",
                            "java.net.SocketException: Network is unreachable",
                            "java.net.ConnectException: Connection refused",
                            "java.lang.IllegalArgumentException: Invalid bitrate",
                            "java.io.EOFException",
                            "java.net.UnknownHostException:",
                            "java.lang.IllegalStateException: Connection pool shut down",
                            "java.lang.IllegalStateException: Error from decoder",
                            "java.lang.IllegalStateException: Current position is beyond this element",
                            "com.sedmelluq.discord.lavaplayer.tools.io.PersistentHttpStream$PersistentHttpException: Not success status code: 403",
                        )
                    ):
                        if not hasattr(self, "retries_general_errors"):
                            self.retries_general_errors = {
                                "counter": 6,
                                "last_node": self.node.identifier,
                                "last_time": disnake.utils.utcnow(),
                            }

                        self.queue.appendleft(track)

                        if (
                            self.retries_general_errors["counter"] < 1
                            and self.node.identifier == self.retries_general_errors["last_node"]
                            and (disnake.utils.utcnow() - self.retries_general_errors["last_time"]).total_seconds()
                            < 180
                        ):
                            try:
                                self._new_node_task.cancel()
                            except Exception:
                                pass
                            self._new_node_task = self.bot.loop.create_task(
                                self._wait_for_new_node(ignore_node=self.node)
                            )
                            continue

                        self.retries_general_errors["last_time"] = disnake.utils.utcnow()

                        if self.retries_general_errors["last_node"] == self.node.identifier:
                            self.retries_general_errors["counter"] -= 1
                        else:
                            self.retries_general_errors = {
                                "counter": 6,
                                "last_node": self.node.identifier,
                                "last_time": disnake.utils.utcnow(),
                            }

                        start_position = get_start_pos(self, track)

                        cooldown = 4

                    elif event.cause == "java.lang.InterruptedException":
                        self.queue.appendleft(track)
                        try:
                            self._new_node_task.cancel()
                        except Exception:
                            pass
                        self._new_node_task = self.bot.loop.create_task(self._wait_for_new_node())
                        await send_report()
                        continue

                    elif track.source_name == "youtube":
                        self.current = None
                        self.current_encoded = None
                        self.native_yt = False
                        self.queue.appendleft(track)

                        try:
                            new_node = [
                                n
                                for n in self.bot.music.nodes.values()
                                if n != self.node and n.is_available and "ytsearch" in n.search_providers
                            ][0]
                        except Exception:
                            new_node = None

                        if new_node:
                            self.native_yt = True
                            txt = f"Devido a restrições do youtube no servidor `{self.node.identifier}` o player foi movido para o servidor `{new_node.identifier}`."
                            if self.controller_mode:
                                self.set_command_log(txt, emoji="⚠️", controller=True)
                            elif self.text_channel:
                                try:
                                    await self.text_channel.send(
                                        embed=disnake.Embed(
                                            description=f"-# `⚠️ -` {txt}", color=self.bot.get_color(self.guild.me)
                                        ),
                                        delete_after=10,
                                    )
                                except Exception:
                                    traceback.print_exc()
                            await asyncio.sleep(5)
                            await self.change_node(new_node.identifier)
                            self.locked = False
                            await self.process_next(start_position=self.position)
                            await send_report()
                            continue

                        if not getattr(self, "yt_warn", None):
                            txt = (
                                f"Devido a restrições do youtube no servidor `{self.node.identifier}`. Durante a sessão atual "
                                "será feito uma tentativa de obter a mesma música em outras plataformas de música usando o nome "
                                "das músicas do youtube que estão na fila (talvez a música tocada seja diferente do esperado "
                                "ou até mesmo ignoradas caso não retorne resultados)."
                            )
                            try:
                                await self.text_channel.send(
                                    embed=disnake.Embed(description=txt, color=self.bot.get_color(self.guild.me)),
                                    delete_after=30,
                                )
                            except Exception:
                                self.set_command_log(text=txt, emoji="⚠️", controller=True)
                            self.yt_warn = True
                            await send_report()

                        self.locked = False
                        await self.process_next(start_position=self.position)
                        continue

                    elif not track.track_loops:
                        self.failed_tracks.append(track)

                    elif self.keep_connected and not track.autoplay and len(self.queue) > 15:
                        self.queue.append(track)

                    if event.cause.startswith(
                        (
                            "com.github.topi314.lavasrc.mirror.TrackNotFoundException: No tracks found in playlist or search result for track",
                            "com.github.topi314.lavasrc.mirror.TrackNotFoundException: Playlist is empty",
                            "com.github.topi314.lavasrc.mirror.TrackNotFoundException: No mirror found for track",
                        )
                    ):
                        embed = disnake.Embed(
                            description=f"`Ignorando a música` [`{track.title}`](<{track.url}>)`. Pois não houve resultados em outras plataformas de música.`",
                            color=self.bot.get_color(self.guild.me),
                        ).set_thumbnail(track.thumb)

                    if isinstance(self.text_channel, disnake.Thread):
                        send_message_perm = self.text_channel.parent.permissions_for(
                            self.guild.me
                        ).send_messages_in_threads
                    else:
                        send_message_perm = self.text_channel.permissions_for(self.guild.me).send_messages

                    await send_report()

                    if not ignore_error_log and embed and self.text_channel and send_message_perm:
                        await self.text_channel.send(embed=embed, delete_after=10)

                    await asyncio.sleep(cooldown)

                    self.locked = False
                    await self.process_next(start_position=start_position)
                    continue

                if isinstance(event, wavelink.TrackStuck):
                    try:
                        self.message_updater_task.cancel()
                    except Exception:
                        pass

                    await self.track_end()

                    self.update = False

                    try:
                        self.set_command_log(
                            text=f"A música [{fix_characters(self.current.single_title, 25)}](<{self.current.uri}>) travou.",
                            emoji="⚠️",
                            controller=True,
                        )
                    except Exception:
                        pass

                    await self.process_next()

                    continue

                print(f"Unknown Wavelink event: {repr(event)}")

            except Exception:
                traceback.print_exc()

    async def channel_cleanup(self):
        if not self.text_channel:
            return

        try:
            parent = self.text_channel.parent
        except AttributeError:
            pass
        else:
            if (
                isinstance(parent, disnake.ForumChannel)
                and self.text_channel.owner_id == self.bot.user.id
                and self.text_channel.message_count > 1
            ):
                try:
                    await self.text_channel.purge(
                        check=lambda m: m.channel.id != m.id and (not m.pinned or not m.is_system())
                    )
                except Exception:
                    pass
                self.channel_purged = True
                return

        def check_current_message(m: disnake.Message):
            try:
                return m.id != self.message.id
            except AttributeError:
                return True

        if isinstance(self.text_channel, disnake.Thread):
            check = (
                lambda m: m.id != self.last_message_id
                and not not m.pinned
                and check_current_message(m)
                and (not m.is_system() or m.type != disnake.MessageType.channel_name_change)
            )
        else:
            check = lambda m: m.id != self.last_message_id and not m.pinned and check_current_message(m)

        try:
            await self.text_channel.purge(check=check)
        except Exception:
            print(
                f"Falha ao limpar mensagens do canal {self.text_channel} [ID: {self.text_channel.id}]:\n"
                f"{traceback.format_exc()}"
            )
            pass

        self.channel_purged = True

    async def connect(self, channel_id: int, self_mute: bool = False, self_deaf: bool = False):
        await super().connect(channel_id, self_mute=self_mute, self_deaf=True)
        self._last_channel = self.bot.get_channel(channel_id)
        self._last_channel_id = channel_id

    @property
    def last_channel(self):
        try:
            return self.guild.me.voice.channel
        except AttributeError:
            return self._last_channel

    def setup_features(self):
        try:
            (
                self.bot.player_static_skins[self.skin_static] if self.static else self.bot.player_skins[self.skin]
            ).setup_features(self)
        except Exception:
            # linha temporária para resolver possíveis problemas com skins custom criadas por usuarios antes desse commit.
            self.auto_update = 0
            self.controller_mode = True

    def check_skins(self):
        if self.skin.startswith("> custom_skin: "):
            if self.skin[15:] not in self.custom_skin_data:
                self.skin = self.bot.pool.default_skin
        elif self.skin not in self.bot.pool.player_skins:
            self.skin = self.bot.pool.default_skin

        if self.skin_static.startswith("> custom_skin: "):
            if self.skin_static[15:] not in self.custom_skin_static_data:
                self.skin_static = self.bot.pool.default_static_skin
        elif self.skin_static not in self.bot.pool.player_static_skins:
            self.skin_static = self.bot.pool.default_static_skin

    def start_members_timeout(self, check: bool, force: bool = False, idle_timeout=None):
        try:
            self.members_timeout_task.cancel()
        except Exception:
            pass
        self.members_timeout_task = self.bot.loop.create_task(
            self.members_timeout(check=check, force=force, idle_timeout=idle_timeout)
        )

    async def members_timeout(self, check: bool, force: bool = False, idle_timeout=None):
        if check:
            try:
                self.auto_skip_track_task.cancel()
            except Exception:
                pass

            self.auto_skip_track_task = None

            if self.current and self.auto_pause:
                self.auto_pause = False

                try:
                    self.set_command_log(
                        emoji="🔋", text="O modo **[economia de recursos]** foi desativado.", controller=True
                    )
                    if self.current:
                        self.queue.insert(0, self.current)
                    await self.process_next(start_position=self.position)
                except Exception:
                    traceback.print_exc()
            else:
                self.auto_pause = False
            return

        if not force:
            try:
                vc = self.guild.me.voice.channel
            except AttributeError:
                vc = self.last_channel

            if vc and [m for m in vc.members if not m.bot and not (m.voice.deaf or m.voice.self_deaf)]:
                try:
                    self.auto_skip_track_task.cancel()
                except Exception:
                    pass
                return

            if self.auto_pause:
                return

            if not idle_timeout:
                idle_timeout = self.bot.config["WAIT_FOR_MEMBERS_TIMEOUT"]

            await asyncio.sleep(idle_timeout)

            try:
                vc = self.guild.me.voice.channel
            except AttributeError:
                vc = self.last_channel

            if vc and [m for m in vc.members if not m.bot and not (m.voice.deaf or m.voice.self_deaf)]:
                try:
                    self.auto_skip_track_task.cancel()
                except Exception:
                    pass
                return

        if self.keep_connected:
            if self.paused or self.auto_pause:
                return

            self.auto_pause = True
            track = self.current
            if self.is_playing:
                await self.stop()
            self.current = track
            try:
                self.auto_skip_track_task.cancel()
            except Exception:
                pass
            self.set_command_log(
                emoji="🪫",
                text="O player está no modo **[economia de recursos]** (esse modo será desativado automaticamente quando "
                f"um membro entrar no canal <#{self.channel_id}>).",
                controller=True,
            )
            self.update = True
            self.start_auto_skip()
            await self.update_stage_topic()

        else:
            if self.is_closing:
                return

            try:
                vc = self.guild.me.voice.channel
            except AttributeError:
                vc = self.last_channel

            if vc and [m for m in vc.members if not m.bot]:
                return

            msg = "O player foi desligado por falta de membros no canal" + (f" <#{vc.id}>" if vc else "") + "..."

            self.command_log = msg

            if not self.controller_mode:
                embed = disnake.Embed(description=f"**{msg}**", color=self.bot.get_color(self.guild.me))
                try:
                    await self.text_channel.send(embed=embed, allowed_mentions=self.allowed_mentions)
                except Exception:
                    pass

            await self.destroy()

    async def get_autoqueue_tracks(self):
        try:
            return self.queue_autoplay.popleft()
        except Exception:
            pass

        if self.locked:
            return

        tracks_search = []

        for t in reversed(self.failed_tracks + self.played):
            if len(tracks_search) > 4:
                break

            tracks_search.insert(0, t)

        if current_track := self.current or self.last_track:
            tracks_search.insert(0, current_track)

        track = None
        tracks = []
        tracks_ytsearch = []

        exception = None

        if tracks_search:
            self.locked = True

            for track_data in tracks_search:
                if (
                    track_data.info["sourceName"] == "spotify"
                    and "spotify" not in self.node.info["sourceManagers"]
                    and self.bot.spotify
                ):
                    result = None

                    for i in range(3):
                        try:
                            result = await self.bot.spotify.track_search(tracks_search[0].author, limit=100)
                            break
                        except Exception as e:
                            self.set_command_log(
                                emoji="⚠️",
                                text=f"Falha ao obter músicas recomendadas do spotify, tentativa {i + 1} de 3.",
                                controller=True,
                            )
                            self.update = True
                            traceback.print_exc()
                            exception = e
                            await asyncio.sleep(5)

                    if result:
                        tracks = []

                        for t in result["tracks"]:
                            try:
                                thumb = t["album"]["images"][0]["url"]
                            except (IndexError, KeyError):
                                thumb = ""

                            partial_track = PartialTrack(
                                uri=t["external_urls"]["spotify"],
                                author=t["artists"][0]["name"] or "Unknown Artist",
                                title=t["name"],
                                thumb=thumb,
                                duration=t["duration_ms"],
                                source_name="spotify",
                                identifier=t["id"],
                                requester=self.bot.user.id,
                                autoplay=True,
                            )

                            partial_track.info["extra"]["authors"] = [
                                fix_characters(i["name"])
                                for i in t["artists"]
                                if f"feat. {i['name'].lower()}" not in t["name"].lower()
                            ]

                            partial_track.info["extra"]["authors_md"] = ", ".join(
                                f"[`{a['name']}`]({a['external_urls']['spotify']})" for a in t["artists"]
                            )

                            try:
                                if t["album"]["name"] != t["name"]:
                                    partial_track.info["extra"]["album"] = {
                                        "name": t["album"]["name"],
                                        "url": t["album"]["external_urls"]["spotify"],
                                    }
                            except (AttributeError, KeyError):
                                pass

                            tracks.append(partial_track)

                elif (
                    track_data.info["sourceName"] == "deezer"
                    and (
                        self.bot.pool.config["FORCE_USE_DEEZER_CLIENT"]
                        or "deezer" not in self.node.info["sourceManagers"]
                    )
                    and (artist_id := track_data.info["extra"].get("artist_id"))
                ):
                    try:
                        try:
                            result = await self.bot.deezer.get_artist_radio_info(artist_id)
                        except Exception:
                            traceback.print_exc()
                            result = None

                        if result:
                            tracks = []

                            for n, t in enumerate(result):
                                partial_track = PartialTrack(
                                    uri=f"https://www.deezer.com/track/{t['id']}",
                                    author=t["artist"]["name"],
                                    title=t["title"],
                                    thumb=t["album"]["cover_big"],
                                    duration=t["duration"] * 1000,
                                    source_name="deezer",
                                    identifier=t["id"],
                                    requester=self.bot.user.id,
                                    autoplay=True,
                                )

                                partial_track.info["isrc"] = t.get("isrc")
                                artists = t.get("contributors") or [t["artist"]]

                                partial_track.info["extra"]["authors"] = [a["name"] for a in artists]
                                partial_track.info["extra"]["authors_md"] = ", ".join(
                                    f"[`{fix_characters(a['name'])}`](https://www.deezer.com/artist/{a['id']})"
                                    for a in artists
                                )
                                partial_track.info["extra"]["artist_id"] = t["artist"]["id"]

                                if t["title"] != t["album"]["title"]:
                                    partial_track.info["extra"]["album"] = {
                                        "name": t["album"]["title"],
                                        "url": t["album"]["tracklist"],
                                    }

                                tracks.append(partial_track)
                    except Exception:
                        traceback.print_exc()

                elif track_data.info["sourceName"] == "soundcloud":
                    try:
                        info = await self.bot.loop.run_in_executor(
                            None,
                            lambda: self.bot.pool.ytdl.extract_info(f"{track_data.uri}/recommended", download=False),
                        )
                    except AttributeError:
                        pass

                    else:
                        tracks = [
                            PartialTrack(
                                uri=i["url"],
                                title=i["title"],
                                requester=self.bot.user.id,
                                source_name="soundcloud",
                                identifier=i["id"],
                                autoplay=True,
                            )
                            for i in info.get("entries", [])
                        ]

                if not tracks:
                    if self.bot.last_fm and not self.lastfm_artists:
                        if track_data.ytid:
                            if (
                                track_data.author.endswith(" - topic")
                                and not track_data.author.endswith("Release - topic")
                                and not track_data.title.startswith(track_data.author[:-8])
                            ):
                                artist = track_data.author[:-8]
                            else:
                                try:
                                    artist = track_data.title.split(" - ", maxsplit=1)[0]
                                except ValueError:
                                    artist = track_data.author
                        else:
                            artist = track_data.author

                        try:
                            self.lastfm_artists = [
                                a["name"]
                                for a in await self.bot.last_fm.get_similar_artists(artist)
                                if a["name"].lower() not in track_data.author.lower()
                            ]
                            self.lastfm_artists.insert(0, track_data.author)
                        except LastFmException as e:
                            print(f"Last.FM recommendations error: {repr(e)}")
                        except Exception:
                            traceback.print_exc()

                    try:
                        author = self.lastfm_artists.pop(0)
                    except Exception:
                        author = track_data.author

                    if track_data.info["sourceName"] == "youtube" and self.native_yt:
                        queries = [f"https://www.youtube.com/watch?v={track_data.ytid}&list=RD{track_data.ytid}"]

                        if p_dict := providers_dict.get(track_data.info["sourceName"]):
                            providers = [p_dict] + [p for p in self.node.search_providers if p != p_dict]
                        else:
                            providers = self.node.search_providers

                        queries.extend([f"{sp}:{author.split(',')[0]}" for sp in providers])

                    # elif track_data.info["sourceName"] == "spotify" and "spotify" in self.node.info["sourceManagers"] and (spotify_tracks:=[t.identifier for t in tracks_search if t.info["sourceName"] == "spotify"]):
                    #    queries = ["sprec:seed_tracks=" + ",".join(set(spotify_tracks[:5]))]

                    elif (
                        track_data.info["sourceName"] == "deezer"
                        and "deezer" in self.node.info["sourceManagers"]
                        and (deezer_tracks := [t.identifier for t in tracks_search if t.info["sourceName"] == "deezer"])
                    ):
                        queries = [f"dzrec:{deezer_tracks[0]}"]

                    else:
                        if p_dict := providers_dict.get(track_data.info["sourceName"]):
                            providers = [p_dict] + [p for p in self.node.search_providers if p != p_dict]
                        else:
                            providers = self.node.search_providers

                        queries = [f"{sp}:{author.split(',')[0]}" for sp in providers]

                    for query in queries:
                        if query.startswith("jssearch"):
                            continue

                        try:
                            tracks = await self.node.get_tracks(
                                query,
                                track_cls=LavalinkTrack,
                                playlist_cls=LavalinkPlaylist,
                                autoplay=True,
                                requester=self.bot.user.id,
                            )
                        except Exception as e:
                            if [
                                err
                                for err in ("Could not find tracks from mix", "Could not read mix page")
                                if err in str(e)
                            ] and self.native_yt:
                                try:
                                    tracks_ytsearch = await self.node.get_tracks(
                                        f'{query}:"{track_data.author}"',
                                        track_cls=LavalinkTrack,
                                        playlist_cls=LavalinkPlaylist,
                                        autoplay=True,
                                        requester=self.bot.user.id,
                                    )
                                    break
                                except Exception as e:
                                    exception = e
                                    continue
                            else:
                                print(traceback.format_exc())
                                exception = e
                                await asyncio.sleep(1.5)
                                continue

                        try:
                            tracks = tracks.tracks
                        except Exception:
                            pass

                        if not tracks:
                            continue

                        break

                    if not any(i in track_data.title.lower() for i in exclude_tags_2):
                        final_tracks = []
                        for t in tracks:
                            if not any(
                                (i in t.title.lower()) for i in exclude_tags_2
                            ) and not track_data.uri.startswith(t.uri):
                                final_tracks.append(t)
                        tracks = final_tracks or tracks

                track = track_data

            if not tracks:
                try:
                    tracks_ytsearch = tracks_ytsearch.tracks
                except AttributeError:
                    pass
                tracks = tracks_ytsearch
                tracks.reverse()

            if not tracks:
                self.locked = False

                if exception:
                    if isinstance(exception, wavelink.TrackLoadError):
                        error_code = log_lavalink_failure(
                            "Falha ao obter dados do autoplay",
                            message=exception.message,
                            cause=exception.cause,
                            severity=exception.severity,
                            node=self.node.identifier,
                        )
                        error_msg = (
                            f"**Mensagem:** {lavalink_text(exception.message)}\n"
                            f"**Nível:** `{exception.severity}`\n"
                            f"**Servidor de música:** `{self.node.identifier}`{code_suffix(error_code)}"
                        )
                    else:
                        error_code = log_unexpected_error(logger, exception, "autoplay")
                        error_msg = f"**Ocorreu um erro inesperado.**{code_suffix(error_code)}"
                else:
                    error_msg = "Não houve resultados relacionados as músicas tocadas..."

                try:
                    embed = disnake.Embed(
                        description=f"**Falha ao obter dados do autoplay:**\n{error_msg}", color=disnake.Colour.red()
                    )
                    await self.text_channel.send(embed=embed, delete_after=10)
                except Exception:
                    traceback.print_exc()
                await asyncio.sleep(7)
                return

        try:
            tracks = tracks.tracks
        except AttributeError:
            pass

        try:
            tracks = [t for t in tracks if not [u for u in tracks_search if t.uri.startswith(u.uri)]]
        except Exception:
            pass

        if track:
            info = {"title": track.title, "uri": track.uri}

            tracks_final = []

            for t in tracks:
                if t.is_stream:
                    continue

                # if t.duration < 90000:
                #    continue

                if track.ytid and track.ytid == t.ytid:
                    continue

                if not isinstance(t, PartialTrack):
                    t.info["extra"].update({"autoplay": True, "requester": self.bot.user.id})
                    t.playlist = None

                t.info["extra"]["related"] = info
                tracks_final.append(t)

            tracks.clear()
            self.queue_autoplay.extend(tracks_final)

        self.locked = False

        try:
            return self.queue_autoplay.popleft()
        except Exception:
            try:
                return self.played.popleft()
            except Exception:
                return None

    def start_auto_skip(self):
        try:
            self.auto_skip_track_task.cancel()
        except Exception:
            pass
        self.auto_skip_track_task = self.bot.loop.create_task(self.auto_skip_track())

    async def process_next(
        self, start_position: Union[int, float] = 0, inter: disnake.MessageInteraction = None, force_np=False
    ):
        try:
            self.lyric_task.cancel()
        except Exception:
            pass

        if self.locked or self.is_closing:
            return

        self.has_lyrics = False

        self.lyric_embed = None

        if not self.node or not self.node.is_available:
            try:
                self._new_node_task.cancel()
            except Exception:
                pass
            self._new_node_task = self.bot.loop.create_task(self._wait_for_new_node())
            return

        try:
            self.track_load_task.cancel()
        except Exception:
            pass
        self.track_load_task = self.bot.loop.create_task(
            self._process_next(start_position=start_position, inter=inter, force_np=force_np)
        )

    async def _process_next(
        self, start_position: Union[int, float] = 0, inter: disnake.MessageInteraction = None, force_np=False
    ):
        try:
            await self.bot.wait_until_ready()

            if not self.is_connected:
                return

            if not self.guild.me.voice:
                if self.last_channel:
                    await self.connect(self.last_channel.id)
                else:
                    return

            if not self.channel_purged and self.static and self.text_channel:
                data = await self.bot.get_data(self.guild_id, db_name=DBModel.guilds)
                if data["player_controller"]["channel"] == str(self.text_channel.id):
                    await self.channel_cleanup()
                else:
                    self.channel_purged = True

            try:
                self.idle_task.cancel()
            except Exception:
                pass

            if not self.controller_mode and self.idle_task:
                await self.message.delete()

            self.idle_task = None

            try:
                track = self.queue.popleft()

            except Exception:
                try:
                    track = None

                    if self.autoplay or self.keep_connected:
                        try:
                            track = await self.get_autoqueue_tracks()
                        except Exception:
                            print(traceback.format_exc())
                            self.locked = False
                            await asyncio.sleep(60)
                            if not self.current and (self.autoplay or self.keep_connected):
                                await self.process_next()
                            return

                    if not track:
                        await self.stop()
                        now = disnake.utils.utcnow()
                        self.idle_start_timestamp = int(now.timestamp())
                        self.idle_endtime = now + datetime.timedelta(seconds=self.bot.config["IDLE_TIMEOUT"])
                        self.last_track = None
                        self.idle_task = self.bot.loop.create_task(self.idling_mode())
                        self.bot.dispatch("player_queue_end", player=self)
                        return

                except Exception:
                    print(traceback.format_exc())
                    track = None

            if not track:
                await self.process_next()
                return

            self.locked = True

            encoded_track = None

            if not self.auto_pause:
                if track.info["sourceName"] not in self.node.info["sourceManagers"] and not isinstance(
                    track, PartialTrack
                ):
                    track.id = ""

                if isinstance(track, PartialTrack) and track.info["sourceName"] != "youtube":
                    if not track.id:
                        try:
                            await self.resolve_track(track)
                        except Exception as e:
                            error_code = log_unexpected_error(logger, e, f"resolução da faixa parcial {track.uri}")
                            try:
                                await self.text_channel.send(
                                    embed=disnake.Embed(
                                        description=f"Houve um problema ao tentar processar a música [{track.title}]({track.uri})..."
                                        f"{error_code_text(error_code)}",
                                        color=self.bot.get_color(),
                                    )
                                )
                            except Exception:
                                print(traceback.format_exc())

                            self.locked = False
                            self.native_yt = True

                            await self.process_next()
                            return

                        if not track.id:
                            try:
                                await self.text_channel.send(
                                    embed=disnake.Embed(
                                        description=f"A música [{track.title}]({track.uri}) não está disponível...\n"
                                        f"Pulando para a próxima música...",
                                        color=self.bot.get_color(),
                                    ),
                                    delete_after=10,
                                )
                            except Exception:
                                print(traceback.format_exc())

                            await asyncio.sleep(10)

                            self.locked = False

                            await self.process_next()
                            return

                if not self.native_yt or not self.node.prefer_youtube_native_playback:
                    cache_key = f"{track.info['sourceName']}:id:{track.identifier or track.id or track.ytid}"

                    partial_data = self.bot.pool.partial_track_cache.get(cache_key)

                    if track.info["sourceName"] == "youtube" or (
                        partial_data and partial_data[0].info["sourceName"] == "youtube"
                    ):
                        if track.is_stream or track.duration > 480000:
                            if not self.native_yt:
                                self.played.append(track)
                                self.locked = False
                                self.native_yt = True
                                await self.process_next()
                                return

                            try:
                                encoded_track = partial_data[0].id
                            except Exception:
                                pass

                        else:
                            tracks = []

                            exceptions = ""

                            if not partial_data:
                                for provider in self.node.search_providers:
                                    if provider in ("ytsearch", "ytmsearch"):
                                        continue

                                    if track.author.endswith(" - topic"):
                                        query = f"{provider}:{track.title} - {track.author[:-8]}"
                                    else:
                                        query = f"{provider}:{track.title}"

                                    tracks = self.bot.pool.partial_track_cache.get(query)

                                    if not tracks:
                                        try:
                                            tracks = await self.node.get_tracks(
                                                query, track_cls=LavalinkTrack, playlist_cls=LavalinkPlaylist
                                            )
                                        except Exception:
                                            exceptions += f"{traceback.format_exc()}\n"
                                            await asyncio.sleep(1)
                                            continue

                                        try:
                                            tracks = tracks.tracks
                                        except AttributeError:
                                            pass

                                        self.bot.pool.partial_track_cache[query] = tracks

                                    if not any(i in track.title.lower() for i in exclude_tags):
                                        final_result = []
                                        for t in tracks:
                                            if not any((i in t.title.lower()) for i in exclude_tags):
                                                final_result.append(t)
                                        tracks = final_result or tracks

                                    min_duration = track.duration - 7000
                                    max_duration = track.duration + 7000

                                    final_result = []

                                    for t in tracks:
                                        if (
                                            t.is_stream
                                            or not min_duration < t.duration < max_duration
                                            or fuzz.token_set_ratio(t.title, track.title) < TITLE_MATCH_THRESHOLD
                                        ):
                                            continue
                                        final_result.append(t)

                                    if not final_result:
                                        tracks = []
                                        continue

                                    tracks = final_result
                                    break

                            else:
                                tracks = partial_data

                            if not tracks:
                                if not self.native_yt:
                                    if exceptions:
                                        print(exceptions)
                                    self.played.append(track)
                                    self.set_command_log(
                                        emoji="⚠️",
                                        text=f"A música [`{track.title[:15]}`](<{track.uri}>) será pulada devido a falta de resultado "
                                        "em outras plataformas de música.",
                                        controller=True,
                                    )
                                    await asyncio.sleep(3)
                                    self.locked = False
                                    self.native_yt = True
                                    await self.process_next()
                                    return

                            else:
                                alt_track = tracks[0]
                                encoded_track = alt_track.id
                                self.bot.pool.partial_track_cache[cache_key] = [alt_track]
                                self.set_command_log(
                                    emoji="▶️",
                                    text=f"Tocando música obtida via metadados: [`{fix_characters(alt_track.title, 20)}`](<{alt_track.uri}>) `| Por: {fix_characters(alt_track.author, 15)}`",
                                    controller=True,
                                )
                                self.native_yt = True

                if not encoded_track and not track.id:
                    await self.resolve_track(track)

                    if not track.id:
                        try:
                            await self.text_channel.send(
                                embed=disnake.Embed(
                                    description=f"A música [{track.title}]({track.uri}) não está disponível...\n"
                                    "Pulando para a próxima música...",
                                    color=self.bot.get_color(),
                                ),
                                delete_after=10,
                            )
                        except Exception:
                            print(traceback.format_exc())

                        await asyncio.sleep(10)

                        self.locked = False

                        await self.process_next()
                        return

            self.last_track = track

            self.is_previows_music = False

            self.locked = False

            if track.is_stream:
                start_position = 0

            self.current = track
            self.last_update = 0
            self.last_position = start_position
            self.position_timestamp = 0
            self.paused = False

            self.process_hint()

            self.start_time = disnake.utils.utcnow()
            self.start_timestamp = self.start_time.timestamp()

            if self.auto_pause:
                self.last_update = time() * 1000
                self.current = track
                self.current_encoded = None
                self.start_auto_skip()
                self.bot.loop.create_task(
                    self.node.on_event(TrackStart({"track": track, "player": self, "node": self.node}))
                )
                self.set_command_log(
                    emoji="🪫",
                    text="O player está no modo **[economia de recursos]** (esse modo será desativado automaticamente quando "
                    f"um membro entrar no canal <#{self.channel_id}>).",
                    controller=True,
                )
            else:
                await self.play(track, start=start_position, temp_id=encoded_track)

            # TODO: rever essa parte caso adicione função de ativar track loops em músicas da fila
            if self.loop != "current" or force_np or (not self.controller_mode and self.current.track_loops == 0):
                if start_position:
                    await asyncio.sleep(1)

                await self.invoke_np(
                    interaction=inter,
                    force=True if (self.static or not self.loop or not self.is_last_message()) else False,
                    rpc_update=True,
                )
        except Exception as e:
            error_code = log_unexpected_error(logger, e, "reprodução da música")

            embed = disnake.Embed(description="**Ocorreu um erro ao reproduzir a música:**")

            if self.current:
                embed.description += f" [`{self.current.title}`]({self.current.uri})"

            embed.description += error_code_text(error_code)

            if self.text_channel:
                try:
                    await self.text_channel.send(embed=embed, delete_after=15)
                except Exception:
                    print(traceback.format_exc())

            cog = self.bot.get_cog("ErrorHandler")
            if cog:
                embed.add_field(name="Servidor:", value=f"{self.guild.name} [{self.guild.id}]")
                try:
                    await cog.send_webhook(
                        embed=embed,
                        file=string_to_file(
                            "".join(traceback.format_exception(type(e), e, e.__traceback__)), "error_traceback_ytdl.txt"
                        ),
                    )
                except Exception:
                    print(traceback.format_exc())
            await asyncio.sleep(10)
            self.locked = False
            await self.process_next()

    async def play(self, track: Union[LavalinkTrack], *, replace: bool = True, start: int = 0, end: int = 0, **kwargs):
        if replace or not self.is_playing:
            self.last_update = 0
            self.last_position = 0
            self.position_timestamp = 0
            self.paused = False
        else:
            return

        self.current = track

        self.current_encoded = kwargs.pop("temp_id", None) or track.id

        if self.node.version == 3:
            payload = {
                "op": "play",
                "guildId": str(self.guild_id),
                "track": self.current_encoded,
                "noReplace": not replace,
                "startTime": start,
            }

            payload.update(kwargs)

            if end > 0:
                payload["endTime"] = str(end)

            await self.node._send(**payload, **kwargs)
        else:
            vol: int = kwargs.get("volume") or self.volume

            if vol != self.volume:
                self.volume = vol

            pause: bool

            if (p := kwargs.get("paused")) is not None:
                pause = p
            else:
                pause = self.paused

            payload = {
                "encodedTrack": self.current_encoded,
                "volume": vol,
                "position": int(start),
                "paused": pause,
                "filters": self.filters,
            }

            if end > 0:
                payload["endTime"] = str(end)

            if track.source_name == "youtube":
                try:
                    payload["userData"] = {"oauth-token": self.extra_info["guild-yt-oauth"][0]}
                except KeyError:
                    pass

            await self.node.update_player(self.guild_id, payload, replace)

    async def process_idle_message(self):
        controller_opts = [
            disnake.SelectOption(
                emoji="➕",
                value=PlayerControls.add_song,
                label="Adicionar música",
                description=f"Tocar nova música/playlist.",
            ),
        ]

        if (played := len(self.played)) or self.last_track:
            try:
                play_txt = self.played[-1].title
            except Exception:
                play_txt = self.last_track.title

            controller_opts.extend(
                [
                    disnake.SelectOption(
                        emoji="⏮️",
                        value=PlayerControls.back,
                        label="Voltar",
                        description=f"Ouvir novamente: {play_txt[:31]}",
                    ),
                    disnake.SelectOption(
                        label="Ativar a reprodução automática",
                        emoji="🔄",
                        value=PlayerControls.autoplay,
                        description=f"Tocar música relacionadas a: {play_txt[:19]}",
                    ),
                ]
            )

        if played > 1:
            controller_opts.append(
                disnake.SelectOption(
                    emoji="↪️",
                    value=PlayerControls.readd,
                    label="Tocar novamente",
                    description=f"Tocar todas as músicas novamente ({played})",
                )
            )

        controller_opts.append(
            disnake.SelectOption(
                emoji="🛑",
                value=PlayerControls.stop,
                label="Finalizar",
                description=f"Finalizar o player e me desconectar do canal.",
            ),
        )

        components = [
            disnake.ui.Select(
                placeholder="Executar uma ação:",
                options=controller_opts,
                custom_id="musicplayer_dropdown_idle",
                min_values=0,
                max_values=1,
                required=False,
            )
        ]

        guild_data = await self.bot.get_data(self.guild.id, db_name=DBModel.guilds)

        opts = [
            disnake.SelectOption(label=k, value=k, description=v["description"])
            for k, v in guild_data["player_controller"]["fav_links"].items()
        ]

        if opts:
            components.append(
                disnake.ui.Select(
                    placeholder="Tocar música/playlist do servidor.", options=opts, custom_id="player_guild_pin"
                )
            )

        embed = disnake.Embed(
            description="**Não há músicas na fila... Adicione uma música ou use uma das opções abaixo.**",
            color=self.bot.get_color(self.guild.me),
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.replace(size=512, static_format="png").url)

        if not self.keep_connected:
            embed.description += (
                "\n\n**Nota:** `O Player será desligado automaticamente` "
                f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(seconds=self.bot.config['IDLE_TIMEOUT'])).timestamp())}:R> "
                f"`caso nenhuma ação seja executada...`"
            )

        kwargs = {"embed": embed, "content": None, "components": components, "allowed_mentions": self.allowed_mentions}

        try:
            if isinstance(self.text_channel.parent, disnake.ForumChannel) and self.static:
                kwargs["content"] = "💤 Aguardando por novas músicas..."
        except Exception:
            pass

        try:
            if self.has_thread or self.static or self.text_channel.last_message_id == self.message.id:
                try:
                    await self.message.edit(**kwargs)
                except Exception:
                    print(traceback.format_exc())
                    if self.text_channel and not self.static:
                        self.message = await self.text_channel.send(**kwargs)
                send_message = False
            else:
                send_message = True
        except AttributeError:
            send_message = True

        if send_message:
            try:
                await self.message.delete()
            except Exception:
                pass
            self.message = await self.text_channel.send(**kwargs)

    async def idling_mode(self):
        try:
            vc = self.guild.me.voice.channel
        except AttributeError:
            vc = self.last_channel

        try:
            await self.process_rpc(vc)
        except Exception:
            print(traceback.format_exc())

        try:
            await self.process_idle_message()
        except Exception:
            print(traceback.format_exc())

        try:
            await self.update_stage_topic()
        except Exception:
            pass

        if self.keep_connected:
            return

        await asyncio.sleep(self.bot.config["IDLE_TIMEOUT"])

        msg = "💤 **⠂O player foi desligado por inatividade...**"

        try:
            if self.static or self.has_thread:
                self.command_log = msg
            else:
                if self.text_channel:
                    embed = disnake.Embed(description=msg, color=self.bot.get_color(self.guild.me))
                    self.bot.loop.create_task(
                        self.text_channel.send(embed=embed, delete_after=120, allowed_mentions=self.allowed_mentions)
                    )
        except Exception:
            print(traceback.format_exc())

        await self.destroy()

    def set_command_log(self, text="", emoji="", controller=False):
        if controller or not text:
            self.command_log = text
            self.command_log_emoji = emoji
        else:
            self.command_log_list.append(
                {"text": text, "emoji": emoji, "timestamp": disnake.utils.utcnow().timestamp()}
            )

    async def update_stage_topic(self, reconnect=True, clear=False):
        if not self.guild.me.voice:
            if reconnect:
                await self.connect(self.last_channel.id)
            return

        if not self.stage_title_event:
            return

        if clear:
            if isinstance(self.guild.me.voice.channel, disnake.VoiceChannel) and self.last_stage_title:
                await self.bot.edit_voice_channel_status(status=None, channel_id=self.guild.me.voice.channel.id)
            return

        msg = None

        if self.current:
            requester = self.guild.get_member(self.current.requester)

            if requester:
                requester_name = str(requester.display_name)
            else:
                requester_name = "Membro desconhecido"

            if not self.current.is_stream and (not self.auto_pause or not self.paused):
                if isinstance(self.guild.me.voice.channel, disnake.StageChannel):
                    timestamp = str(self.current.duration)
                else:
                    timestamp = f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=self.current.duration - self.position)).timestamp())}:R>"
            else:
                timestamp = (
                    ("pausado" if (self.paused) else "🔴") + (f" <t:{int(disnake.utils.utcnow().timestamp())}:R>")
                    if not self.current.is_stream
                    else ""
                )

            msg = (
                self.stage_title_template.replace("{track.title}", self.current.single_title)
                .replace("{track.author}", self.current.authors_string)
                .replace(
                    "{track.duration}",
                    time_format(self.current.duration) if not self.current.is_stream else "Livestream",
                )
                .replace("{track.source}", self.current.info.get("sourceName", "desconhecido"))
                .replace("{track.playlist}", self.current.playlist_name or "Sem playlist")
                .replace("{requester.name}", requester_name)
                .replace("{requester.id}", str(self.current.requester))
                .replace("{track.timestamp}", timestamp)
            )

        if isinstance(self.guild.me.voice.channel, disnake.StageChannel):
            if not self.guild.me.guild_permissions.manage_guild:
                return

            if msg is not None:
                msg = msg.replace("{track.emoji}", "♪")

                if len(msg) > 110:
                    msg = msg[:107] + "..."

            if not msg:
                msg = "Status: Aguardando por novas músicas."
            else:
                emojis = emoji_pattern.findall(msg)
                for emoji in emojis:
                    msg = msg.replace(emoji, "")

            if not self.guild.me.voice.channel.instance:
                func = self.guild.me.voice.channel.create_instance
            elif msg == self.last_stage_title:
                return
            else:
                func = self.guild.me.voice.channel.instance.edit

            await func(topic=msg)

        else:  # voicechannel
            if msg is not None:
                msg = msg.replace("{track.emoji}", music_source_emoji(self.current.info["sourceName"]))

                if len(msg) > 496:
                    msg = msg[:496] + "..."

            if msg == self.last_stage_title:
                return

            try:
                await self.bot.edit_voice_channel_status(status=msg, channel_id=self.guild.me.voice.channel.id)
            except Exception as e:
                if isinstance(e, disnake.Forbidden):
                    self.stage_title_event = False
                    self.set_command_log(
                        emoji="❌",
                        text="O status automático foi desativado devido a falta de permissão pra alterar status.",
                        controller=True,
                    )
                    self.update = True
                print(traceback.format_exc())

        self.last_stage_title = msg

    async def set_pause(self, pause: bool) -> None:
        await super().set_pause(pause)
        self.start_timestamp = (disnake.utils.utcnow() - datetime.timedelta(milliseconds=self.position)).timestamp()
        self.bot.dispatch("player_pause" if pause else "player_resume", player=self)

    def get_skin(self, disable=False):
        if not self.current:
            return

        if self.static:
            if self.skin_static.startswith("> custom_skin: "):
                data = skin_converter(
                    self.custom_skin_static_data[self.skin_static[15:]], player=self, guild=self.guild
                )
            else:
                data = self.bot.pool.player_static_skins[self.skin_static].load(self)

        else:
            if self.skin.startswith("> custom_skin: "):
                data = skin_converter(self.custom_skin_data[self.skin[15:]], player=self, guild=self.guild)
            else:
                data = self.bot.pool.player_skins[self.skin].load(self)

        if disable:
            data = self.get_skin()

            components = []

            for c in data.get("components", []):
                c.disabled = True
                components.append(c)

            data["components"] = components

        return data

    async def auto_skip_track(self):
        if not self.controller_mode or not self.current:
            return

        try:
            try:
                if self.current.is_stream:
                    return
            except AttributeError:
                pass

            retries = 5

            sleep_time = None

            while retries > 0:
                try:
                    sleep_time = (self.current.duration - self.position) / 1000
                    break
                except AttributeError:
                    await asyncio.sleep(5)
                    retries -= 1
                    continue

            if not sleep_time:
                if self.current.duration:
                    sleep_time = self.current.duration / 1000
                else:
                    sleep_time = 180

            await asyncio.sleep(sleep_time)
            self.current = None
            self.current_encoded = None
            self.last_update = 0
            self.bot.loop.create_task(
                self.node.on_event(
                    TrackEnd({"track": self.current, "player": self, "node": self.node, "reason": "FINISHED"})
                )
            )
            return

        except asyncio.CancelledError:
            return

        except Exception:
            traceback.print_exc()
            return

    async def resolve_track(self, track: PartialTrack, force=False):
        if track.id:
            return

        check_duration = bool(track.duration)

        try:
            exceptions = []
            selected_track = None
            tracks = []

            if track.info["sourceName"] == "http":
                search_queries = [track.uri or track.search_uri]
            elif (
                track.info["sourceName"] == "youtube"
                and not force
                and (not self.native_yt or not self.node.prefer_youtube_native_playback)
            ):
                return
            else:
                search_queries = []

            if not search_queries:
                if (
                    not force
                    and track.info["sourceName"] in self.node.info.get("sourceManagers", [])
                    and (not self.node.only_use_native_search_providers or track.info["sourceName"] in native_sources)
                ):
                    search_queries = [track.uri]
                else:
                    search_queries = []
                    for sp in self.node.partial_providers:
                        if (
                            track.info["sourceName"] == "youtube"
                            and sp.startswith(("ytsearch:", "ytmsearch:"))
                            and not self.native_yt
                        ):
                            continue

                        if "{isrc}" in sp:
                            if isrc := track.info.get("isrc"):
                                search_queries.append(sp.replace("{isrc}", isrc))
                            continue
                        search_queries.append(
                            sp.replace("{title}", track.single_title).replace("{author}", ", ".join(track.authors))
                        )

            for query in search_queries:
                if not (
                    result := self.bot.pool.partial_track_cache.get(
                        f"{track.info['sourceName']}:{track.author}-{track.single_title}"
                    )
                ):
                    try:
                        result = await self.node.get_tracks(
                            query,
                            track_cls=LavalinkTrack,
                            playlist_cls=LavalinkPlaylist,
                            check_title=60 if query.startswith(("ytmsearch", "ytsearch", "scsearch")) else 75,
                        )
                    except Exception as e:
                        if track.info["sourceName"] == "youtube" and any(
                            e in str(e)
                            for e in (
                                "This video is not available",
                                "YouTube WebM streams are currently not supported.",
                                "Video returned by YouTube isn't what was requested",
                                "The video returned is not what was requested.",
                            )
                        ):
                            cog = self.bot.get_cog("Music")
                            cog.remove_provider(self.node.search_providers, ["ytsearch", "ytmsearch"])
                            cog.remove_provider(
                                self.node.partial_providers,
                                [
                                    'ytsearch:"{isrc}"',
                                    'ytsearch:"{title} - {author}"',
                                    'ytmsearch:"{isrc}"',
                                    'ytmsearch:"{title} - {author}"',
                                ],
                            )
                            self.native_yt = False
                            await self.resolve_track(track)
                            return
                        exceptions.append(e)
                        continue

                    try:
                        result = result.tracks
                    except AttributeError:
                        pass

                    self.bot.pool.partial_track_cache[
                        f"{track.info['sourceName']}:{track.author}-{track.single_title}"
                    ] = tracks

                try:
                    if result[0].info["sourceName"] == "bandcamp":
                        check_duration = False
                except Exception:
                    pass

                has_exclude_tags = any(tag for tag in exclude_tags if tag.lower() in track.title.lower())

                tracks.extend(result)

                for t in result:
                    if t.is_stream:
                        continue

                    if not has_exclude_tags and any(tag for tag in exclude_tags if tag.lower() in t.title.lower()):
                        continue

                    if check_duration and not ((t.duration - 10000) < track.duration < (t.duration + 10000)):
                        continue

                    selected_track = t
                    break

                if selected_track:
                    break

            if not selected_track:
                try:
                    selected_track = tracks[0]
                except Exception:
                    if exceptions:
                        print("Falha ao resolver PartialTrack:\n" + "\n".join(repr(e) for e in exceptions))
                    return

            track.id = selected_track.id
            track.info["id"] = selected_track.id
            track.info["length"] = selected_track.duration
            if track.info["sourceName"] == "last.fm":
                track.info["pluginInfo"] = selected_track.info.get("pluginInfo", {})
                track.info["author"] = selected_track.author
                track.info["title"] = selected_track.title
                track.info["sourceName"] = selected_track.info["sourceName"]
                track.info["uri"] = selected_track.info["uri"]
            else:
                track.info["sourceNameOrig"] = selected_track.info["sourceName"]
                if not track.info["author"]:
                    track.info["author"] = selected_track.author
            if not track.duration:
                track.info["duration"] = selected_track.duration
            if not track.thumb:
                track.info["artworkUrl"] = selected_track.thumb

        except Exception as e:
            error_code = log_unexpected_error(
                logger, e, f"obtenção de informação da PartialTrack {track.uri or track.search_uri}"
            )
            embed = disnake.Embed(
                description=f"**Falha ao obter informação de PartialTrack:\n[{track.title}]({track.uri or track.search_uri})**"
                f"{error_code_text(error_code)}\n"
                f"**Servidor de música:** `{self.node.identifier}`",
                color=disnake.Colour.red(),
            )
            await self.report_error(embed, track)

    async def _wait_for_new_node(self, txt: str = None, ignore_node: wavelink.Node = None):
        if self.node.is_available:
            return

        self.locked = True

        try:
            self.auto_skip_track_task.cancel()
        except Exception:
            pass

        try:
            original_identifier = str(self.node.identifier)

            self.set_command_log(
                txt
                or "Não há servidores de música disponível. Irei fazer algumas tentativas de conectar em um novo servidor de música.",
                emoji="⏰",
                controller=True,
            )
            self.update = True

            while True:
                node = self.bot.music.get_best_node(ignore_node=ignore_node)

                if not node:
                    await asyncio.sleep(5)
                    continue

                self.native_yt = True

                try:
                    self.node.players[self.guild_id]
                except KeyError:
                    return

                try:
                    if node == self.node and self.guild.me.voice and self._voice_state:
                        await self._dispatch_voice_update()
                    else:
                        await self.change_node(node.identifier)
                except Exception:
                    await asyncio.sleep(5)
                    continue

                if not self.guild.me.voice:
                    try:
                        can_connect(self.last_channel, self.guild, bot=self.bot)
                    except (GenericError, PoolException) as e:
                        self.set_command_log(f"O player foi finalizado devido ao erro: {e}", controller=True)
                        await self.destroy()
                        return
                    except Exception as e:
                        error_code = log_unexpected_error(logger, e, "conexão do player ao novo servidor de música")
                        self.set_command_log(
                            f"O player foi finalizado devido a um erro inesperado{code_suffix(error_code)}.",
                            controller=True,
                        )
                        await self.destroy()
                        return
                    await self.connect(self.last_channel.id)

                self.locked = False

                if self.current:
                    self.queue.appendleft(self.current)
                    start_position = self.position
                    self.current = None
                    self.current_encoded = None
                else:
                    start_position = 0

                await self.process_next(start_position=start_position)

                try:
                    if not self.auto_pause:
                        if original_identifier != node.identifier:
                            txt = f"O player foi movido para o servidor de música **{node.identifier}**."
                        else:
                            txt = f"O player foi reconectado no servidor de músca **{self.node.identifier}**"
                        self.set_command_log(emoji="📶", text=txt, controller=True)
                        self.update = True
                except Exception:
                    print(traceback.format_exc())
                self._new_node_task = None
                return
        except Exception:
            traceback.print_exc()

    async def track_end(self, ignore_track_loop=False):
        self.votes.clear()

        self.locked = True

        await asyncio.sleep(0.5)

        if self.last_track:
            if not self.last_track.is_stream and self.last_track.duration < 60000:
                await asyncio.sleep(7)

            if self.loop == "current":
                self.queue.appendleft(self.last_track)
            elif self.is_previows_music:
                self.queue.insert(1, self.last_track)
                self.is_previows_music = False
            elif self.last_track.track_loops and not ignore_track_loop:
                self.last_track.info["extra"]["track_loops"] -= 1
                self.queue.insert(0, self.last_track)
            elif self.loop == "queue":  # or self.keep_connected:
                if self.is_previows_music:
                    self.queue.insert(1, self.last_track)
                    self.is_previows_music = False
                else:
                    self.queue.append(self.last_track)
            elif not self.last_track.autoplay:
                self.played.append(self.last_track)

        elif self.is_previows_music:
            self.is_previows_music = False

        self.locked = False

    async def destroy(self, *, force: bool = False, inter: disnake.MessageInteraction = None):
        self.bot.loop.create_task(self.process_destroy(force=force, inter=inter))

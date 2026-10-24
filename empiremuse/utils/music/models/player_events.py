# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import pprint
import traceback
from typing import TYPE_CHECKING

import disnake

import empiremuse.wavelink as wavelink
from empiremuse.rules.text import plain_snippet
from empiremuse.utils.music.converters import fix_characters
from empiremuse.utils.music.errors import (
    code_suffix,
)

if TYPE_CHECKING:
    pass

from empiremuse.utils.music.models.tracks import (
    PartialTrack,
)
from empiremuse.utils.music.models.helpers import (
    get_start_pos,
    lavalink_text,
    log_lavalink_failure,
)


class PlayerEventsMixin:
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

# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import traceback
from typing import Union, List

import disnake

from empiremuse.utils.db import DBModel
from empiremuse.utils.others import send_idle_embed

from empiremuse.utils.music.models.tracks import (
    LavalinkTrack,
    PartialTrack,
)


class PlayerStateMixin:
    async def cleanup(self, inter: disnake.MessageInteraction = None):
        self.played.clear()

        try:
            self.reconnect_voice_channel_task.cancel()
        except Exception:
            pass

        try:
            self.members_timeout_task.cancel()
        except Exception:
            pass

        try:
            self.auto_skip_track_task.cancel()
        except Exception:
            pass

        try:
            self._queue_updater_task.cancel()
        except Exception:
            pass

        try:
            self.message_updater_task.cancel()
        except Exception:
            pass
        self.message_updater_task = None

        try:
            self._new_node_task.cancel()
        except Exception:
            pass
        self._new_node_task = None

        try:
            self.idle_task.cancel()
        except Exception:
            pass
        self.idle_task = None

        if self.guild.me:
            self.bot.loop.create_task(self.update_stage_topic(reconnect=False, clear=True))

            try:
                vc = self.guild.voice_client.channel
            except Exception:
                vc = self.last_channel

            try:
                await self.process_rpc(vc, close=True)
            except Exception:
                traceback.print_exc()

            if self.static:
                try:
                    await send_idle_embed(inter or self.message, self.command_log, bot=self.bot)
                except Exception:
                    traceback.print_exc()
                    pass

                await self.channel_cleanup()

            else:
                try:
                    if self.has_thread or self.static:
                        try:
                            if inter.message.id == self.message.id:
                                func = inter.response.edit_message
                            else:
                                func = self.message.edit
                        except AttributeError:
                            try:
                                func = self.message.edit
                            except AttributeError:
                                func = None

                        if func:
                            try:
                                await func(
                                    allowed_mentions=self.allowed_mentions,
                                    **self.get_skin(disable=True)
                                    if (
                                        not self.static
                                        and (
                                            disnake.utils.utcnow()
                                            - datetime.datetime.fromtimestamp(self.uptime, datetime.timezone.utc)
                                        ).total_seconds()
                                        > 15
                                    )
                                    else {
                                        "embed": disnake.Embed(
                                            description=self.command_log, color=self.bot.get_color(self.guild.me)
                                        )
                                    },
                                )
                                channel: disnake.Thread = self.bot.get_channel(self.message.id)

                                if channel.parent.permissions_for(self.guild.me).send_messages_in_threads:
                                    try:
                                        await channel.send(
                                            embed=disnake.Embed(
                                                color=self.bot.get_color(self.guild.me),
                                                description="**A sessão de pedido de música da conversa atual foi encerrada.**",
                                            )
                                        )
                                    except Exception:
                                        pass

                                if (
                                    channel.owner.id == self.bot.user.id
                                    or channel.parent.permissions_for(self.guild.me).manage_threads
                                ):
                                    kwargs = {"archived": True, "locked": True}
                                else:
                                    kwargs = {}

                                await channel.edit(**kwargs)
                            except Exception:
                                print(
                                    f"Falha ao arquivar thread do servidor: {self.guild.name}\n{traceback.format_exc()}"
                                )

                    elif inter:
                        kw = {}

                        if self.lyric_embed and self.message and self.message.components:
                            self.lyric_embed.description += f"\n🛑 ⠂{self.command_log}"

                            components = []

                            for component in self.message.components:
                                for item in component.children:
                                    if isinstance(item, disnake.Button):
                                        item = disnake.ui.Button().from_component(item)
                                    elif isinstance(item, disnake.SelectMenu):
                                        item = disnake.ui.Select().from_component(item)
                                    item.disabled = True
                                    components.append(item)

                            kw = {"embed": self.lyric_embed, "components": components}

                        if inter.message.id == self.message.id:
                            func = inter.response.edit_message
                            if (
                                not kw
                                and (
                                    disnake.utils.utcnow()
                                    - datetime.datetime.fromtimestamp(self.uptime, datetime.timezone.utc)
                                ).total_seconds()
                                > 15
                            ):
                                kw = self.get_skin(disable=True)
                                try:
                                    del kw["flags"]
                                except Exception:
                                    pass
                        else:
                            try:
                                func = self.message.edit
                            except Exception:
                                func = None

                        if func:
                            if not kw:
                                kw = {
                                    "embed": disnake.Embed(
                                        description=f"🛑 ⠂{self.command_log}", color=self.bot.get_color(self.guild.me)
                                    ),
                                    "view": None,
                                }

                            await func(**kw)

                    elif self.controller_mode is True:
                        if not self.current:
                            await self.destroy_message()
                            return

                        kw = {}

                        if self.lyric_embed and self.message and self.message.components:
                            self.lyric_embed.description += f"\n🛑 ⠂{self.command_log}"
                            kw = {"embed": self.lyric_embed, "components": []}

                            for c in disnake.ui.View(timeout=0).from_message(self.message).children:
                                c.disabled = True
                                kw["components"].append(c)

                        await self.message.edit(**kw or self.get_skin(disable=True))

                except Exception:
                    traceback.print_exc()

        self.queue.clear()

    async def process_destroy(self, force: bool = False, inter: disnake.MessageInteraction = None):
        if self.is_closing:
            return

        self.is_closing = True

        try:
            self.track_load_task.cancel()
        except Exception:
            pass

        try:
            self.event_queue_task.cancel()
        except Exception:
            pass

        try:
            self.lyric_task.cancel()
        except Exception:
            pass

        await self.cleanup(inter)

        try:
            channel = self.guild.voice_client.channel
        except AttributeError:
            channel = self.last_channel

        if (
            isinstance(channel, disnake.StageChannel)
            and self.stage_title_event
            and self.guild.me
            and self.guild.me.guild_permissions.manage_channels
        ):
            if channel.instance:
                try:
                    await channel.instance.delete()
                except Exception:
                    traceback.print_exc()

        await super().destroy(force=force, guild=self.guild)

        self.bot.dispatch("player_destroy", player=self)

    async def process_save_queue(self, create_task=True):
        if self._session_resuming:
            await asyncio.sleep(10)
            self._session_resuming = False
            return

        if self._queue_updater_task and self.bot.config["PLAYER_SESSIONS_MONGODB"] and self.bot.config["MONGO"]:
            return

        cog = self.bot.get_cog("PlayerSession")

        if not cog:
            return

        try:
            self._queue_updater_task.cancel()
        except Exception:
            pass

        await cog.save_info(self)

        if create_task:
            self._queue_updater_task = self.bot.loop.create_task(cog.queue_updater_task(self))

    async def _send_rpc_data(self, users: List[int], stats: dict):
        for u in users:
            stats["user"] = u

            data = await self.bot.get_global_data(id_=u, db_name=DBModel.users)

            if self.bot.config["ENABLE_RPC_AUTH"] and not data["token"]:
                continue

            stats.update({"token": data["token"], "lastfm_user": data["lastfm"]["username"]})

            try:
                await self.bot.ws_client.send(stats)
            except Exception:
                print(traceback.format_exc())

    async def process_rpc(
        self,
        voice_channel: Union[disnake.VoiceChannel, disnake.StageChannel] = None,
        close=False,
        users: List[int] = None,
        wait: bool = False,
    ):
        try:
            if not voice_channel and not close:
                try:
                    voice_channel = self.bot.get_channel(self.channel_id) or self.bot.get_channel(
                        self.guild.voice_client.channel.id
                    )
                except AttributeError:
                    voice_channel = self.last_channel

            if not users:
                try:
                    users = voice_channel.voice_states
                except AttributeError:
                    # TODO: Investigar possível bug ao mover o bot de canal pelo discord.
                    return

            thumb = self.bot.user.display_avatar.replace(size=512, static_format="png").url

            users = [u for u in users if u != self.bot.user.id]

            if close:
                stats = {
                    "op": "close",
                    "bot_id": self.bot.user.id,
                    "bot_name": str(self.bot.user),
                    "thumb": thumb,
                    "auth_enabled": self.bot.config["ENABLE_RPC_AUTH"],
                }

                if wait:
                    await self._send_rpc_data(users, stats)
                else:
                    try:
                        self._rpc_update_task.cancel()
                    except Exception:
                        pass
                    self._rpc_update_task = self.bot.loop.create_task(self._send_rpc_data(users, stats))
                return

            if self.is_closing:
                return

            stats = {
                "op": "update",
                "track": None,
                "bot_id": self.bot.user.id,
                "bot_name": str(self.bot.user),
                "thumb": thumb,
                "guild": self.guild.name,
                "auth_enabled": self.bot.config["ENABLE_RPC_AUTH"],
                "listen_along_invite": self.listen_along_invite,
            }

            if not self.current:
                try:
                    bot_public = self.bot.appinfo.bot_public
                except AttributeError:
                    bot_public = False

                stats.update(
                    {
                        "op": "idle",
                        "bot_id": self.bot.user.id,
                        "invite_permissions": self.bot.config["INVITE_PERMISSIONS"],
                        "bot_name": str(self.bot.user),
                        "public": bot_public,
                        "support_server": self.bot.config["SUPPORT_SERVER"],
                    }
                )

                try:
                    stats["idle_endtime"] = int(self.idle_endtime.timestamp())
                    stats["idle_starttime"] = self.idle_start_timestamp
                except Exception:
                    pass

            else:
                track: Union[LavalinkTrack, PartialTrack] = self.current

                stats["track"] = {
                    "source": track.info["sourceName"],
                    "thumb": track.thumb if len(track.thumb) < 257 else "",
                    "title": track.single_title,
                    "url": track.uri,
                    "author": track.authors_string,
                    "stream": track.is_stream,
                    "position": self.position,
                    "paused": self.is_paused,
                    "requester_id": track.requester,
                    "loop": self.current.track_loops or self.loop,
                    "queue": len(self.queue),
                    "247": self.keep_connected,
                    "autoplay": self.current.autoplay,
                }

                stats["start_time"] = self.start_timestamp

                if self.current.is_stream:
                    stats["track"]["duration"] = int(self.start_time.timestamp())
                else:
                    stats["track"]["duration"] = track.duration

                if track.playlist_name:
                    stats["track"].update(
                        {
                            "playlist_name": track.playlist_name,
                            "playlist_url": track.playlist_url,
                        }
                    )

                if track.album_name:
                    stats["track"].update(
                        {
                            "album_name": track.album_name,
                            "album_url": track.album_url,
                        }
                    )

            if wait:
                await self._send_rpc_data(users, stats)
            else:
                try:
                    self._rpc_update_task.cancel()
                except Exception:
                    pass

                self._rpc_update_task = self.bot.loop.create_task(self._send_rpc_data(users, stats))

        except Exception:
            traceback.print_exc()

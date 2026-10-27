# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import traceback
from typing import TYPE_CHECKING

import disnake

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.checks import can_connect
from empiremuse.utils.music.converters import time_format
from empiremuse.utils.music.errors import (
    GenericError,
    PoolException,
    code_suffix,
    log_unexpected_error,
)
from empiremuse.utils.others import music_source_emoji

if TYPE_CHECKING:
    pass

from empiremuse.utils.music.models.helpers import (
    emoji_pattern,
    logger,
)


class PlayerVoiceMixin:
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
            check = lambda m: (
                m.id != self.last_message_id
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

    def start_members_timeout(self, check: bool, force: bool = False, idle_timeout=None):
        try:
            self.members_timeout_task.cancel()
        except Exception:
            pass
        self.members_timeout_task = self.bot.loop.create_task(
            self.members_timeout(check=check, force=force, idle_timeout=idle_timeout)
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

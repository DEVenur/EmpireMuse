# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import traceback

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.models.event_steps import _he_dispatch


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

                await _he_dispatch(self, event)

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

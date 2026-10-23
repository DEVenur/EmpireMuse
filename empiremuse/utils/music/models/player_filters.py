# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime

import disnake

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.filters import AudioFilter


class PlayerFiltersMixin:
    #######################
    #### Filter Stuffs ####
    #######################

    async def seek(self, position: int = 0) -> None:
        self.last_position = position
        await super().seek(position=position)
        self.start_timestamp = (disnake.utils.utcnow() - datetime.timedelta(milliseconds=self.position)).timestamp()
        self.bot.dispatch("player_seek", player=self, position=position)

    async def set_distortion(
        self,
        sin_offset: float = 0,
        sin_scale: float = 1.0,
        cos_offset: float = 0,
        cos_scale: float = 1.0,
        tan_offset: float = 0,
        tan_scale: float = 1.0,
        offset: float = 0,
        scale: float = 1.0,
        enabled: bool = True,
    ):
        if enabled:
            return await self.set_filter(
                AudioFilter.distortion(
                    sin_offset, sin_scale, cos_offset, cos_scale, tan_offset, tan_scale, offset, scale
                )
            )

        try:
            del self.filters["distortion"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_timescale(self, speed: float = 1.0, pitch: float = 1.0, rate: float = 1.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.timescale(speed=speed, pitch=pitch, rate=rate))

        try:
            del self.filters["timescale"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_karaoke(
        self,
        level: float = 1.0,
        mono_level: float = 1.0,
        filter_band: float = 220.0,
        filter_width: float = 100.0,
        enabled: bool = True,
    ):
        if enabled:
            return await self.set_filter(
                AudioFilter.karaoke(
                    level=level, mono_level=mono_level, filter_band=filter_band, filter_width=filter_width
                )
            )

        try:
            del self.filters["karaoke"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_tremolo(self, frequency: float = 2.0, depth: float = 0.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.tremolo(frequency=frequency, depth=depth))

        try:
            del self.filters["tremolo"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_vibrato(self, frequency: float = 2.0, depth: float = 0.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.vibrato(frequency=frequency, depth=depth))

        try:
            del self.filters["vibrato"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_rotation(self, sample_rate: int = 5, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.rotation(sample_rate=sample_rate))

        try:
            del self.filters["rotation"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_lowpass(self, smoothing: float = 20.0, enabled: bool = True):
        if enabled:
            return await self.set_filter(AudioFilter.low_pass(smoothing=smoothing))

        try:
            del self.filters["lowpass"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_channelmix(
        self,
        left_to_left: float = 1.0,
        left_to_right: float = 0,
        right_to_left: float = 0,
        right_to_right: float = 1.0,
        enabled: bool = True,
    ):
        if enabled:
            return await self.set_filter(
                AudioFilter.channel_mix(
                    left_to_left=left_to_left,
                    left_to_right=left_to_right,
                    right_to_left=right_to_left,
                    right_to_right=right_to_right,
                )
            )

        try:
            del self.filters["channelmix"]
        except KeyError:
            pass

        await self.update_filters()

    async def set_eq(self, equalizer: wavelink.Equalizer):
        await self.set_filter(AudioFilter.equalizer(bands=equalizer.eq))
        self._equalizer = equalizer

    async def update_filters(self):
        if self.node.version == 3:
            await self.node._send(op="filters", **self.filters, guildId=str(self.guild_id))
        else:
            await self.node.update_player(guild_id=self.guild_id, data={"filters": self.filters})

    async def set_filter(self, filter_type: AudioFilter):
        self.filters.update(filter_type.filter)
        await self.update_filters()

        return filter_type

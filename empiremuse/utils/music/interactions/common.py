# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import disnake

from empiremuse.utils.others import send_idle_embed

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

youtube_regex = re.compile(r"https?://www\.youtube\.com/(?:channel/|@)[^/]+")
soundcloud_regex = re.compile(r"^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)")


async def process_idle_embed(bot: BotCore, guild: disnake.Guild, guild_data: dict):
    try:
        bot.music.players[guild.id]
        return
    except KeyError:
        pass

    try:
        channel = bot.get_channel(int(guild_data["player_controller"]["channel"]))
    except Exception:
        return

    try:
        message = await channel.fetch_message(int(guild_data["player_controller"]["message_id"]))
    except Exception:
        message = None

    await send_idle_embed(message or channel, bot=bot, guild_data=guild_data)


class ViewMode:
    fav_manager = "0"
    guild_fav_manager = "1"
    integrations_manager = "2"


IMPORT_ECHO_LIMIT = 100

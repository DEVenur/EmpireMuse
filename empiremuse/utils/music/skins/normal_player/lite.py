# -*- coding: utf-8 -*-
from os.path import basename

import disnake

from empiremuse.utils.branding import asset_url
from empiremuse.utils.music.converters import fix_characters, time_format, md_bracketed, md_link
from empiremuse.utils.music.models import LavalinkPlayer


class LiteSkin:
    __slots__ = ("name", "preview")

    def __init__(self):
        self.name = basename(__file__)[:-3]
        self.preview = asset_url("skin_normal_lite_preview.png")

    def setup_features(self, player: LavalinkPlayer):
        player.mini_queue_feature = False
        player.controller_mode = False
        player.auto_update = 0
        player.hint_rate = 9
        player.static = False

    def load(self, player: LavalinkPlayer) -> dict:
        data = {"content": None, "embeds": []}

        embed = disnake.Embed(color=player.bot.get_color(player.guild.me))

        duration = "`🔴 Livestream`" if player.current.is_stream else time_format(player.current.duration)

        embed.description = (
            f"> -# ▶️ **┃**{md_link(player.current.title, player.current.uri or player.current.search_uri, limit=45)}\n"
            f"> -# ℹ️ **┃**`{duration}`┃`{fix_characters(player.current.author, 18)}`┃"
        )

        if not player.current.autoplay:
            embed.description += f"<@{player.current.requester}>"
        else:
            try:
                embed.description = f"{md_bracketed(md_link('Recomendada', player.current.info['extra']['related']['uri']))}"
            except Exception:
                embed.description = "`[Recomendada]`"

        if player.current.playlist_name:
            embed.description += (
                f"\n> -# 🎼 **┃ Playlist:** {md_link(player.current.playlist_name, player.current.playlist_url)}"
            )

        embed.set_thumbnail(player.current.thumb)

        data["embeds"].append(embed)

        if player.current_hint:
            data["embeds"].append(
                disnake.Embed(color=player.bot.get_color(player.guild.me)).set_footer(
                    text=f"💡 Dica: {player.current_hint}"
                )
            )

        return data


def load():
    return LiteSkin()

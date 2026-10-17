# -*- coding: utf-8 -*-
import datetime
import itertools
from os.path import basename

import disnake

from empiremuse.utils.branding import asset_url
from empiremuse.utils.music.converters import fix_characters, time_format, get_button_style, music_source_image
from empiremuse.utils.music.models import LavalinkPlayer
from empiremuse.utils.others import PlayerControls


class DefaultSkin:
    __slots__ = ("name", "preview")

    def __init__(self):
        self.name = basename(__file__)[:-3]
        self.preview = asset_url("skin_normal_default_preview.png")

    def setup_features(self, player: LavalinkPlayer):
        player.mini_queue_feature = True
        player.controller_mode = True
        player.auto_update = 0
        player.hint_rate = player.bot.config["HINT_RATE"]
        player.static = False

    def load(self, player: LavalinkPlayer) -> dict:
        data = {"content": None, "embeds": []}

        color = player.bot.get_color(player.guild.me)

        embed = disnake.Embed(color=color)
        embed_queue = None
        vc_txt = ""

        if not player.paused:
            embed.set_author(name="Tocando Agora:", icon_url=music_source_image(player.current.info["sourceName"]))

        else:
            embed.set_author(name="Em Pausa:", icon_url=asset_url("player_pause_icon.png"))

        if player.current_hint:
            embed.set_footer(text=f"💡 Dica: {player.current_hint}")
        else:
            embed.set_footer(text=str(player), icon_url=asset_url("player_loading_neon_circle.gif"))

        player.mini_queue_feature = True

        duration = (
            "> -# 🔴 **⠂** `Livestream`\n"
            if player.current.is_stream
            else (
                f"> -# ⏰ **⠂** `{time_format(player.current.duration)} [`"
                + f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=player.current.duration - player.position)).timestamp())}:R>`]`\n"
                if not player.paused
                else ""
            )
        )

        txt = (
            f"-# [`{player.current.single_title}`]({player.current.uri or player.current.search_uri})\n\n"
            f"{duration}"
            f"> -# 👤 **⠂** {player.current.authors_md}"
        )

        if not player.current.autoplay:
            txt += f"\n> -# ✋ **⠂** <@{player.current.requester}>"
        else:
            try:
                mode = f" [`Recomendada`]({player.current.info['extra']['related']['uri']})"
            except:
                mode = "`Recomendada`"
            txt += f"\n> -# 👍 **⠂** {mode}"

        if player.current.track_loops:
            txt += f"\n> -# 🔂 **⠂** `Repetições restantes: {player.current.track_loops}`"

        if player.loop:
            if player.loop == "current":
                e = "🔂"
                m = "Música atual"
            else:
                e = "🔁"
                m = "Fila"
            txt += f"\n> -# {e} **⠂** `Repetição: {m}`"

        if player.current.album_name:
            txt += (
                f"\n> -# 💽 **⠂** [`{fix_characters(player.current.album_name, limit=36)}`]({player.current.album_url})"
            )

        if player.current.playlist_name:
            txt += f"\n> -# 📑 **⠂** [`{fix_characters(player.current.playlist_name, limit=36)}`]({player.current.playlist_url})"

        if (qlenght := len(player.queue)) and not player.mini_queue_enabled:
            txt += f"\n> -# 🎶 **⠂** `{qlenght} música{'s'[: qlenght ^ 1]} na fila`"

        if player.keep_connected:
            txt += "\n> -# ♾️ **⠂** `Modo 24/7 ativado`"

        txt += f"{vc_txt}\n"

        bar = asset_url("ui_rainbow_bar_3.gif")

        if player.command_log:
            txt += f"```ansi\n [34;1mÚltima Interação:[0m```**┕ {player.command_log_emoji} ⠂**{player.command_log}\n"

        if player.mini_queue_enabled:
            if len(player.queue):
                queue_txt = "\n".join(
                    f"-# `{(n + 1):02}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, 21)}`]({t.uri})"
                    for n, t in (enumerate(itertools.islice(player.queue, 3)))
                )

                embed_queue = disnake.Embed(
                    title=f"Músicas na fila: {qlenght}", color=color, description=f"\n{queue_txt}"
                )

                if not player.loop and not player.keep_connected and not player.paused:
                    queue_duration = 0

                    for t in player.queue:
                        if not t.is_stream:
                            queue_duration += t.duration

                    embed_queue.description += f"\n-# `[⌛ As músicas acabam` <t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=(queue_duration + (player.current.duration if not player.current.is_stream else 0)) - player.position)).timestamp())}:R> `⌛]`"

                embed_queue.set_image(url=bar)

            elif len(player.queue_autoplay):
                queue_txt = "\n".join(
                    f"-# `👍⠂{(n + 1):02}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, 20)}`]({t.uri})"
                    for n, t in (enumerate(itertools.islice(player.queue_autoplay, 3)))
                )
                embed_queue = disnake.Embed(
                    title="Próximas músicas recomendadas:", color=color, description=f"\n{queue_txt}"
                )
                embed_queue.set_image(url=bar)

        embed.description = txt
        embed.set_image(url=bar)
        embed.set_thumbnail(url=player.current.thumb)

        data["embeds"] = [embed_queue, embed] if embed_queue else [embed]

        data["components"] = [
            disnake.ui.Button(emoji="⏯️", custom_id=PlayerControls.pause_resume, style=get_button_style(player.paused)),
            disnake.ui.Button(emoji="⏮️", custom_id=PlayerControls.back),
            disnake.ui.Button(emoji="⏹️", custom_id=PlayerControls.stop),
            disnake.ui.Button(emoji="⏭️", custom_id=PlayerControls.skip),
            disnake.ui.Button(
                emoji="📑", custom_id=PlayerControls.queue, disabled=not (player.queue or player.queue_autoplay)
            ),
            disnake.ui.Select(
                placeholder="Mais opções:",
                custom_id="musicplayer_dropdown_inter",
                min_values=0,
                max_values=1,
                required=False,
                options=[
                    disnake.SelectOption(
                        label="Adicionar música",
                        emoji="➕",
                        value=PlayerControls.add_song,
                        description="Adicionar uma música/playlist na fila.",
                    ),
                    disnake.SelectOption(
                        label="Adicionar nos seus favoritos",
                        emoji="💗",
                        value=PlayerControls.add_favorite,
                        description="Adicionar a música atual nos seus favoritos.",
                    ),
                    disnake.SelectOption(
                        label="Tocar do inicio",
                        emoji="⏪",
                        value=PlayerControls.seek_to_start,
                        description="Voltar o tempo da música atual para o inicio.",
                    ),
                    disnake.SelectOption(
                        label=f"Volume: {player.volume}%",
                        emoji="🔊",
                        value=PlayerControls.volume,
                        description="Ajustar volume.",
                    ),
                    disnake.SelectOption(
                        label="Misturar",
                        emoji="🔀",
                        value=PlayerControls.shuffle,
                        description="Misturar as músicas da fila.",
                    ),
                    disnake.SelectOption(
                        label="Readicionar",
                        emoji="🎶",
                        value=PlayerControls.readd,
                        description="Readicionar as músicas tocadas de volta na fila.",
                    ),
                    disnake.SelectOption(
                        label="Repetição",
                        emoji="🔁",
                        value=PlayerControls.loop_mode,
                        description="Ativar/Desativar repetição da música/fila.",
                    ),
                    disnake.SelectOption(
                        label=("Desativar" if player.nightcore else "Ativar") + " o efeito nightcore",
                        emoji="🇳",
                        value=PlayerControls.nightcore,
                        description="Efeito que aumenta velocidade e tom da música.",
                    ),
                    disnake.SelectOption(
                        label=("Desativar" if player.autoplay else "Ativar") + " a reprodução automática",
                        emoji="🔄",
                        value=PlayerControls.autoplay,
                        description="Sistema de adição de música automática quando a fila estiver vazia.",
                    ),
                    disnake.SelectOption(
                        label="Last.fm scrobble",
                        emoji="🎧",
                        value=PlayerControls.lastfm_scrobble,
                        description="Ativar/desativar o scrobble/registro de músicas na sua conta do last.fm.",
                    ),
                    disnake.SelectOption(
                        label=("Desativar" if player.restrict_mode else "Ativar") + " o modo restrito",
                        emoji="🔐",
                        value=PlayerControls.restrict_mode,
                        description="Apenas DJ's/Staff's podem usar comandos restritos.",
                    ),
                ],
            ),
        ]

        if player.current.ytid and player.node.lyric_support:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Visualizar letras",
                    emoji="📃",
                    value=PlayerControls.lyrics,
                    description="Obter letra da música atual.",
                )
            )

        if player.mini_queue_feature:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Mini-fila do player",
                    emoji="📑",
                    value=PlayerControls.miniqueue,
                    description="Ativar/Desativar a mini-fila do player.",
                )
            )

        if isinstance(player.last_channel, disnake.VoiceChannel):
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Status automático",
                    emoji="📢",
                    value=PlayerControls.set_voice_status,
                    description="Configurar o status automático do canal de voz.",
                )
            )

        if not player.has_thread:
            data["components"][5].options.append(
                disnake.SelectOption(
                    label="Song-Request Thread",
                    emoji="💬",
                    value=PlayerControls.song_request_thread,
                    description="Criar uma thread/conversa temporária para pedir músicas usando apenas o nome/link.",
                )
            )

        return data


def load():
    return DefaultSkin()

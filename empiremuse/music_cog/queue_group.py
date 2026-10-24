# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção até a KI-29b (grupo /queue coeso; clear e do_move têm ~270 linhas cada).
import traceback
from random import shuffle
from typing import Union, Optional

import disnake
from disnake.ext import commands

from empiremuse.utils.music.checks import (
    check_voice,
    has_player,
    is_dj,
    check_pool_bots,
    check_queue_loading,
)
from empiremuse.utils.music.converters import (
    time_format,
    fix_characters,
    string_to_seconds,
)
from empiremuse.utils.music.errors import (
    GenericError,
)
from empiremuse.utils.music.interactions import (
    QueueInteraction,
)
from empiremuse.utils.music.models import (
    LavalinkPlayer,
)
from empiremuse.utils.others import (
    CustomContext,
    PlayerControls,
    queue_track_index,
    pool_command,
    CommandArgparse,
)

# O corpo da classe usa estes nomes, então eles precisam existir neste módulo.
from empiremuse.music_cog.shared import (
    DESC_PREFIX as desc_prefix,
    remove_mc,
    queue_manipulation_cd,
)


class QueueGroupMixin:
    @has_player()
    @check_voice()
    @commands.slash_command(name="queue", extras={"only_voiced": True})
    @commands.contexts(guild=True)
    async def q(self, inter):
        pass

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(
        name="shuffle",
        aliases=["sf", "shf", "sff", "misturar"],
        only_voiced=True,
        description="Misturar as músicas da fila",
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def shuffle_legacy(self, ctx: CustomContext):
        await self.shuffle_.callback(self, inter=ctx)

    @is_dj()
    @q.sub_command(
        name="shuffle",
        description=f"{desc_prefix}Misturar as músicas da fila",
        extras={"only_voiced": True},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def shuffle_(self, inter: disnake.ApplicationCommandInteraction):
        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if len(player.queue) < 3:
            raise GenericError("**A fila tem que ter no mínimo 3 músicas para ser misturada.**")

        shuffle(player.queue)

        await self.interaction_message(
            inter,
            ["misturou as músicas da fila.", f"🔀 **⠂{inter.author.mention} misturou as músicas da fila.**"],
            emoji="🔀",
        )

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(
        name="reverse",
        aliases=["invert", "inverter", "rv"],
        only_voiced=True,
        description="Inverter a ordem das músicas na fila",
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def reverse_legacy(self, ctx: CustomContext):
        await self.reverse.callback(self=self, inter=ctx)

    @is_dj()
    @q.sub_command(
        description=f"{desc_prefix}Inverter a ordem das músicas na fila",
        extras={"only_voiced": True},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def reverse(self, inter: disnake.ApplicationCommandInteraction):
        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if len(player.queue) < 2:
            raise GenericError("**A fila tem que ter no mínimo 2 músicas para inverter a ordem.**")

        player.queue.reverse()
        await self.interaction_message(
            inter,
            txt=[
                "inverteu a ordem das músicas na fila.",
                f"🔄 **⠂{inter.author.mention} inverteu a ordem das músicas na fila.**",
            ],
            emoji="🔄",
        )

    queue_show_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @has_player()
    @check_voice()
    @pool_command(
        name="queue",
        aliases=["q", "fila"],
        description="Exibir as músicas que estão na fila.",
        only_voiced=True,
        max_concurrency=queue_show_mc,
    )
    async def queue_show_legacy(self, ctx: CustomContext):
        await self.display.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.member)
    @q.sub_command(description=f"{desc_prefix}Exibir as músicas que estão na fila.", max_concurrency=queue_show_mc)
    async def display(self, inter: disnake.ApplicationCommandInteraction):
        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.queue and not player.queue_autoplay:
            raise GenericError("**Não há músicas na fila.**")

        view = QueueInteraction(bot, inter.author)
        embed = view.embed

        try:
            if bot.user.id != self.bot.user.id:
                embed.set_footer(text=f"Bot selecionado: {bot.user.display_name}", icon_url=bot.user.display_avatar.url)
        except AttributeError:
            pass

        await inter.response.defer(ephemeral=True)

        kwargs = {"embed": embed, "view": view}

        try:
            func = inter.followup.send
            kwargs["ephemeral"] = True
        except AttributeError:
            try:
                func = inter.edit_original_message
            except AttributeError:
                func = inter.send
                kwargs["ephemeral"] = True

        view.message = await func(**kwargs)

        await view.wait()

    adv_queue_flags = CommandArgparse()

    adv_queue_flags.add_argument(
        "-songtitle",
        "-name",
        "-title",
        "-songname",
        nargs="+",
        help="incluir nome que tiver na música.\nEx: -name NCS",
        default=[],
    )

    adv_queue_flags.add_argument(
        "-uploader",
        "-author",
        "-artist",
        nargs="+",
        default=[],
        help="Remover músicas com o nome que tiver no autor/artista/uploader especificado.\nEx: -uploader sekai",
    )

    adv_queue_flags.add_argument(
        "-member",
        "-user",
        "-u",
        nargs="+",
        default=[],
        help="Remover músicas pedidas pelo usuário especificado.\nEx: -user @user",
    )

    adv_queue_flags.add_argument(
        "-duplicates", "-dupes", "-duplicate", action="store_true", help="Remover músicas duplicadas."
    )

    adv_queue_flags.add_argument(
        "-playlist",
        "-list",
        "-pl",
        nargs="+",
        default=[],
        help="Remover música que tiver com o nome especificado na playlist associada.\nEx: -playlist minhaplaylist",
    )

    adv_queue_flags.add_argument(
        "-minimaltime",
        "-mintime",
        "-min",
        "-minduration",
        "-minduration",
        default=None,
        help="Remover músicas com a duração mínima especificada.\nEx: -min 1:23.",
    )

    adv_queue_flags.add_argument(
        "-maxduration",
        "-maxtime",
        "-max",
        default=None,
        help="Remover músicas com a duração máxima especificada.\nEx: -max 1:23.",
    )

    adv_queue_flags.add_argument(
        "-amount",
        "-counter",
        "-count",
        "-c",
        type=int,
        default=None,
        help="Especificar uma quantidade de músicas para mover com o nome especificado.\nEx: -amount 5",
    )

    adv_queue_flags.add_argument(
        "-startposition",
        "-startpos",
        "-start",
        type=int,
        default=0,
        help="Remover músicas a partir de uma posição inicial da fila.\nEx: -start 10",
    )

    adv_queue_flags.add_argument(
        "-endposition",
        "-endpos",
        "-end",
        type=int,
        default=0,
        help="Remover músicas da fila até uma posição específica na fila.\nEx: -end 15",
    )

    adv_queue_flags.add_argument(
        "-absentmembers",
        "-absent",
        "-abs",
        action="store_true",
        help="Remover músicas adicionads por membros que saíram do canal",
    )

    clear_flags = CommandArgparse(parents=[adv_queue_flags])

    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(
        name="clear",
        aliases=["limpar", "clearqueue"],
        description="Limpar a fila de música.",
        only_voiced=True,
        extras={"flags": clear_flags},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def clear_legacy(self, ctx: CustomContext, *, flags: str = ""):
        args, unknown = ctx.command.extras["flags"].parse_known_args(flags.split())

        await self.clear.callback(
            self=self,
            inter=ctx,
            song_name=" ".join(args.songtitle + unknown),
            song_author=" ".join(args.uploader),
            user=await commands.MemberConverter().convert(ctx, " ".join(args.member)) if args.member else None,
            duplicates=args.duplicates,
            playlist=" ".join(args.playlist),
            min_duration=args.minimaltime,
            max_duration=args.maxduration,
            amount=args.amount,
            range_start=args.startposition,
            range_end=args.endposition,
            absent_members=args.absentmembers,
        )

    @check_queue_loading()
    @is_dj()
    @has_player()
    @check_voice()
    @q.sub_command(
        name="clear",
        description=f"{desc_prefix}Limpar a fila de música.",
        extras={"only_voiced": True},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def clear(
        self,
        inter: disnake.ApplicationCommandInteraction,
        song_name: str = commands.Param(name="nome", description="Incluir um nome que tiver na música.", default=None),
        song_author: str = commands.Param(
            name="uploader", description="Incluir um nome que tiver no autor/artista/uploader da música.", default=None
        ),
        user: disnake.Member = commands.Param(
            name="membro", description="Incluir músicas pedidas pelo membro selecionado.", default=None
        ),
        duplicates: bool = commands.Param(name="duplicados", description="Incluir músicas duplicadas", default=False),
        playlist: str = commands.Param(description="Incluir nome que tiver na playlist.", default=None),
        min_duration: str = commands.Param(
            name="duração_inicial", description="incluir músicas com duração acima/igual (ex. 1:23).", default=None
        ),
        max_duration: str = commands.Param(
            name="duração_máxima",
            description="Incluir músicas com duração máxima especificada (ex. 1:45).",
            default=None,
        ),
        amount: int = commands.Param(
            name="quantidade", description="Quantidade de músicas para mover.", min_value=0, max_value=99, default=None
        ),
        range_start: int = commands.Param(
            name="posição_inicial",
            description="incluir músicas da fila a partir da posição específicada.",
            min_value=1.0,
            max_value=500.0,
            default=0,
        ),
        range_end: int = commands.Param(
            name="posição_final",
            description="incluir músicas da fila até a posição especificada.",
            min_value=1.0,
            max_value=500.0,
            default=0,
        ),
        absent_members: bool = commands.Param(
            name="membros_ausentes",
            description="Incluir músicas adicionads por membros que saíram do canal.",
            default=False,
        ),
    ):
        if min_duration and max_duration:
            raise GenericError(
                "Você deve escolher apenas uma das opções: **duração_abaixo_de** ou **duração_acima_de**."
            )

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.queue:
            raise GenericError("**Não há musicas na fila.**")

        if amount is None:
            amount = 0

        filters = []
        final_filters = set()

        txt = []
        playlist_hyperlink = set()

        tracklist = []

        if song_name:
            song_name = song_name.replace("️", "")
            filters.append("song_name")
        if song_author:
            song_author = song_author.replace("️", "")
            filters.append("song_author")
        if user:
            filters.append("user")
        if playlist:
            playlist = playlist.replace("️", "")
            filters.append("playlist")
        if min_duration:
            filters.append("time_below")
            min_duration = string_to_seconds(min_duration) * 1000
        if max_duration:
            filters.append("time_above")
            max_duration = string_to_seconds(max_duration) * 1000
        if absent_members:
            filters.append("absent_members")
        if duplicates:
            filters.append("duplicates")

        if not filters and not range_start and not range_end:
            player.queue.clear()
            txt = ["limpou a fila de música.", f"♻️ **⠂{inter.author.mention} limpou a fila de música.**"]

        else:
            if range_start > 0 and range_end > 0:
                if range_start >= range_end:
                    raise GenericError("**A posição final deve ser maior que a posição inicial!**")

                song_list = list(player.queue)[range_start - 1 : -(range_end - 1)]
                txt.append(f"**Posição inicial da fila:** `{range_start}`\n**Posição final da fila:** `{range_end}`")

            elif range_start > 0:
                song_list = list(player.queue)[range_start - 1 :]
                txt.append(f"**Posição inicial da fila:** `{range_start}`")
            elif range_end > 0:
                song_list = list(player.queue)[: -(range_end - 1)]
                txt.append(f"**Posição final da fila:** `{range_end}`")
            else:
                song_list = list(player.queue)

            deleted_tracks = 0

            duplicated_titles = set()

            amount_counter = int(amount) if amount > 0 else 0

            for t in song_list:
                if amount and amount_counter < 1:
                    break

                temp_filter = list(filters)

                if "duplicates" in temp_filter:
                    if (title := f"{t.author} - {t.title}".lower()) in duplicated_titles:
                        temp_filter.remove("duplicates")
                        final_filters.add("duplicates")
                    else:
                        duplicated_titles.add(title)

                if "time_below" in temp_filter and t.duration >= min_duration:
                    temp_filter.remove("time_below")
                    final_filters.add("time_below")

                elif "time_above" in temp_filter and t.duration <= max_duration:
                    temp_filter.remove("time_above")
                    final_filters.add("time_above")

                if "song_name" in temp_filter:
                    title = t.title.replace("️", "").lower().split()

                    query_words = song_name.lower().split()

                    word_count = 0

                    for query_word in song_name.lower().split():
                        for title_word in title:
                            if query_word in title_word:
                                title.remove(title_word)
                                word_count += 1
                                break

                    if word_count == len(query_words):
                        temp_filter.remove("song_name")
                        final_filters.add("song_name")

                if "song_author" in temp_filter and song_author.lower() in t.author.replace("️", "").lower():
                    temp_filter.remove("song_author")
                    final_filters.add("song_author")

                if "user" in temp_filter and user.id == t.requester:
                    temp_filter.remove("user")
                    final_filters.add("user")

                elif "absent_members" in temp_filter and t.requester not in player.guild.me.voice.channel.voice_states:
                    temp_filter.remove("absent_members")
                    final_filters.add("absent_members")

                playlist_link = None

                if "playlist" in temp_filter:
                    if playlist == t.playlist_name.replace("️", "") or (
                        isinstance(inter, CustomContext) and playlist.lower() in t.playlist_name.replace("️", "").lower()
                    ):
                        playlist_link = f"[`{fix_characters(t.playlist_name)}`](<{t.playlist_url}>)"
                        temp_filter.remove("playlist")
                        final_filters.add("playlist")

                if not temp_filter:
                    tracklist.append(t)
                    player.queue.remove(t)
                    deleted_tracks += 1
                    if playlist_link:
                        playlist_hyperlink.add(playlist_link)

                    if amount:
                        amount_counter -= 1

            duplicated_titles.clear()

            if not deleted_tracks:
                await inter.send("Nenhuma música encontrada!", ephemeral=True)
                return

            try:
                final_filters.remove("song_name")
                txt.append(f"**Inclui nome:** `{fix_characters(song_name)}`")
            except Exception:
                pass

            try:
                final_filters.remove("song_author")
                txt.append(f"**Inclui nome no uploader/artista:** `{fix_characters(song_author)}`")
            except Exception:
                pass

            try:
                final_filters.remove("user")
                txt.append(f"**Pedido pelo membro:** {user.mention}")
            except Exception:
                pass

            try:
                final_filters.remove("playlist")
                txt.append(f"**Playlist:** {' | '.join(playlist_hyperlink)}")
            except Exception:
                pass

            try:
                final_filters.remove("time_below")
                txt.append(f"**Com duração inicial/igual:** `{time_format(min_duration)}`")
            except Exception:
                pass

            try:
                final_filters.remove("time_above")
                txt.append(f"**Com duração máxima:** `{time_format(max_duration)}`")
            except Exception:
                pass

            try:
                final_filters.remove("duplicates")
                txt.append(f"**Músicas duplicadas**")
            except Exception:
                pass

            try:
                final_filters.remove("absent_members")
                txt.append("`Músicas pedidas por membros que saíram do canal.`")
            except Exception:
                pass

            msg_txt = (
                f"### ♻️ ⠂{inter.author.mention} removeu {deleted_tracks} música{'s'[: deleted_tracks ^ 1]} da fila:\n"
                + "\n".join(f"[`{fix_characters(t.title, 45)}`](<{t.uri}>)" for t in tracklist[:7])
            )

            if (trackcount := (len(tracklist) - 7)) > 0:
                msg_txt += f"\n`e mais {trackcount} música{'s'[: trackcount ^ 1]}.`"

            msg_txt += f"\n### ✅ ⠂Filtro{(t := 's'[: len(txt) ^ 1])} usado{t}:\n" + "\n".join(txt)

            txt = [f"removeu {deleted_tracks} música{'s'[: deleted_tracks ^ 1]} da fila via clear.", msg_txt]

        try:
            kwargs = {"thumb": tracklist[0].thumb}
        except IndexError:
            kwargs = {}

        await self.interaction_message(inter, txt, emoji="♻️", **kwargs)

    move_queue_flags = CommandArgparse(parents=[adv_queue_flags])

    move_queue_flags.add_argument(
        "-position", "-pos", help="Especificar uma posição de destino (opcional).\nEx: -pos 1", type=int, default=None
    )

    move_queue_flags.add_argument(
        "-casesensitive",
        "-cs",
        action="store_true",
        help="Buscar por músicas com a frase exata no nome da música ao invés de buscar palavra por palavra.",
    )

    @check_queue_loading()
    @is_dj()
    @has_player()
    @check_voice()
    @pool_command(
        name="move",
        aliases=["movequeue", "moveadv", "moveadvanced", "moveq", "mq", "mv", "mover"],
        description="Mover músicas da fila.",
        only_voiced=True,
        extras={"flags": move_queue_flags},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    async def move_legacy(self, ctx: CustomContext, position: Optional[int] = None, *, flags: str = ""):
        args, unknown = ctx.command.extras["flags"].parse_known_args(flags.split())

        if args.position:
            if position:
                unknown.insert(0, str(position))
            position = args.position

        if position is None:
            position = 1

        await self.do_move(
            inter=ctx,
            position=position,
            song_name=" ".join(unknown + args.songtitle),
            song_author=" ".join(args.uploader),
            user=await commands.MemberConverter().convert(ctx, " ".join(args.member)) if args.member else None,
            duplicates=args.duplicates,
            playlist=" ".join(args.playlist),
            min_duration=args.minimaltime,
            max_duration=args.maxduration,
            amount=args.amount,
            range_start=args.startposition,
            range_end=args.endposition,
            absent_members=args.absentmembers,
        )

    @check_queue_loading()
    @is_dj()
    @has_player()
    @check_voice()
    @commands.slash_command(
        name="move",
        description=f"{desc_prefix}Mover músicas da fila.",
        extras={"only_voiced": True},
        cooldown=queue_manipulation_cd,
        max_concurrency=remove_mc,
    )
    @commands.contexts(guild=True)
    async def move(
        self,
        inter: disnake.ApplicationCommandInteraction,
        song_name: str = commands.Param(name="nome", description="Incluir um nome que tiver na música.", default=None),
        position: int = commands.Param(
            name="posição", description="Posição de destino na fila (Opcional).", min_value=1, max_value=900, default=1
        ),
        song_author: str = commands.Param(
            name="uploader", description="Incluir um nome que tiver no autor/artista/uploader da música.", default=None
        ),
        user: disnake.Member = commands.Param(
            name="membro", description="Incluir músicas pedidas pelo membro selecionado.", default=None
        ),
        duplicates: bool = commands.Param(name="duplicados", description="Incluir músicas duplicadas", default=False),
        playlist: str = commands.Param(description="Incluir nome que tiver na playlist.", default=None),
        min_duration: str = commands.Param(
            name="duração_inicial", description="incluir músicas com duração acima/igual (ex. 1:23).", default=None
        ),
        max_duration: str = commands.Param(
            name="duração_máxima",
            description="Incluir músicas com duração máxima especificada (ex. 1:45).",
            default=None,
        ),
        amount: int = commands.Param(
            name="quantidade", description="Quantidade de músicas para mover.", min_value=0, max_value=99, default=None
        ),
        range_start: int = commands.Param(
            name="posição_inicial",
            description="incluir músicas da fila a partir da posição específicada.",
            min_value=1.0,
            max_value=500.0,
            default=0,
        ),
        range_end: int = commands.Param(
            name="posição_final",
            description="incluir músicas da fila até a posição especificada.",
            min_value=1.0,
            max_value=500.0,
            default=0,
        ),
        absent_members: bool = commands.Param(
            name="membros_ausentes",
            description="Incluir músicas adicionads por membros que saíram do canal.",
            default=False,
        ),
    ):
        await self.do_move(
            inter=inter,
            position=position,
            song_name=song_name,
            song_author=song_author,
            user=user,
            duplicates=duplicates,
            playlist=playlist,
            min_duration=min_duration,
            max_duration=max_duration,
            amount=amount,
            range_start=range_start,
            range_end=range_end,
            absent_members=absent_members,
        )

    async def do_move(
        self,
        inter: Union[disnake.ApplicationCommandInteraction, CustomContext],
        position: int = 1,
        song_name: str = None,
        song_author: str = None,
        user: disnake.Member = None,
        duplicates: bool = False,
        playlist: str = None,
        min_duration: str = None,
        max_duration: str = None,
        amount: int = None,
        range_start: int = 0,
        range_end: int = 0,
        absent_members: bool = False,
        case_sensitive=False,
    ):
        if min_duration and max_duration:
            raise GenericError(
                "Você deve escolher apenas uma das opções: **duração_abaixo_de** ou **duração_acima_de**."
            )

        try:
            bot = inter.music_bot
        except AttributeError:
            bot = inter.bot

        player: LavalinkPlayer = bot.music.players[inter.guild_id]

        if not player.queue and not player.queue_autoplay:
            raise GenericError("**Não há musicas na fila.**")

        filters = []
        final_filters = set()

        txt = []
        playlist_hyperlink = set()

        tracklist = []

        if song_name:
            song_name = song_name.replace("️", "")
            filters.append("song_name")
        if song_author:
            song_author = song_author.replace("️", "")
            filters.append("song_author")
        if user:
            filters.append("user")
        if playlist:
            playlist = playlist.replace("️", "")
            filters.append("playlist")
        if min_duration:
            filters.append("time_below")
            min_duration = string_to_seconds(min_duration) * 1000
        if max_duration:
            filters.append("time_above")
            max_duration = string_to_seconds(max_duration) * 1000
        if absent_members:
            filters.append("absent_members")
        if duplicates:
            filters.append("duplicates")

        if not filters and not range_start and not range_end:
            raise GenericError("**Você deve usar pelo menos uma opção pra mover**")

        indexes = None

        try:
            has_id = song_name.split(" || ID > ")[1]
        except Exception:
            has_id = isinstance(inter, CustomContext)

        insert_func = player.queue.insert

        if range_start > 0 and range_end > 0:
            if range_start >= range_end:
                raise GenericError("**A posição final deve ser maior que a posição inicial!**")

            song_list = list(player.queue)[range_start - 1 : -(range_end - 1)]
            txt.append(f"**Posição inicial da fila:** `{range_start}`\n**Posição final da fila:** `{range_end}`")

        elif range_start > 0:
            song_list = list(player.queue)[range_start - 1 :]
            txt.append(f"**Posição inicial da fila:** `{range_start}`")
        elif range_end > 0:
            song_list = list(player.queue)[: -(range_end - 1)]
            txt.append(f"**Posição final da fila:** `{range_end}`")
        elif song_name and has_id and filters == ["song_name"] and amount is None:
            indexes = queue_track_index(inter, bot, song_name, match_count=1, case_sensitive=case_sensitive)
            for index, track in reversed(indexes):
                try:
                    player.queue.remove(track)
                except ValueError:
                    player.queue_autoplay.remove(track)
                    insert_func = player.queue_autoplay.insert
                tracklist.append(track)
            song_list = []

        else:
            song_list = list(player.queue)

        if not tracklist:
            if amount is None:
                amount = 0

            duplicated_titles = set()

            amount_counter = int(amount) if amount > 0 else 0

            for t in song_list:
                if amount and amount_counter < 1:
                    break

                temp_filter = list(filters)

                if "duplicates" in temp_filter:
                    if (title := f"{t.author} - {t.title}".lower()) in duplicated_titles:
                        temp_filter.remove("duplicates")
                        final_filters.add("duplicates")
                    else:
                        duplicated_titles.add(title)

                if "time_below" in temp_filter and t.duration >= min_duration:
                    temp_filter.remove("time_below")
                    final_filters.add("time_below")

                elif "time_above" in temp_filter and t.duration <= max_duration:
                    temp_filter.remove("time_above")
                    final_filters.add("time_above")

                if "song_name" in temp_filter:
                    title = t.title.replace("️", "").lower().split()

                    query_words = song_name.lower().split()

                    word_count = 0

                    for query_word in song_name.lower().split():
                        for title_word in title:
                            if query_word in title_word:
                                title.remove(title_word)
                                word_count += 1
                                break

                    if word_count == len(query_words):
                        temp_filter.remove("song_name")
                        final_filters.add("song_name")

                if "song_author" in temp_filter and song_author.lower() in t.author.replace("️", "").lower():
                    temp_filter.remove("song_author")
                    final_filters.add("song_author")

                if "user" in temp_filter and user.id == t.requester:
                    temp_filter.remove("user")
                    final_filters.add("user")

                elif "absent_members" in temp_filter and t.requester not in player.guild.me.voice.channel.voice_states:
                    temp_filter.remove("absent_members")
                    final_filters.add("absent_members")

                playlist_link = None

                if "playlist" in temp_filter:
                    if playlist == t.playlist_name.replace("️", "") or (
                        isinstance(inter, CustomContext) and playlist.lower() in t.playlist_name.replace("️", "").lower()
                    ):
                        playlist_link = f"[`{fix_characters(t.playlist_name)}`]({t.playlist_url})"
                        temp_filter.remove("playlist")
                        final_filters.add("playlist")

                if not temp_filter:
                    track = player.queue[player.queue.index(t)]
                    player.queue.remove(t)
                    tracklist.append(track)
                    if playlist_link:
                        playlist_hyperlink.add(playlist_link)

                    if amount:
                        amount_counter -= 1

            duplicated_titles.clear()

        if not tracklist:
            raise GenericError("Nenhuma música encontrada com os filtros selecionados!")

        for t in reversed(tracklist):
            insert_func(position - 1, t)

        try:
            final_filters.remove("song_name")
            txt.append(f"**Inclui nome:** `{fix_characters(song_name)}`")
        except Exception:
            pass

        try:
            final_filters.remove("song_author")
            txt.append(f"**Inclui nome no uploader/artista:** `{fix_characters(song_author)}`")
        except Exception:
            pass

        try:
            final_filters.remove("user")
            txt.append(f"**Pedido pelo membro:** {user.mention}")
        except Exception:
            pass

        try:
            final_filters.remove("playlist")
            txt.append(f"**Playlist:** {' | '.join(playlist_hyperlink)}")
        except Exception:
            pass

        try:
            final_filters.remove("time_below")
            txt.append(f"**Com duração inicial/igual:** `{time_format(min_duration)}`")
        except Exception:
            pass

        try:
            final_filters.remove("time_above")
            txt.append(f"**Com duração máxima:** `{time_format(max_duration)}`")
        except Exception:
            pass

        try:
            final_filters.remove("duplicates")
            txt.append(f"**Músicas duplicadas**")
        except Exception:
            pass

        try:
            final_filters.remove("absent_members")
            txt.append("`Músicas pedidas por membros que saíram do canal.`")
        except Exception:
            pass

        components = [
            disnake.ui.Button(emoji="▶️", label="Tocar agora", custom_id=PlayerControls.embed_forceplay),
        ]

        if indexes:
            track = tracklist[0]
            txt = [
                f"moveu a música [`{fix_characters(track.title, limit=25)}`](<{track.uri or track.search_uri}>) para a posição **[{position}]** da fila.",
                f"↪️ **⠂{inter.author.mention} moveu uma música para a posição [{position}]:**\n"
                f"╰[`{fix_characters(track.title, limit=43)}`](<{track.uri or track.search_uri}>)",
            ]

            await self.interaction_message(inter, txt, emoji="↪️", components=components)

        else:
            moved_tracks = len(tracklist)

            moved_tracks_txt = moved_tracks if moved_tracks == 1 else f"[{position}-{position + moved_tracks - 1}]"

            msg_txt = (
                f"### ↪️ ⠂{inter.author.mention} moveu {moved_tracks} música{'s'[: moved_tracks ^ 1]} para a posição {moved_tracks_txt} da fila:\n"
                + "\n".join(
                    f"`{position + n}.` [`{fix_characters(t.title, 45)}`](<{t.uri}>)"
                    for n, t in enumerate(tracklist[:7])
                )
            )

            if (track_extra := (moved_tracks - 7)) > 0:
                msg_txt += f"\n`e mais {track_extra} música{'s'[: track_extra ^ 1]}.`"

            msg_txt += f"\n### ✅ ⠂Filtro{(t := 's'[: len(txt) ^ 1])} usado{t}:\n" + "\n".join(txt)

            txt = [
                f"moveu {moved_tracks} música{'s'[: moved_tracks ^ 1]} para a posição **[{position}]** da fila.",
                msg_txt,
            ]

            await self.interaction_message(
                inter, txt, emoji="↪️", force=True, thumb=tracklist[0].thumb, components=components
            )

    @move.autocomplete("playlist")
    @clear.autocomplete("playlist")
    async def queue_playlist(self, inter: disnake.Interaction, query: str):
        try:
            if not inter.author.voice:
                return
        except Exception:
            pass

        if not self.bot.bot_ready or not self.bot.is_ready():
            return [query]

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except Exception:
            traceback.print_exc()
            return

        try:
            player = bot.music.players[inter.guild_id]
        except KeyError:
            return

        return list(
            set(
                [
                    track.playlist_name
                    for track in player.queue
                    if track.playlist_name and query.lower() in track.playlist_name.lower()
                ]
            )
        )[:20]

    @move.autocomplete("uploader")
    @clear.autocomplete("uploader")
    async def queue_author(self, inter: disnake.Interaction, query: str):
        if not self.bot.bot_ready or not self.bot.is_ready():
            return [query]

        try:
            await check_pool_bots(inter, only_voiced=True)
            bot = inter.music_bot
        except Exception:
            return

        if not inter.author.voice:
            return

        try:
            player = bot.music.players[inter.guild_id]
        except KeyError:
            return

        if not query:
            return list(set([track.authors_string for track in player.queue]))[:20]
        else:
            return list(
                set([track.authors_string for track in player.queue if query.lower() in track.authors_string.lower()])
            )[:20]

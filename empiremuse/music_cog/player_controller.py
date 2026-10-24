# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção até a KI-29b (Music.player_controller, 776 linhas, é um listener coeso).
import asyncio
from typing import Union, Optional

import disnake
from disnake.ext import commands

import empiremuse.wavelink as wavelink
from empiremuse.rules.errors import RuleError
from empiremuse.rules.favorites import save_track
from empiremuse.utils.client import BotCore
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.checks import (
    is_dj,
    can_connect,
    check_player_perm,
)
from empiremuse.utils.music.converters import (
    fix_characters,
    URL_REG,
)
from empiremuse.utils.music.errors import (
    GenericError,
)
from empiremuse.utils.music.user_limits import quota_for, track_fav_error_text
from empiremuse.utils.music.interactions import (
    SelectInteraction,
)
from empiremuse.utils.music.models import (
    LavalinkPlayer,
)
from empiremuse.utils.others import (
    send_idle_embed,
    PlayerControls,
    music_source_emoji_url,
)


class PlayerControllerMixin:
    async def player_controller(self, interaction: disnake.MessageInteraction, control: str, **kwargs):
        if not self.bot.bot_ready or not self.bot.is_ready():
            await interaction.send("Ainda estou inicializando...", ephemeral=True)
            return

        if not interaction.guild_id:
            await interaction.response.edit_message(components=None)
            return

        cmd_kwargs = {}

        cmd: Optional[disnake.ApplicationCommandInteraction] = None

        if control in (
            PlayerControls.embed_forceplay,
            PlayerControls.embed_enqueue_track,
            PlayerControls.embed_enqueue_playlist,
        ):
            try:
                try:
                    if not (url := interaction.message.embeds[0].author.url):
                        if not (matches := URL_REG.findall(interaction.message.embeds[0].description)):
                            return
                        url = matches[0].split(">")[0]
                except Exception:
                    return

                try:
                    await self.player_interaction_concurrency.acquire(interaction)
                except Exception:
                    raise GenericError("Há uma música sendo processada no momento...")

                bot: Optional[BotCore] = None
                player: Optional[LavalinkPlayer] = None
                channel: Union[disnake.TextChannel, disnake.VoiceChannel, disnake.StageChannel, disnake.Thread] = None
                author: Optional[disnake.Member] = None

                for b in sorted(
                    self.bot.pool.get_guild_bots(interaction.guild_id), key=lambda b: b.identifier, reverse=True
                ):
                    try:
                        p = b.music.players[interaction.guild_id]
                    except KeyError:
                        if c := b.get_channel(interaction.channel_id):
                            bot = b
                            channel = c
                            author = c.guild.get_member(interaction.author.id)
                        continue

                    if p.guild.me.voice and interaction.author.id in p.guild.me.voice.channel.voice_states:
                        if p.locked:
                            raise GenericError(
                                "**Não é possível executar essa ação com o processamento da música em andamento "
                                "(por favor aguarde mais alguns segundos e tente novamente).**"
                            )

                        player = p
                        bot = b
                        channel = player.text_channel
                        author = p.guild.get_member(interaction.author.id)
                        break

                if not channel:
                    raise GenericError("Não há bots disponíveis no momento.")

                if not author.voice:
                    raise GenericError("Você deve entrar em um canal de voz pra usar esse botão....")

                try:
                    node = player.node
                except Exception:
                    node: Optional[wavelink.Node] = None

                try:
                    interaction.author = author
                except AttributeError:
                    pass

                await check_player_perm(inter=interaction, bot=bot, channel=interaction.channel)

                vc_id: int = author.voice.channel.id

                can_connect(channel=author.voice.channel, guild=channel.guild)

                await interaction.response.defer()

                if control == PlayerControls.embed_enqueue_playlist:
                    if retry_after := self.bot.pool.enqueue_playlist_embed_cooldown.get_bucket(
                        interaction
                    ).update_rate_limit():
                        raise GenericError(
                            f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} pra adicionar uma playlist no player atual.**"
                        )

                    if not player:
                        player = await self.create_player(
                            inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                        )

                    await self.check_player_queue(interaction.author, bot, interaction.guild_id)
                    result, node = await self.get_tracks(
                        url, interaction, author, source=False, node=player.node, bot=bot
                    )
                    result = await self.check_player_queue(interaction.author, bot, interaction.guild_id, tracks=result)
                    player.queue.extend(result.tracks)
                    await interaction.send(
                        f"{interaction.author.mention}, a playlist [`{result.name}`](<{url}>) foi adicionada com sucesso!{player.controller_link}",
                        ephemeral=True,
                    )

                    if not player.is_connected:
                        await player.connect(vc_id)

                    try:
                        vc = interaction.author.voice.channel
                    except AttributeError:
                        vc = player.bot.get_channel(vc_id)

                    if isinstance(vc, disnake.StageChannel):
                        retries = 5

                        while retries > 0:
                            await asyncio.sleep(1)

                            if not player.guild.me.voice:
                                retries -= 1
                                continue

                            break

                        if player.guild.me not in vc.speakers:
                            stage_perms = vc.permissions_for(player.guild.me)
                            if stage_perms.manage_permissions:
                                await asyncio.sleep(1.5)
                                await player.guild.me.edit(suppress=False)

                    if not player.current:
                        await player.process_next()

                else:
                    track = []
                    seek_status = False

                    if player:
                        if (
                            control == PlayerControls.embed_forceplay
                            and player.current
                            and (player.current.uri.startswith(url) or url.startswith(player.current.uri))
                        ):
                            await self.check_stage_title(inter=interaction, bot=bot, player=player)
                            await player.seek(0)
                            player.set_command_log("voltou para o início da música.", emoji="⏪")
                            await asyncio.sleep(3)
                            await player.update_stage_topic()
                            await asyncio.sleep(7)
                            seek_status = True

                        else:
                            for t in list(player.queue):
                                if t.uri.startswith(url) or url.startswith(t.uri):
                                    track = [t]
                                    player.queue.remove(t)
                                    break

                            if not track:
                                for t in list(player.played):
                                    if t.uri.startswith(url) or url.startswith(t.uri):
                                        track = [t]
                                        player.played.remove(t)
                                        break

                                if not track:
                                    for t in list(player.failed_tracks):
                                        if t.uri.startswith(url) or url.startswith(t.uri):
                                            track = [t]
                                            player.failed_tracks.remove(t)
                                            break

                    if not seek_status:
                        if not track:
                            if retry_after := self.bot.pool.enqueue_track_embed_cooldown.get_bucket(
                                interaction
                            ).update_rate_limit():
                                raise GenericError(
                                    f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} para adicionar uma nova música na fila.**"
                                )

                            if control == PlayerControls.embed_enqueue_track:
                                await self.check_player_queue(interaction.author, bot, interaction.guild_id)

                            result, node = await self.get_tracks(
                                url, interaction, author, source=False, node=node, bot=bot
                            )

                            track = result

                        if control == PlayerControls.embed_enqueue_track:
                            if not player:
                                player = await self.create_player(
                                    inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                                )
                            await self.check_player_queue(interaction.author, bot, interaction.guild_id)
                            player.update = True
                            if isinstance(track, list):
                                t = track[0]
                                player.queue.append(t)
                                await interaction.send(
                                    f"{author.mention}, a música [`{t.title}`](<{t.uri}>) foi adicionada na fila.{player.controller_link}",
                                    ephemeral=True,
                                )
                            else:
                                player.queue.extend(track.tracks)
                                await interaction.send(
                                    f"{author.mention}, a playlist [`{track.name}`](<{track.url}>) foi adicionada na fila.{player.controller_link}",
                                    ephemeral=True,
                                )
                            if not player.is_connected:
                                await player.connect(vc_id)
                            if not player.current:
                                await player.process_next()

                        else:
                            if not player:
                                player = await self.create_player(
                                    inter=interaction, bot=bot, guild=channel.guild, channel=channel, node=node
                                )
                            else:
                                await self.check_stage_title(inter=interaction, bot=bot, player=player)

                            if isinstance(track, list):
                                player.queue.insert(0, track[0])
                            else:
                                index = len(player.queue)
                                player.queue.extend(track.tracks)
                                if index:
                                    player.queue.rotate(index * -1)
                            if not player.is_connected:
                                await player.connect(vc_id)
                            await self.process_music(inter=interaction, player=player, force_play="yes")

            except Exception as e:
                self.bot.dispatch("interaction_player_error", interaction, e)
                if not isinstance(e, GenericError):
                    await asyncio.sleep(5)
            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass
            return

        if control == PlayerControls.embed_add_fav:
            try:
                embed = interaction.message.embeds[0]
            except IndexError:
                await interaction.send("A embed da mensagem foi removida...", ephemeral=True)
                return

            if retry_after := self.bot.pool.add_fav_embed_cooldown.get_bucket(interaction).update_rate_limit():
                await interaction.send(
                    f"**Você terá que aguardar {(rta := int(retry_after))} segundo{'s'[: rta ^ 1]} para adicionar um novo favorito.**",
                    ephemeral=True,
                )
                return

            await interaction.response.defer()

            user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

            limit = await quota_for(self.bot, interaction.author, "MAX_USER_FAVS")

            saved = save_track(user_data["fav_links"], embed.author.name[1:], embed.author.url, limit=limit)

            if isinstance(saved, RuleError):
                await interaction.edit_original_message(track_fav_error_text(saved))
                return

            fav_name = saved.name
            user_data["fav_links"] = saved.entries

            await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

            global_data = await self.bot.get_global_data(interaction.guild_id, db_name=DBModel.guilds)

            try:
                cmd = (
                    f"</play:"
                    + str(
                        self.bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id
                    )
                    + ">"
                )
            except AttributeError:
                cmd = "/play"

            try:
                interaction.message.embeds[0].fields[0].value = (
                    f"{interaction.author.mention} "
                    + interaction.message.embeds[0].fields[0].value.replace(interaction.author.mention, "")
                )
            except IndexError:
                interaction.message.embeds[0].add_field(
                    name="**Membros que favoritaram o link:**", value=interaction.author.mention
                )

            await interaction.send(
                embed=disnake.Embed(
                    description=f"[`{fav_name}`](<{embed.author.url}>) **foi adicionado nos seus favoritos!**\n\n"
                    "**Como usar?**\n"
                    f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                    "* Clicando no botão/select de tocar favorito/integração do player.\n"
                    f"* Usando o comando {global_data['prefix'] or self.bot.default_prefix}{self.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                ).set_footer(
                    text=f"Caso queira ver todos os seus favoritos use o comando {global_data['prefix'] or self.bot.default_prefix}{self.fav_manager_legacy.name}"
                ),
                ephemeral=True,
            )

            if not interaction.message.flags.ephemeral:
                if not interaction.guild:
                    await (await interaction.original_response()).edit(embed=interaction.message.embeds[0])
                else:
                    await interaction.message.edit(embed=interaction.message.embeds[0])
            return

        if not interaction.guild:
            await interaction.response.edit_message(components=None)
            return

        try:
            if control == "musicplayer_request_channel":
                cmd = self.bot.get_slash_command("setup")
                cmd_kwargs = {"target": interaction.channel}
                await self.process_player_interaction(interaction, cmd, cmd_kwargs)
                return

            if control == PlayerControls.fav_manager:
                if str(interaction.user.id) not in interaction.message.content:
                    await interaction.send("Você não pode interagir aqui!", ephemeral=True)
                    return

                cmd = self.bot.get_slash_command("fav_manager")
                await self.process_player_interaction(interaction, cmd, cmd_kwargs)
                return

            if control in (PlayerControls.add_song, PlayerControls.enqueue_fav):
                if not interaction.user.voice:
                    raise GenericError("**Você deve entrar em um canal de voz para usar esse botão.**")

                user_data = await self.bot.get_global_data(id_=interaction.user.id, db_name=DBModel.users)

                modal_components = []

                if user_data["fav_links"]:
                    fav_opts = []

                    for k, v in list(user_data["fav_links"].items())[:25]:
                        emoji, platform = music_source_emoji_url(v)
                        fav_opts.append(
                            disnake.SelectOption(
                                label=fix_characters(k, 35),
                                value=f"> fav: {k}",
                                description=f"⭐ -> {platform}",
                                emoji=emoji,
                            )
                        )

                    modal_components.append(
                        disnake.ui.Label(
                            text="⭐⠂Favoritos:",
                            component=disnake.ui.StringSelect(
                                options=fav_opts, required=False, min_values=0, custom_id="fav_links"
                            ),
                        ),
                    )

                if user_data["integration_links"]:
                    integration_opts = []

                    update = False

                    for k, v in list(user_data["integration_links"].items())[:25]:
                        if not isinstance(v, dict):
                            v = {"url": v, "avatar": None}
                            user_data["integration_links"][k] = v
                            update = True

                        emoji, platform = music_source_emoji_url(v["url"])

                        integration_opts.append(
                            disnake.SelectOption(
                                label=fix_characters(k[6:], 35),
                                value=f"> itg: {k}",
                                description=f"💠 -> {platform}",
                                emoji=emoji,
                            )
                        )

                    modal_components.append(
                        disnake.ui.Label(
                            text="💠⠂Integrações:",
                            component=disnake.ui.StringSelect(
                                options=integration_opts, required=False, min_values=0, custom_id="integration_links"
                            ),
                        )
                    )

                    if update:
                        await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

                modal_components = [
                    disnake.ui.Label(
                        text="Nome ou link do youtube/spotify/soundcloud...",
                        component=disnake.ui.TextInput(
                            custom_id="song_input", max_length=150, required=not modal_components
                        ),
                    ),
                    disnake.ui.Label(
                        text="Posição da fila (número).",
                        component=disnake.ui.TextInput(custom_id="song_position", max_length=3, required=False),
                    ),
                ] + modal_components

                await interaction.response.send_modal(
                    title="Pedir uma música",
                    custom_id="modal_add_song" + (f"_{interaction.message.id}" if interaction.message.thread else ""),
                    components=modal_components,
                )

                return

            if control == PlayerControls.lastfm_scrobble:
                await interaction.response.defer(ephemeral=True, with_message=True)
                user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

                if not user_data["lastfm"]["sessionkey"]:
                    try:
                        cmd = (
                            f"</lastfm:"
                            + str(
                                self.bot.get_global_command_named(
                                    "lastfm", cmd_type=disnake.ApplicationCommandType.chat_input
                                ).id
                            )
                            + ">"
                        )
                    except AttributeError:
                        cmd = "/lastfm"

                    await interaction.edit_original_message(
                        content=f"Você não possui uma conta do last.fm vinculada nos meus dados. "
                        f"Você pode vincular uma conta do last.fm usando o comando {cmd}."
                    )
                    return

                user_data["lastfm"]["scrobble"] = not user_data["lastfm"]["scrobble"]
                self.bot.pool.lastfm_sessions[interaction.author.id] = user_data["lastfm"]
                await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)
                await interaction.edit_original_message(
                    embed=disnake.Embed(
                        description=f"**O scrobble/registro de músicas foi {'ativado' if user_data['lastfm']['scrobble'] else 'desativado'} na conta: [{user_data['lastfm']['username']}](<https://www.last.fm/user/{user_data['lastfm']['username']}>).**",
                        color=self.bot.get_color(),
                    )
                )
                return

            try:
                player: LavalinkPlayer = self.bot.music.players[interaction.guild_id]
            except KeyError:
                await interaction.send("Não há player ativo no servidor...", ephemeral=True)
                await send_idle_embed(interaction.message, bot=self.bot)
                return

            if interaction.message != player.message:
                if control != PlayerControls.queue:
                    return

            if player.interaction_cooldown:
                raise GenericError("O player está em cooldown, tente novamente em instantes.")

            try:
                vc = player.guild.me.voice.channel
            except AttributeError:
                await player.destroy(force=True)
                return

            if control == PlayerControls.help_button:
                embed = disnake.Embed(
                    description="📘 **IFORMAÇÕES SOBRE OS BOTÕES** 📘\n\n"
                    "⏯️ `= Pausar/Retomar a música.`\n"
                    "⏮️ `= Voltar para a música tocada anteriormente.`\n"
                    "⏭️ `= Pular para a próxima música.`\n"
                    "🔀 `= Misturar as músicas da fila.`\n"
                    "🎶 `= Adicionar música/playlist/favorito.`\n"
                    "⏹️ `= Parar o player e me desconectar do canal.`\n"
                    "📑 `= Exibir a fila de música.`\n"
                    "🛠️ `= Alterar algumas configurações do player:`\n"
                    "`volume / efeito nightcore / repetição / modo restrito.`\n",
                    color=self.bot.get_color(interaction.guild.me),
                )

                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if not interaction.author.voice or interaction.author.voice.channel != vc:
                raise GenericError(f"Você deve estar no canal <#{vc.id}> para usar os botões do player.")

            if control == PlayerControls.miniqueue:
                await is_dj().predicate(interaction)
                player.mini_queue_enabled = not player.mini_queue_enabled
                player.set_command_log(
                    emoji="📑",
                    text=f"{interaction.author.mention} {'ativou' if player.mini_queue_enabled else 'desativou'} "
                    f"a mini-fila do player.",
                )
                await player.invoke_np(interaction=interaction)
                return

            if control != PlayerControls.queue:
                try:
                    await self.player_interaction_concurrency.acquire(interaction)
                except commands.MaxConcurrencyReached:
                    raise GenericError(
                        '**Você tem uma interação em aberto!**\n`Se for uma mensagem oculta, evite clicar em "ignorar".`'
                    )

            if control == PlayerControls.add_favorite:
                if not player.current:
                    await interaction.send("**Não há música tocando atualmente...**", ephemeral=True)
                    return

                choices = {}
                msg = ""

                if player.current.uri:
                    choices["Track"] = {"name": player.current.title, "url": player.current.uri, "emoji": "🎵"}
                    msg += f"**Música:** [`{player.current.title}`]({player.current.uri})\n"

                if player.current.album_url:
                    choices["Album"] = {
                        "name": player.current.album_name,
                        "url": player.current.album_url,
                        "emoji": "💽",
                    }
                    msg += f"**Album:** [`{player.current.album_name}`]({player.current.album_url})\n"

                if player.current.playlist_url:
                    choices["Playlist"] = {
                        "name": player.current.playlist_name,
                        "url": player.current.playlist_url,
                        "emoji": "📑",
                    }
                    msg += f"**Playlist:** [`{player.current.playlist_name}`]({player.current.playlist_url})\n"

                if not choices:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me),
                            description="### Não há itens para favoritar na música atual.",
                        ),
                        ephemeral=True,
                    )
                    return

                if len(choices) == 1:
                    select_type, info = list(choices.items())[0]

                else:
                    view = SelectInteraction(
                        user=interaction.author,
                        timeout=30,
                        opts=[
                            disnake.SelectOption(label=k, description=v["name"][:50], emoji=v["emoji"])
                            for k, v in choices.items()
                        ],
                    )

                    await interaction.send(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me),
                            description=f"### Selecione um item da música atual para adicionar nos seus favoritos:"
                            f"\n\n{msg}",
                        ),
                        view=view,
                        ephemeral=True,
                    )

                    await view.wait()

                    select_interaction = view.inter

                    if not select_interaction or view.selected is False:
                        try:
                            await self.player_interaction_concurrency.release(interaction)
                        except Exception:
                            pass
                        await interaction.edit_original_message(
                            embed=disnake.Embed(
                                color=self.bot.get_color(interaction.guild.me), description="### Operação cancelada!"
                            ),
                            view=None,
                        )
                        return

                    interaction = select_interaction

                    select_type = view.selected
                    info = choices[select_type]

                await interaction.response.defer()

                user_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.users)

                limit = await quota_for(self.bot, interaction.author, "MAX_USER_FAVS")

                saved = save_track(user_data["fav_links"], info["name"], info["url"], limit=limit)

                if isinstance(saved, RuleError):
                    await interaction.edit_original_message(
                        embed=disnake.Embed(
                            color=self.bot.get_color(interaction.guild.me), description=track_fav_error_text(saved)
                        ),
                        view=None,
                    )
                    return

                user_data["fav_links"] = saved.entries

                await self.bot.update_global_data(interaction.author.id, user_data, db_name=DBModel.users)

                self.bot.dispatch("fav_add", interaction.user, user_data, f"[`{info['name']}`]({info['url']})")

                global_data = await self.bot.get_global_data(interaction.author.id, db_name=DBModel.guilds)

                try:
                    slashcmd = (
                        f"</play:"
                        + str(
                            self.bot.get_global_command_named(
                                "play", cmd_type=disnake.ApplicationCommandType.chat_input
                            ).id
                        )
                        + ">"
                    )
                except AttributeError:
                    slashcmd = "/play"

                await interaction.edit_original_response(
                    embed=disnake.Embed(
                        color=self.bot.get_color(interaction.guild.me),
                        description="### Item adicionado/editado com sucesso nos seus favoritos:\n\n"
                        f"**{select_type}:** [`{info['name']}`]({info['url']})\n\n"
                        f"### Como usar?\n"
                        f"* Usando o comando {slashcmd} (no preenchimento automático da busca)\n"
                        f"* Clicando no botão/select de tocar favorito/integração do player.\n"
                        f"* Usando o comando {global_data['prefix'] or self.bot.default_prefix}{self.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.",
                    ),
                    view=None,
                )

                try:
                    await self.player_interaction_concurrency.release(interaction)
                except Exception:
                    pass

                return

            if control == PlayerControls.lyrics:
                if not player.current:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send("**Não estou tocando algo no momento...**", ephemeral=True)
                    return

                if not player.current.ytid:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.send("No momento apenas músicas do youtube são suportadas.", ephemeral=True)
                    return

                not_found_msg = "Não há letras disponíveis para a música atual..."

                await interaction.response.defer(ephemeral=True, with_message=True)

                if player.current.info["extra"].get("lyrics") is None:
                    lyrics_data = await player.node.fetch_ytm_lyrics(player.current.ytid)
                    player.current.info["extra"]["lyrics"] = {} if lyrics_data.get("track") is None else lyrics_data

                elif not player.current.info["extra"]["lyrics"]:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.edit_original_message(f"**{not_found_msg}**")
                    return

                if not player.current.info["extra"]["lyrics"]:
                    try:
                        await self.player_interaction_concurrency.release(interaction)
                    except Exception:
                        pass
                    await interaction.edit_original_message(f"**{not_found_msg}**")
                    return

                player.current.info["extra"]["lyrics"]["track"]["albumArt"] = player.current.info["extra"]["lyrics"][
                    "track"
                ]["albumArt"][:-1]

                try:
                    lyrics_string = "\n".join([d["line"] for d in player.current.info["extra"]["lyrics"]["lines"]])
                except KeyError:
                    lyrics_string = player.current.info["extra"]["lyrics"]["text"]

                try:
                    await self.player_interaction_concurrency.release(interaction)
                except Exception:
                    pass

                await interaction.edit_original_message(
                    embed=disnake.Embed(
                        description=f"### Letras da música: [{player.current.title}](<{player.current.uri}>)\n{lyrics_string}",
                        color=self.bot.get_color(player.guild.me),
                    )
                )
                return

            if control == PlayerControls.volume:
                cmd_kwargs = {"value": None}

            elif control == PlayerControls.queue:
                cmd = self.bot.get_slash_command("queue").children.get("display")

            elif control == PlayerControls.shuffle:
                cmd = self.bot.get_slash_command("queue").children.get("shuffle")

            elif control == PlayerControls.seek_to_start:
                cmd = self.bot.get_slash_command("seek")
                cmd_kwargs = {"position": "0"}

            elif control == PlayerControls.pause_resume:
                control = PlayerControls.pause if not player.paused else PlayerControls.resume

            elif control == PlayerControls.loop_mode:
                if player.loop == "current":
                    cmd_kwargs["mode"] = "queue"
                elif player.loop == "queue":
                    cmd_kwargs["mode"] = "off"
                else:
                    cmd_kwargs["mode"] = "current"

            elif control == PlayerControls.skip:
                cmd_kwargs = {"query": None, "play_only": "no"}

            if not cmd:
                cmd = self.bot.get_slash_command(control[12:])

            await self.process_player_interaction(interaction=interaction, command=cmd, kwargs=cmd_kwargs)

            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass

        except Exception as e:
            try:
                await self.player_interaction_concurrency.release(interaction)
            except Exception:
                pass
            self.bot.dispatch("interaction_player_error", interaction, e)

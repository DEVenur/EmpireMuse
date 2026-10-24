# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import itertools
import random
import traceback
from itertools import cycle

import disnake

from empiremuse.utils.db import DBModel
from empiremuse.utils.music.converters import fix_characters, time_format, get_button_style
from empiremuse.utils.music.errors import (
    code_suffix,
    log_unexpected_error,
)
from empiremuse.utils.music.skin_utils import skin_converter
from empiremuse.utils.others import PlayerControls

from empiremuse.utils.music.models.helpers import (
    logger,
)


class PlayerMessageMixin:
    async def invoke_np(self, force=False, interaction=None, rpc_update=False):
        if self.is_closing:
            return

        if not self.text_channel:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except Exception:
                pass
            return

        if not self.current:
            if not force:
                try:
                    if not interaction.response.is_done():
                        await interaction.response.defer()
                except Exception:
                    pass
            else:
                await self.process_idle_message()
            return

        if self.updating and not force:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except Exception:
                pass
            return

        if self.has_lyrics:
            return

        if rpc_update:
            try:
                await self.process_rpc()
            except Exception:
                traceback.print_exc()

        if self.retry_setup_hints:
            self.setup_hints()
            self.retry_setup_hints = False

        try:
            if self.static:
                if self.skin_static.startswith("> custom_skin: "):
                    data = skin_converter(
                        self.custom_skin_static_data[self.skin_static[15:]], player=self, guild=self.guild
                    )
                else:
                    data = self.bot.pool.player_static_skins[self.skin_static].load(self)

            else:
                if self.skin.startswith("> custom_skin: "):
                    data = skin_converter(self.custom_skin_data[self.skin[15:]], player=self, guild=self.guild)
                else:
                    data = self.bot.pool.player_skins[self.skin].load(self)
        except OverflowError:
            await self.process_next()
            return

        if data == self.last_data:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except Exception:
                pass
            return

        self.last_data = data

        if not data.get("flags"):
            try:
                if self.static and isinstance(self.text_channel.parent, disnake.ForumChannel):
                    data["content"] = (
                        f"`{'▶️' if not self.paused else '⏸️'} {fix_characters(self.current.title, 50)}` |\n\n"
                        + (data.get("content") or "")
                    )
            except Exception:
                pass

        if not self.controller_mode:
            if self.temp_embed:
                data["embeds"].insert(0, self.temp_embed)
                self.temp_embed = None

            self.updating = True

            if self.keep_connected:
                if not self.is_last_message():
                    await self.destroy_message()
                elif self.text_channel:
                    if not self.text_channel.permissions_for(self.guild.me).send_messages:
                        self.text_channel = None
                        self.message = None
                    else:
                        try:
                            await self.message.edit(allowed_mentions=self.allowed_mentions, **data)
                        except disnake.Forbidden:
                            self.message = None
                            self.text_channel = None
                        except Exception:
                            self.message = await self.text_channel.send(allowed_mentions=self.allowed_mentions, **data)

            else:
                try:
                    self.message_updater_task.cancel()
                except Exception:
                    pass
                self.message = await self.text_channel.send(allowed_mentions=self.allowed_mentions, **data)

            self.updating = False

        else:
            # nenhum controle de botão foi definido na skin (será usado os botões padrões).
            if data.get("components") is None:
                # Aviso: Não modifique os components abaixo, prefira copiar uma das skins da pasta utils -> music -> skins
                # e deixá-la com outro nome (sem acentos, espaços, caracteres especiais) e modifique-as a seu gosto.
                # Caso queira deixar uma skin customizada por padrão adicione/modifique a config DEFAULT_SKIN="tuaskin"

                data["components"] = [
                    disnake.ui.Button(
                        emoji="⏯️", custom_id=PlayerControls.pause_resume, style=get_button_style(self.paused)
                    ),
                    disnake.ui.Button(emoji="⏮️", custom_id=PlayerControls.back),
                    disnake.ui.Button(emoji="⏹️", custom_id=PlayerControls.stop),
                    disnake.ui.Button(emoji="⏭️", custom_id=PlayerControls.skip),
                    disnake.ui.Button(
                        emoji="📑", custom_id=PlayerControls.queue, disabled=not (self.queue or self.queue_autoplay)
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
                                label=f"Volume: {self.volume}%",
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
                                label=("Desativar" if self.nightcore else "Ativar") + " o efeito nightcore",
                                emoji="🇳",
                                value=PlayerControls.nightcore,
                                description="Efeito que aumenta velocidade e tom da música.",
                            ),
                            disnake.SelectOption(
                                label=("Desativar" if self.autoplay else "Ativar") + " a reprodução automática",
                                emoji="🔄",
                                value=PlayerControls.autoplay,
                                description="Sistema de reprodução de música automática quando a fila tiver vazia.",
                            ),
                            disnake.SelectOption(
                                label="Last.fm scrobble",
                                emoji="🎧",
                                value=PlayerControls.lastfm_scrobble,
                                description="Ativar/desativar o scrobble/registro de músicas na sua conta do last.fm.",
                            ),
                            disnake.SelectOption(
                                label=("Desativar" if self.restrict_mode else "Ativar") + " o modo restrito",
                                emoji="🔐",
                                value=PlayerControls.restrict_mode,
                                description="Apenas DJ's/Staff's podem usar comandos restritos.",
                            ),
                        ],
                    ),
                ]

                if self.static:
                    if queue := self.queue or self.queue_autoplay:
                        data["components"].append(
                            disnake.ui.Select(
                                placeholder="Próximas músicas:",
                                custom_id="musicplayer_queue_dropdown",
                                min_values=0,
                                max_values=1,
                                required=False,
                                options=[
                                    disnake.SelectOption(
                                        label=fix_characters(f"{n + 1}. {t.single_title}", 47),
                                        description=fix_characters(
                                            f"[{time_format(t.duration) if not t.is_stream else '🔴 Live'}]. {t.authors_string}",
                                            47,
                                        ),
                                        value=f"{n:02d}.{t.title[:96]}",
                                    )
                                    for n, t in enumerate(itertools.islice(queue, 25))
                                ],
                            )
                        )

                if self.current.ytid and self.node.lyric_support:
                    data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Visualizar letras",
                            emoji="📃",
                            value=PlayerControls.lyrics,
                            description="Obter letra da música atual.",
                        )
                    )

                if self.mini_queue_feature:
                    data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Mini-fila do player",
                            emoji="📑",
                            value=PlayerControls.miniqueue,
                            description="Ativar/Desativar a mini-fila do player.",
                        )
                    )

                if isinstance(self.last_channel, disnake.VoiceChannel):
                    data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Status automático",
                            emoji="📢",
                            value=PlayerControls.set_voice_status,
                            description="Configurar o status automático do canal de voz.",
                        )
                    )

                if not self.static and not self.has_thread:
                    data["components"][5].options.append(
                        disnake.SelectOption(
                            label="Song-Request Thread",
                            emoji="💬",
                            value=PlayerControls.song_request_thread,
                            description="Criar uma thread/conversa temporária para pedir músicas usando apenas o nome/link.",
                        )
                    )

            self.updating = True

            if interaction:
                try:
                    del data["flags"]
                except KeyError:
                    pass

                try:
                    if interaction.response.is_done():
                        await interaction.message.edit(allowed_mentions=self.allowed_mentions, **data)
                    else:
                        await interaction.response.edit_message(allowed_mentions=self.allowed_mentions, **data)
                    self.updating = False
                except Exception:
                    traceback.print_exc()
                else:
                    self.start_message_updater_task()
                return

            else:
                if self.message and (
                    self.ignore_np_once or self.has_thread or self.static or not force or self.is_last_message()
                ):
                    self.ignore_np_once = False

                    try:
                        try:
                            if data.get("flags"):
                                data["content"] = None
                                data["embed"] = None
                            await self.message.edit(allowed_mentions=self.allowed_mentions, **data)
                            await asyncio.sleep(0.5)
                        except asyncio.CancelledError:
                            self.updating = False
                            return
                        except Exception:
                            traceback.print_exc()

                            try:
                                self.text_channel = self.bot.get_channel(
                                    self.text_channel.id
                                ) or await self.bot.fetch_channel(self.text_channel.id)
                            except (AttributeError, disnake.Forbidden, disnake.HTTPException):
                                self.text_channel = None

                            if not self.text_channel:
                                self.message = None
                                return

                            if isinstance(self.text_channel, disnake.Thread):
                                if (
                                    not self.text_channel.parent.permissions_for(self.guild.me).send_messages_in_threads
                                    or not self.text_channel.permissions_for(self.guild.me).read_messages
                                ):
                                    self.text_channel = None
                                    return

                                if self.text_channel.locked:
                                    if not self.text_channel.parent.permissions_for(self.guild.me).manage_threads:
                                        self.text_channel = None
                                        self.message = None
                                        return
                                    else:
                                        await self.text_channel.edit(archived=False, locked=False)

                                elif self.text_channel.archived:
                                    if self.text_channel.owner_id == self.bot.user.id:
                                        await self.text_channel.edit(archived=False)
                                    else:
                                        await self.text_channel.send("Desarquivando o tópico.", delete_after=2)

                                await self.message.edit(allowed_mentions=self.allowed_mentions, **data)
                                await asyncio.sleep(0.5)

                                # elif ((
                                #              self.text_channel.archive_timestamp - disnake.utils.utcnow()).total_seconds() / 60) < (
                                # thread_archive_time[self.text_channel.auto_archive_duration]):
                                #    await self.text_channel.send("Evitando o tópico auto-arquivar...", delete_after=2)

                            elif (
                                not self.text_channel.permissions_for(self.guild.me).send_messages
                                or not self.text_channel.permissions_for(self.guild.me).read_messages
                            ):
                                return

                        self.start_message_updater_task()
                        self.updating = False
                        return
                    except Exception as e:
                        self.updating = False
                        error_code = log_unexpected_error(logger, e, "atualização da mensagem do player")
                        if self.static or self.has_thread:
                            self.set_command_log(
                                f"{(interaction.author.mention + ' ') if interaction else ''}houve um erro na interação{code_suffix(error_code)}.",
                                "⚠️",
                                controller=True,
                            )
                            self.update = True
                            return

            await self.destroy_message()

            if not self.message:
                try:
                    self.message = await self.text_channel.send(allowed_mentions=self.allowed_mentions, **data)
                except Exception:
                    traceback.print_exc()
                else:
                    if self.static:
                        await self.channel_cleanup()
                        data = await self.bot.get_data(self.guild_id, db_name=DBModel.guilds)
                        data["player_controller"]["channel"] = str(self.text_channel.id)
                        data["player_controller"]["message_id"] = str(self.message.id)
                        await self.bot.update_data(self.guild_id, data, db_name=DBModel.guilds)

            self.start_message_updater_task()

        self.updating = False

    async def message_updater(self):
        while True:
            if not self.text_channel or not self.controller_mode:
                pass

            elif self.auto_update and not self.current.is_stream:
                await asyncio.sleep(self.auto_update)

                try:
                    await self.invoke_np()
                except Exception:
                    traceback.print_exc()

                continue

            elif self.update:
                try:
                    await self.invoke_np()
                except Exception:
                    traceback.print_exc()

                self.update = False

                await asyncio.sleep(5)

            await asyncio.sleep(10)

    async def update_message(self, interaction: disnake.Interaction = None, force=False, rpc_update=False):
        if rpc_update:
            await self.process_rpc()

        if force or (interaction and not interaction.response.is_done()):
            if self.controller_mode or interaction:
                await self.invoke_np(interaction=interaction)

        else:
            self.update = True

    def start_message_updater_task(self):
        try:
            self.message_updater_task.cancel()
        except AttributeError:
            pass
        self.message_updater_task = self.bot.loop.create_task(self.message_updater())

    async def destroy_message(self):
        try:
            self.message_updater_task.cancel()
        except Exception:
            pass

        if self.static:
            return

        try:
            if self.guild.me:
                await self.message.delete()
        except Exception:
            pass

        self.message = None

    def is_last_message(self):
        try:
            return self.last_message_id == self.message.id
        except AttributeError:
            return

    def setup_hints(self):
        hints = list(self.initial_hints)

        if self.static:
            hints.append(
                "É possível fixar músicas/playlists na mensagem do player quando tiver no modo de "
                "espera/oscioso para permitir os membros ouvi-las de forma pública. Pra isso use o "
                f"comando /fav_manager ou {self.prefix_info}favmanager (apenas membros com permissão "
                "de gerenciar servidor podem usar esse recurso)."
            )

        elif self.bot.intents.message_content and self.controller_mode:
            hints.append(
                "Ao criar uma conversa/thread na mensagem do player, será ativado o modo de song-request "
                "nela (possibilitando pedir música apenas enviando o nome/link da música na conversa)."
            )

        if len(self.bot.pool.get_guild_bots(self.guild.id)) > 1:
            bots_in_guild = 0
            bots_outside_guild = 0

            for b in self.bot.pool.get_guild_bots(self.guild.id):
                if b == self.bot:
                    continue

                try:
                    self.bot.user.id
                except AttributeError:
                    self.retry_setup_hints = True
                    continue

                if b.get_guild(self.guild.id):
                    bots_in_guild += 1
                else:
                    bots_outside_guild += 1

            if bots_in_guild:
                hints.append(
                    "Caso algum membro queira me usar em outro canal de voz sem precisar aguardar me "
                    f"desconectarem ou me interromperem do canal atual, há mais {bots_in_guild} bot{'s'[: bots_in_guild ^ 1]} no servidor que "
                    f"funciona{'m'[: bots_in_guild ^ 1]} com o meu sistema/comandos (usando o mesmo prefixo/comandos de barra). "
                    f"Experimente entrar em um canal de voz diferente do meu atual e use o comando "
                    f"{self.prefix_info}play ou /play."
                )

            elif bots_outside_guild:
                hints.append(
                    "Caso algum membro queira me usar em outro canal de voz sem precisar aguardar me "
                    f"desconectarem ou me interromperem do canal atual. Dá para adicionar mais {bots_outside_guild} bot{'s'[: bots_outside_guild ^ 1]} "
                    f"extras no servidor atual que funciona(m) com o mesmo sistema/comandos (usando o mesmo "
                    f"prefixo/comandos de barra). Use o comando {self.prefix_info}invite ou /invite para adicioná-los."
                )

        if self.controller_mode:
            hints.append(
                "Ao clicar nesse emoji 🎛️ das mensagens de alguns comandos você será redirecionado para o player-controller."
            )

        random.shuffle(hints)
        self.hints = cycle(hints)

    def process_hint(self):
        if random.choice([x for x in range(self.hint_rate)]) == 0:
            self.current_hint = next(self.hints)
        else:
            self.current_hint = ""

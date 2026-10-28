# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Union, Optional, TYPE_CHECKING

import disnake

from empiremuse.rules.errors import (
    STATUS_CHARS,
    STATUS_TOO_LONG,
    RuleError,
)
from empiremuse.rules.limits import (
    VOICE_PLACEHOLDERS,
    VOICE_STATUS_MAX_LENGTH,
)
from empiremuse.rules.settings import validate_voice_status
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.checks import (
    VOICE_STATUS_PERMISSION,
    mention_channels,
    voice_status_blocked_channel,
)
from empiremuse.utils.music.models import LavalinkPlayer
from empiremuse.utils.others import (
    CustomContext,
)

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

from empiremuse.utils.music.interactions.view_modal import ViewModal


class SetStageTitle(disnake.ui.View):
    placeholders = VOICE_PLACEHOLDERS

    placeholder_text = (
        "```ansi\n[34;1m{track.title}[0m -> Nome da música\n"
        "[34;1m{track.author}[0m -> Nome do Artista/Uploader/Autor da música.\n"
        "[34;1m{track.duration}[0m -> Duração da música.\n"
        "[34;1m{track.timestamp}[0m -> Duração da música em contagem regressiva (apenas em canal de voz).\n"
        "[34;1m{track.source}[0m -> Origem/Fonte da música (Youtube/Spotify/Soundcloud etc)\n"
        "[34;1m{track.emoji}[0m -> Emoji da fonte de música (apenas em canal de voz).\n"
        "[34;1m{track.playlist}[0m -> Nome da playlist de origem da música (caso tenha)\n"
        "[34;1m{requester.name}[0m -> Nome/Nick do membro que pediu a música\n"
        "[34;1m{requester.id}[0m -> ID do membro que pediu a música```\n"
        "Exemplo: Tocando {track.title} | Por: {track.author}\n\n"
        "`Nota: No canal de voz você pode usar custom emojis na mensagem do status (incluindo emoji de servers que eu não estou e de servers que você não está).`"
    )

    def __init__(self, ctx: Union[CustomContext, disnake.Interaction], bot: BotCore, guild: disnake.Guild, data: dict):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.bot = bot
        self.data = data
        self.guild = guild
        self.message = None

        if self.data["voice_channel_status"]:
            setstatus_btn = disnake.ui.Button(
                label="Usar modelo atual",
                emoji="🎶",
                style=disnake.ButtonStyle.grey,
                custom_id="status_voice_channel_temp_current",
            )
            setstatus_btn.callback = self.setstatus_callback
            self.add_item(setstatus_btn)

        setstatus_modal_btn = disnake.ui.Button(
            label="Ativar/Desativar status", emoji="🔊", style=disnake.ButtonStyle.grey
        )
        setstatus_modal_btn.callback = self.set_status_modal
        self.add_item(setstatus_modal_btn)

        setstatus_perm_btn = disnake.ui.Button(
            label="Ativar/Desativar status (permanente)", emoji="💾", style=disnake.ButtonStyle.grey
        )
        setstatus_perm_btn.callback = self.set_status_perm
        self.add_item(setstatus_perm_btn)

    async def setstatus_callback(self, interaction: disnake.MessageInteraction):
        await self.modal_handler(inter=interaction, values={"status_voice_value": self.data["voice_channel_status"]})

    async def set_status_modal(self, interaction: disnake.MessageInteraction):
        await interaction.response.send_modal(
            ViewModal(
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="status",
                        custom_id="status_voice_value",
                        placeholder="Pra desativar deixe vazio",
                        max_length=VOICE_STATUS_MAX_LENGTH,
                        required=False,
                    ),
                ],
                view=self,
                title="Definir status do canal",
                custom_id="status_voice_channel_temp",
            )
        )

    async def set_status_perm(self, interaction: disnake.MessageInteraction):
        await interaction.response.send_modal(
            ViewModal(
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="status permanente",
                        custom_id="status_voice_value",
                        placeholder="Pra desativar deixe vazio",
                        max_length=VOICE_STATUS_MAX_LENGTH,
                        required=False,
                    ),
                ],
                view=self,
                title="Definir status do canal",
                custom_id="status_voice_channel_perm",
            )
        )

    def build_embeds(self):
        embeds = []

        color = self.bot.get_color(self.guild.me)

        embeds.append(
            disnake.Embed(
                description="### Definir status automático no canal de voz ou palco\n"
                "**Placeholders:** `(Pelo menos um placeholder deve ser incluso na mensagem de status)`\n"
                f"{self.placeholder_text}",
                color=color,
            )
        )

        if self.data["voice_channel_status"]:
            embeds.append(
                disnake.Embed(
                    title="**Modelo permanente atual:**",
                    description=self.data["voice_channel_status"],
                    color=self.bot.get_color(self.guild.me),
                )
            )

        return embeds

    async def modal_handler(self, inter: disnake.ModalInteraction, values: dict = None):
        try:
            values = inter.text_values
        except AttributeError:
            pass

        status = validate_voice_status(values["status_voice_value"])

        if isinstance(status, RuleError):
            if status.code == STATUS_TOO_LONG:
                await inter.send(
                    f"**O status pode ter no máximo {VOICE_STATUS_MAX_LENGTH} caracteres.**", ephemeral=True
                )
            elif status.code == STATUS_CHARS:
                await inter.send("**O status não pode ter caracteres de controle nem de formatação.**", ephemeral=True)
            else:
                await inter.send("**Você deve usar pelo menos um placeholder válido...**", ephemeral=True)
            return

        values["status_voice_value"] = status

        if inter.data.custom_id == "status_voice_channel_perm":
            if self.data["voice_channel_status"] == values["status_voice_value"]:
                await inter.send("**O status permanente atual é o mesmo do informado...**", ephemeral=True)
                return

            guild: Optional[disnake.Guild] = None

            for b in self.bot.pool.get_guild_bots(inter.guild_id):
                if guild := b.get_guild(inter.guild_id):
                    break

            if not guild:
                await inter.send(
                    "**Não há bots disponíveis no servidor, Adicione pelo menos um clicando no botão abaixo.**",
                    components=[disnake.ui.Button(custom_id="bot_invite", label="Adicionar bots")],
                    ephemeral=True,
                )
                return

            inter.author = guild.get_member(inter.author.id)

            if not inter.author.guild_permissions.manage_guild:
                await inter.send(
                    "**Você não possui a permissão de gerenciar servidor para alterar o status do canal de voz**",
                    ephemeral=True,
                )
                return

            self.data["voice_channel_status"] = values["status_voice_value"]

            await inter.response.defer(ephemeral=True)

            await self.bot.update_global_data(inter.guild_id, self.data, db_name=DBModel.guilds)

            blocked_channels = []

            for b in self.bot.pool.get_guild_bots(inter.guild_id):
                try:
                    p = b.music.players[inter.guild_id]
                except KeyError:
                    continue

                # O modelo é configuração do servidor e fica salvo; o player sem a permissão só não liga o status.
                blocked = voice_status_blocked_channel(p.guild) if values["status_voice_value"] else None
                if blocked:
                    blocked_channels.append(blocked)

                p.stage_title_event = bool(values["status_voice_value"]) and not blocked
                p.stage_title_template = values["status_voice_value"]
                p.start_time = disnake.utils.utcnow()
                if not blocked:
                    p.set_command_log(
                        text=f"{inter.author.mention} "
                        + ("ativou" if values["status_voice_value"] else "desativou")
                        + " o status automático",
                        emoji="📢",
                    )
                p.update = True

                if p.stage_title_event:
                    await p.update_stage_topic()
                else:
                    await p.update_stage_topic(clear=True)

                await p.process_save_queue()
                await asyncio.sleep(3)

            if blocked_channels:
                await inter.edit_original_message(
                    f"**Status permanente salvo, mas falta a permissão {VOICE_STATUS_PERMISSION} em "
                    f"{mention_channels(blocked_channels)}.** Peça a um administrador para liberá-la."
                )
            else:
                await inter.edit_original_message(
                    "**Status permanente foi "
                    + ("salvo" if values["status_voice_value"] else "desativado")
                    + " com sucesso!**"
                )

        elif inter.data.custom_id.startswith("status_voice_channel_temp"):
            player: Optional[LavalinkPlayer] = None

            for bot in self.bot.pool.get_guild_bots(inter.guild_id):
                try:
                    player = bot.music.players[inter.guild_id]
                except KeyError:
                    continue

                if inter.author.id not in player.guild.me.voice.channel.voice_states:
                    continue

                break

            if not player:
                await inter.send("**Não estou tocando música em um canal de voz/palco...**", ephemeral=True)
                return

            inter.author = player.guild.get_member(inter.author.id)

            if not inter.author.guild_permissions.manage_guild:
                await inter.send(
                    "Você não possui a permissão de gerenciar servidor para alterar o status do canal de voz",
                    ephemeral=True,
                )
                return

            if values["status_voice_value"] and (blocked := voice_status_blocked_channel(player.guild)):
                await inter.send(
                    f"**Não tenho a permissão {VOICE_STATUS_PERMISSION} em {blocked.mention}.** "
                    "Peça a um administrador para liberá-la.",
                    ephemeral=True,
                )
                return

            player.stage_title_event = bool(values["status_voice_value"])
            player.stage_title_template = values["status_voice_value"]
            player.start_time = disnake.utils.utcnow()

            await inter.response.defer(ephemeral=True)

            if player.stage_title_event:
                await player.update_stage_topic()
            else:
                await player.update_stage_topic(clear=True)

            await player.process_save_queue()

            player.set_command_log(
                text=f"{inter.author.mention} "
                + ("ativou" if values["status_voice_value"] else "desativou")
                + " o status automático",
                emoji="📢",
            )

            player.update = True

            await inter.edit_original_message(
                "**Status definido com sucesso!**"
                if values["status_voice_value"]
                else "**Status desativado com sucesso!**"
            )

        else:
            await inter.send(f"Não implementado: {inter.data.custom_id}", ephemeral=True)
            return

        await self.close()
        self.stop()

    async def on_timeout(self) -> None:
        await self.close()

    async def close(self):
        for c in self.children:
            c.disabled = True

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        else:
            try:
                await self.ctx.edit_original_message(view=self)
            except Exception:
                pass

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.ctx.author.id:
            await inter.send(
                f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True
            )
            return False
        return True

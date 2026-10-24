# -*- coding: utf-8 -*-

import disnake
from disnake.ext import commands

from empiremuse.utils.db import DBModel
from empiremuse.utils.music.errors import (
    GenericError,
    NoVoice,
    DiffVoiceChannel,
    NoPlayer,
)
from empiremuse.utils.music.interactions import (
    SetStageTitle,
)
from empiremuse.utils.others import (
    CustomContext,
    pool_command,
)

# O corpo da classe usa ``desc_prefix`` (como no corpo de ``Music``), então o nome precisa existir neste módulo.
from empiremuse.music_cog.shared import DESC_PREFIX as desc_prefix


class VoiceStatusMixin:
    stage_cd = commands.CooldownMapping.from_cooldown(2, 45, commands.BucketType.guild)
    stage_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)

    @commands.has_guild_permissions(manage_guild=True)
    @pool_command(
        only_voiced=True,
        name="setvoicestatus",
        aliases=[
            "stagevc",
            "togglestageannounce",
            "announce",
            "vcannounce",
            "setstatus",
            "voicestatus",
            "setvcstatus",
            "statusvc",
            "vcstatus",
            "stageannounce",
        ],
        description="Ativar o sistema de anuncio/status automático do canal com o nome da música.",
        cooldown=stage_cd,
        max_concurrency=stage_mc,
        extras={"exclusive_cooldown": True},
        usage="{prefix}{cmd} <placeholders>\nEx: {track.author} - {track.title}",
    )
    async def setvoicestatus_legacy(self, ctx: CustomContext, *, template=""):
        await self.set_voice_status.callback(self=self, inter=ctx, template=template)

    @commands.slash_command(
        description=f"{desc_prefix}Ativar/editar o sistema de anúncio/status automático do canal com o nome da música.",
        extras={"only_voiced": True, "exclusive_cooldown": True},
        cooldown=stage_cd,
        max_concurrency=stage_mc,
        default_member_permissions=disnake.Permissions(manage_guild=True),
    )
    @commands.contexts(guild=True)
    async def set_voice_status(
        self,
        inter: disnake.ApplicationCommandInteraction,
        template: str = commands.Param(
            name="modelo", default="", description="Especifique manualmente um modelo de status (inclua placeholders)."
        ),
    ):
        if isinstance(template, commands.ParamInfo):
            template = ""

        try:
            bot = inter.music_bot
            guild = inter.music_guild
            author = guild.get_member(inter.author.id)
        except AttributeError:
            bot = inter.bot
            guild = inter.guild
            author = inter.author

        if not author.guild_permissions.manage_guild and not (await bot.is_owner(author)):
            raise GenericError(
                "**Você não possui permissão de gerenciar servidor para ativar/desativar esse sistema.**"
            )

        if not template:
            await inter.response.defer(ephemeral=True, with_message=True)
            global_data = await self.bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
            view = SetStageTitle(ctx=inter, bot=bot, data=global_data, guild=guild)
            view.message = await inter.send(view=view, embeds=view.build_embeds(), ephemeral=True)
            await view.wait()
        else:
            if not any(p in template for p in SetStageTitle.placeholders):
                raise GenericError(
                    f"**Você deve usar pelo menos um placeholder válido:** {SetStageTitle.placeholder_text}"
                )

            try:
                player = bot.music.players[inter.guild_id]
            except KeyError:
                raise NoPlayer()

            if not author.voice:
                raise NoVoice()

            if author.id not in guild.me.voice.channel.voice_states:
                raise DiffVoiceChannel()

            await inter.response.defer()

            player.stage_title_event = True
            player.stage_title_template = template
            player.start_time = disnake.utils.utcnow()

            await player.update_stage_topic()

            await player.process_save_queue()

            player.set_command_log(text="ativou o status automático", emoji="📢")

            player.update = True

            if isinstance(inter, CustomContext):
                await inter.send("**O status automático foi definido com sucesso!**")
            else:
                await inter.edit_original_message("**O status automático foi definido com sucesso!**")

    @set_voice_status.autocomplete("modelo")
    async def default_models(self, inter: disnake.Interaction, query: str):
        return [
            "{track.title} - By: {track.author} | {track.timestamp}",
            "{track.emoji} | {track.title}",
            "{track.title} ( {track.playlist} )",
            "{track.title}  Solicitado por: {requester.name}",
        ]

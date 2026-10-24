# -*- coding: utf-8 -*-

import disnake
from disnake.ext import commands

from empiremuse.utils.db import DBModel
from empiremuse.utils.music.errors import (
    GenericError,
)
from empiremuse.utils.music.interactions import (
    FavMenuView,
    ViewMode,
)
from empiremuse.utils.others import (
    CustomContext,
    select_bot_pool,
)

# O corpo da classe usa estes nomes, então eles precisam existir neste módulo.
from empiremuse.music_cog.shared import (
    DESC_PREFIX as desc_prefix,
)


class FavoritesMixin:
    fav_import_export_cd = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.member)

    fav_cd = commands.CooldownMapping.from_cooldown(3, 15, commands.BucketType.member)

    @commands.command(
        name="favmanager",
        aliases=[
            "favs",
            "favoritos",
            "fvmgr",
            "favlist",
            "integrations",
            "integrationmanager",
            "itg",
            "itgmgr",
            "itglist",
            "integrationlist",
            "serverplaylist",
            "spl",
            "svp",
            "svpl",
        ],
        description="Gerenciar seus favoritos/integrações e links do server.",
        cooldown=fav_cd,
    )
    async def fav_manager_legacy(self, ctx: CustomContext):
        await self.fav_manager.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.member, wait=False)
    @commands.slash_command(
        description=f"{desc_prefix}Gerenciar seus favoritos/integrações e links do server.",
        cooldown=fav_cd,
        extras={"allow_private": True},
    )
    @commands.contexts(guild=True)
    async def fav_manager(self, inter: disnake.ApplicationCommandInteraction):
        bot = self.bot

        mode = ViewMode.fav_manager

        guild_data = None
        interaction = None

        if isinstance(inter, CustomContext):
            prefix = inter.clean_prefix

            if inter.invoked_with in ("serverplaylist", "spl", "svp", "svpl") and (
                inter.author.guild_permissions.manage_guild or await bot.is_owner(inter.author)
            ):
                interaction, bot = await select_bot_pool(inter, return_new=True)

                if not bot:
                    return

                mode = ViewMode.guild_fav_manager

                await interaction.response.defer(ephemeral=True)

                guild_data = await bot.get_data(inter.guild_id, db_name=DBModel.guilds)

            elif inter.invoked_with in (
                "integrations",
                "integrationmanager",
                "itg",
                "itgmgr",
                "itglist",
                "integrationlist",
            ):
                mode = ViewMode.integrations_manager

        else:
            global_data = await bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
            prefix = global_data["prefix"] or bot.default_prefix

        if not interaction:
            interaction = inter

        cog = self.bot.get_cog("Music")

        if cog:
            ephemeral = await cog.is_request_channel(inter, ignore_thread=True)
            await inter.response.defer(ephemeral=ephemeral)
        else:
            ephemeral = True

        user_data = await bot.get_global_data(inter.author.id, db_name=DBModel.users)

        view = FavMenuView(
            bot=bot,
            ctx=interaction,
            data=user_data,
            prefix=prefix,
            mode=mode,
            is_owner=await bot.is_owner(inter.author),
        )
        view.guild_data = guild_data

        txt = view.build_txt()

        if not txt:
            raise GenericError(
                "**Não há suporte a esse recurso no momento...**\n\n`Suporte ao spotify e YTDL não estão ativados.`"
            )

        view.message = await inter.send(txt, view=view, ephemeral=ephemeral)

        await view.wait()

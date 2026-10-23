# -*- coding: utf-8 -*-
# KI-29: 3 linhas acima do teto de 800 por causa dos imports; uma única classe coesa (FavMenuView), sem divisão prevista.
from __future__ import annotations

import json
import traceback
from io import BytesIO
from itertools import islice
from typing import Union, TYPE_CHECKING

import disnake

from empiremuse.utils.db import DBModel
from empiremuse.utils.music.checks import check_pool_bots
from empiremuse.utils.music.converters import time_format, fix_characters
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.others import (
    CustomContext,
    music_source_emoji_url,
    PlayerControls,
    get_source_emoji_cfg,
    paginator,
)

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

from empiremuse.utils.music.interactions.fav_modals import (
    FavModalAdd,
    FavModalImport,
)
from empiremuse.utils.music.interactions.common import (
    ViewMode,
    process_idle_embed,
)


class FavMenuView(disnake.ui.View):
    def __init__(
        self,
        bot: BotCore,
        ctx: Union[disnake.ApplicationCommandInteraction, CustomContext],
        data: dict,
        log: str = "",
        prefix="",
        mode: str = ViewMode.fav_manager,
        is_owner=False,
    ):
        super().__init__(timeout=180)
        self.mode = mode
        self.bot = bot
        self.ctx = ctx
        self.guild = ctx.guild
        self.current = None
        self.data = data
        self.guild_data = {}
        self.message = None
        self.log = log
        self.prefix = prefix
        self.components_updater_task = bot.loop.create_task(self.auto_update())
        self.is_owner = is_owner
        self.light_mode = False

        if not self.guild:
            for b in self.bot.pool.get_guild_bots(ctx.guild_id):
                guild = b.get_guild(ctx.guild_id)
                if guild:
                    self.guild = guild
                    break

            if not self.guild:
                self.light_mode = True

    def update_components(self):
        self.clear_items()

        if not self.light_mode:
            mode_select = disnake.ui.Select(
                options=[
                    disnake.SelectOption(
                        label="Gerenciador de Favoritos",
                        value=f"fav_view_mode_{ViewMode.fav_manager}",
                        emoji="⭐",
                        default=self.mode == ViewMode.fav_manager,
                    )
                ],
                min_values=1,
                max_values=1,
            )

            mode_select.append_option(
                disnake.SelectOption(
                    label="Gerenciador de Integrações",
                    value=f"fav_view_mode_{ViewMode.integrations_manager}",
                    emoji="💠",
                    default=self.mode == ViewMode.integrations_manager,
                )
            )

            if self.guild and (self.ctx.author.guild_permissions.manage_guild or self.is_owner):
                mode_select.options.insert(
                    1,
                    disnake.SelectOption(
                        label="Gerenciador de Playlists do Servidor",
                        value=f"fav_view_mode_{ViewMode.guild_fav_manager}",
                        emoji="📌",
                        default=self.mode == ViewMode.guild_fav_manager,
                    ),
                )

            if len(mode_select.options) < 2:
                mode_select.disabled = True

            mode_select.callback = self.mode_callback
            self.add_item(mode_select)

        if self.mode == ViewMode.fav_manager:
            if self.data["fav_links"]:
                opts = []
                for k, v in list(self.data["fav_links"].items())[
                    :25
                ]:  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    emoji, platform = music_source_emoji_url(v)
                    opts.append(disnake.SelectOption(label=k, emoji=emoji, description=platform))
                fav_select = disnake.ui.Select(options=opts, min_values=1, max_values=1)
                fav_select.options[0].default = True
                self.current = fav_select.options[0].label
                fav_select.callback = self.select_callback
                self.add_item(fav_select)

        elif self.mode == ViewMode.guild_fav_manager and self.guild:
            bots_in_guild = []

            for b in sorted(self.bot.pool.get_guild_bots(self.guild.id), key=lambda b: b.identifier):
                if b.bot_ready and b.user in self.guild.members:
                    bots_in_guild.append(
                        disnake.SelectOption(
                            emoji="🎶",
                            label=f"Bot: {b.user.display_name}"[:25],
                            value=f"bot_select_{b.user.id}",
                            description=f"ID: {b.user.id}",
                            default=b == self.bot,
                        )
                    )

            if bots_in_guild:
                bot_select = disnake.ui.Select(options=bots_in_guild, min_values=1, max_values=1)
                bot_select.callback = self.bot_select
                self.add_item(bot_select)

            if self.guild_data["player_controller"]["fav_links"]:
                fav_select = disnake.ui.Select(
                    options=[
                        disnake.SelectOption(
                            label=k, emoji=music_source_emoji_url(v["url"])[0], description=v.get("description")
                        )
                        for k, v in list(self.guild_data["player_controller"]["fav_links"].items())[
                            :25
                        ]  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    ],
                    min_values=1,
                    max_values=1,
                )
                fav_select.options[0].default = True
                self.current = fav_select.options[0].label
                fav_select.callback = self.select_callback
                self.add_item(fav_select)

        elif self.mode == ViewMode.integrations_manager:
            if self.data["integration_links"]:
                opts = []
                for k, v in list(self.data["integration_links"].items())[
                    :25
                ]:  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    if isinstance(v, dict):
                        v = v["url"]
                    emoji, platform = music_source_emoji_url(v)
                    opts.append(disnake.SelectOption(label=k[5:], emoji=emoji, description=platform, value=k))
                integration_select = disnake.ui.Select(options=opts, min_values=1, max_values=1)
                integration_select.options[0].default = True
                self.current = integration_select.options[0].value
                integration_select.callback = self.select_callback
                self.add_item(integration_select)

        add_button = disnake.ui.Button(label="Adicionar", emoji="➕")
        add_button.callback = self.add_callback
        self.add_item(add_button)

        if self.mode == ViewMode.fav_manager:
            edit_button = disnake.ui.Button(label="Editar", emoji="✍️", disabled=not self.data["fav_links"])
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(label="Remover", emoji="♻️", disabled=not self.data["fav_links"])
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Limpar favoritos", emoji="🚮", disabled=not self.data["fav_links"])
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤", disabled=not self.data["fav_links"])
            export_button.callback = self.export_callback
            self.add_item(export_button)

        elif self.mode == ViewMode.guild_fav_manager:
            edit_button = disnake.ui.Button(
                label="Editar", emoji="✍️", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(
                label="Remover", emoji="♻️", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(
                label="Limpar favoritos", emoji="🚮", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(
                label="Exportar", emoji="📤", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            export_button.callback = self.export_callback
            self.add_item(export_button)

        elif self.mode == ViewMode.integrations_manager:
            remove_button = disnake.ui.Button(label="Remover", emoji="♻️", disabled=not self.data["integration_links"])
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(
                label="Limpar Integrações", emoji="🚮", disabled=not self.data["integration_links"]
            )
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤", disabled=not self.data["integration_links"])
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Importar", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        if self.mode == ViewMode.fav_manager:
            if self.data["fav_links"] and not self.light_mode:
                play_button = disnake.ui.Button(
                    label="Tocar o favorito selecionado", emoji="▶", custom_id="favmanager_play_button"
                )
                play_button.callback = self.play_callback
                self.add_item(play_button)

        elif self.mode == ViewMode.integrations_manager:
            if self.data["integration_links"]:
                play_button = disnake.ui.Button(
                    label="Tocar uma playlist da integração selecionada", emoji="▶", custom_id="favmanager_play_button"
                )
                play_button.callback = self.play_callback
                self.add_item(play_button)

        cancel_button = disnake.ui.Button(label="Fechar", emoji="❌")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def auto_update(self):
        while True:
            if self.mode != ViewMode.fav_manager:
                return

            user, data, url = await self.bot.wait_for(
                "fav_add", check=lambda user, data, url: user.id == self.ctx.author.id
            )

            self.log = f"<{url}> foi adicionado nos seus favoritos."

            if not isinstance(self.ctx, CustomContext):
                await self.ctx.edit_original_message(content=self.build_txt(), view=self)
            elif self.message:
                await self.message.edit(content=self.build_txt(), view=self)

    async def on_timeout(self):
        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        try:
            for i in self.children[1].options:
                i.default = self.current == i.value
        except Exception:
            pass

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

        self.stop()

    def build_txt(self):
        supported_platforms = []

        if self.mode == ViewMode.integrations_manager:
            supported_platforms.extend(
                ["[`Youtube`](<https://www.youtube.com/>)", "[`Soundcloud`](<https://soundcloud.com/>)"]
            )

            if self.bot.spotify:
                supported_platforms.append("[`Spotify`](<https://open.spotify.com/>)")

            supported_platforms.append("[`Deezer`](<https://www.deezer.com/>)")

        self.update_components()

        try:
            cmd = (
                f"</play:"
                + str(self.bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id)
                + ">"
            )
        except AttributeError:
            cmd = "/play"

        if self.mode == ViewMode.fav_manager:
            txt = "### Gerenciador de favoritos.\n"

            if not self.data["fav_links"]:
                txt += "Você não possui favoritos (clique no botão de adicionar abaixo).\n"

            else:

                def format_fav(index, data):
                    name, url = data
                    e = get_source_emoji_cfg(self.bot, url)
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name, 40)}`](<{url}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{url}>)"

                txt += paginator(
                    "\n".join(
                        f"> {format_fav(n + 1, d)}" for n, d in enumerate(islice(self.data["fav_links"].items(), 22))
                    ),
                    max_size=1400,
                )[0]

            if not self.light_mode:
                txt += (
                    "\n\n**Como usá-los?**\n"
                    f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                    "* Clicando no botão/select de tocar favorito/integração do player.\n"
                    f"* Usando o comando {self.prefix}{self.bot.get_cog('Music').play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                    "* Usando o botão de tocar favorito abaixo.\n"
                )

        elif self.mode == ViewMode.guild_fav_manager:
            txt = "### Gerenciador de favoritos do servidor.\n"

            if not self.guild_data["player_controller"]["fav_links"]:
                txt += (
                    f"Não há links adicionados no bot {self.bot.user.mention} (clique no botão de adicionar abaixo).\n"
                )

            else:

                def format_gfav(index, data):
                    name, data = data
                    e = get_source_emoji_cfg(self.bot, data["url"])
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name, 40)}`](<{data['url']}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{data['url']}>)"

                txt += (
                    f"**Links atuais no bot {self.bot.user.mention}:**\n"
                    + paginator(
                        "\n".join(
                            f"> {format_gfav(n + 1, d)}"
                            for n, d in enumerate(islice(self.guild_data["player_controller"]["fav_links"].items(), 22))
                        ),
                        max_size=1400,
                    )[0]
                )

                txt += (
                    "\n\n**Como usá-los?**\n"
                    f"* Usando o menu de seleção do player durante o modo de espera.\n"
                    f"\n`Bot selecionado:` {self.bot.user.mention}"
                )

        elif self.mode == ViewMode.integrations_manager:
            txt = "### Gerenciador de integrações de canais/perfis com playlists públicas.\n"

            if not self.data["integration_links"]:
                txt += "**Você não possui integrações no momento (clique no botão de adicionar abaixo).**\n"

            else:

                def format_itg(bot, index, data):
                    name, url = data
                    if isinstance(url, dict):
                        url = url["url"]
                    e = get_source_emoji_cfg(bot, url)
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name[5:], 40)}`](<{url}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{url}>)"

                txt += (
                    f"### Suas integrações atuais:\n"
                    + paginator(
                        "\n".join(
                            f"> {format_itg(self.bot, n + 1, d)}"
                            for n, d in enumerate(islice(self.data["integration_links"].items(), 22))
                        ),
                        max_size=1400,
                    )[0]
                )

                if not self.light_mode:
                    txt += (
                        "\n\n**Como usá-los?**\n"
                        f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                        "* Clicando no botão/select de tocar favorito/integração do player.\n"
                        f"* Usando o comando {self.prefix}{self.bot.get_cog('Music').play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                        "* Usando o botão de tocar favorito abaixo.\n"
                    )

        else:
            raise GenericError(f"**Modo não implementado:** {self.mode} | {type(self.mode)}")

        if self.log:
            txt += f"\n**Última interação:**\n{self.log}\n"

        if self.mode == ViewMode.integrations_manager:
            txt += f"\n**Links de perfis/canais suportados:**\n{', '.join(supported_platforms)}"

        return txt

    async def add_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(FavModalAdd(name=None, url=None, view=self))

    async def edit_callback(self, inter: disnake.MessageInteraction):
        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        if self.mode == ViewMode.fav_manager:
            try:
                await inter.response.send_modal(
                    FavModalAdd(name=self.current, url=self.data["fav_links"][self.current], view=self)
                )
            except KeyError:
                await inter.send(f"**Não há favorito com o nome:** {self.current}", ephemeral=True)

        elif self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return
            try:
                await inter.response.send_modal(
                    FavModalAdd(
                        bot=self.bot,
                        name=self.current,
                        url=self.data["player_controller"]["fav_links"][self.current]["url"],
                        description=self.data["player_controller"]["fav_links"][self.current]["description"],
                        view=self,
                    )
                )
            except KeyError:
                await inter.send(f"**Não há favorito com nome:** {self.current}", ephemeral=True)

    async def remove_callback(self, inter: disnake.MessageInteraction):
        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        guild = None

        if self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id)

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return

            if not self.guild_data:
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        else:
            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        if self.mode == ViewMode.fav_manager:
            try:
                url = f"[`{self.current}`]({self.data['fav_links'][self.current]})"
                del self.data["fav_links"][self.current]
            except Exception:
                await inter.edit_original_message(f"**Não há favorito na lista com o nome:** {self.current}")
                return

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = f"Favorito {url} foi removido com sucesso!"

        elif self.mode == ViewMode.guild_fav_manager:
            try:
                url = f"[`{self.current}`]({self.guild_data['player_controller']['fav_links'][self.current]})"
                del self.guild_data["player_controller"]["fav_links"][self.current]
            except KeyError:
                try:
                    await process_idle_embed(self.bot, guild, guild_data=self.guild_data)
                except Exception:
                    traceback.print_exc()

                await inter.edit_original_message(
                    embed=disnake.Embed(
                        description=f"**Não há links da lista com o nome:** {self.current}",
                        color=self.bot.get_color(guild.me),
                    ),
                    view=None,
                )
                return

            await self.bot.update_data(inter.guild_id, self.guild_data, db_name=DBModel.guilds)

            self.log = f"Link {url} foi removido com sucesso da lista de favoritos do servidor!"

        elif self.mode == ViewMode.integrations_manager:
            item = self.data["integration_links"][self.current]

            if isinstance(inter, dict):
                item = item["url"]

            try:
                url = f"[`{self.current}`]({item})"
                del self.data["integration_links"][self.current]
            except Exception:
                await inter.send(f"**Não há integração na lista com o nome:** {self.current}", ephemeral=True)
                return

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = f"Integração {url} foi removida com sucesso!"

        await inter.edit_original_message(content=self.build_txt(), view=self)

    async def bot_select(self, inter: disnake.MessageInteraction):
        value = int(inter.values[0][11:])

        for b in self.bot.pool.get_guild_bots(inter.guild_id):
            try:
                if b.user.id == value:
                    self.bot = b
            except AttributeError:
                continue

        self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        await inter.response.edit_message(content=self.build_txt(), view=self)

    async def clear_callback(self, inter: disnake.MessageInteraction):
        guild = None

        if self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return

            await inter.response.defer(ephemeral=True)

            if not self.guild_data:
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        else:
            await inter.response.defer(ephemeral=True)

            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        if self.mode == ViewMode.fav_manager:
            if not self.data["fav_links"]:
                await inter.send("**Você não possui links favoritos!**", ephemeral=True)
                return

            fp = BytesIO(bytes(json.dumps(self.data["fav_links"], indent=4), "utf-8"))

            self.data["fav_links"].clear()

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = "Sua lista de favoritos foi limpa com sucesso!"

            await inter.send(
                "### Seus favoritos foram excluídos com sucesso!\n"
                "`Um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="favs.json"),
            )

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data["player_controller"]["fav_links"]:
                await inter.send("**Não há links favoritos no servidor.**", ephemeral=True)
                return

            fp = BytesIO(bytes(json.dumps(self.guild_data["player_controller"]["fav_links"], indent=4), "utf-8"))

            self.guild_data["player_controller"]["fav_links"].clear()

            await self.bot.update_data(inter.guild_id, self.guild_data, db_name=DBModel.guilds)

            try:
                await process_idle_embed(self.bot, guild, guild_data=self.guild_data)
            except Exception:
                traceback.print_exc()

            self.log = "Lista de favoritos do server foi limpa com sucesso!"

            await inter.send(
                "### Os links de favoritos do server foram excluídos com sucesso!\n"
                "`um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="guild_favs.json"),
            )

        elif self.mode == ViewMode.integrations_manager:
            if not self.data["integration_links"]:
                await inter.response.edit_message(content="**Você não possui integrações salvas!**", view=None)
                return

            fp = BytesIO(bytes(json.dumps(self.data["integration_links"], indent=4), "utf-8"))

            self.data["integration_links"].clear()

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = "Sua lista de integrações foi limpa com sucesso!"

            await inter.send(
                "### Suas integrações foram excluídas com sucesso!\n"
                "`um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="integrations.json"),
            )

        self.current = None

        if not isinstance(self.ctx, CustomContext):
            await self.ctx.edit_original_message(content=self.build_txt(), view=self)
        elif self.message:
            await self.message.edit(content=self.build_txt(), view=self)

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(FavModalImport(view=self))

    async def play_callback(self, inter: disnake.MessageInteraction):
        await check_pool_bots(inter, check_player=False)
        await self.bot.get_cog("Music").player_controller(
            inter,
            PlayerControls.add_song,
            query=f"> itg: {self.current}" if self.mode == ViewMode.integrations_manager else f"> fav: {self.current}",
        )

    async def export_callback(self, inter: disnake.MessageInteraction):
        cog = self.bot.get_cog("Music")

        if retry_after := cog.fav_import_export_cd.get_bucket(inter).update_rate_limit():
            if retry_after < 1:
                retry_after = 1
            await inter.send(
                "**Você deve aguardar {} para exportar.**".format(time_format(int(retry_after) * 1000, use_names=True)),
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        try:
            cmd = (
                f"</{cog.fav_manager.name}:"
                + str(
                    self.bot.get_global_command_named(
                        cog.fav_manager.name, cmd_type=disnake.ApplicationCommandType.chat_input
                    ).id
                )
                + ">"
            )
        except AttributeError:
            cmd = "/play"

        if self.mode == ViewMode.fav_manager:
            if not self.data["fav_links"]:
                await inter.send(
                    f"**Você não possui links favoritos..\nVocê pode adicionar usando o comando: {cmd}**",
                    ephemeral=True,
                )
                return

            fp = BytesIO(bytes(json.dumps(self.data["fav_links"], indent=4), "utf-8"))

            await inter.send(
                embed=disnake.Embed(
                    description=f"Seus favoritos estão aqui.\nVocê pode importar usando o comando: {cmd}",
                    color=self.bot.get_color(),
                ),
                file=disnake.File(fp=fp, filename="favoritos.json"),
                ephemeral=True,
            )

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data["player_controller"]["fav_links"]:
                await inter.edit_original_message(
                    content=f"**Não há músicas/playlists fixadas no servidor..\n"
                    f"Você pode adicionar usando o comando: {cmd}**"
                )

            fp = BytesIO(bytes(json.dumps(self.guild_data["player_controller"]["fav_links"], indent=4), "utf-8"))

            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            embed = disnake.Embed(
                description=f"**Os dados dos links de músicas/playlists fixas do servidor estão aqui.\n"
                f"Você pode importar usando o comando:** {cmd}",
                color=self.bot.get_color(guild.me),
            )

            await inter.send(embed=embed, file=disnake.File(fp=fp, filename="guild_favs.json"), ephemeral=True)

        elif self.mode == ViewMode.integrations_manager:
            if not self.data["integration_links"]:
                await inter.edit_original_message(
                    f"**Você não possui integrações adicionadas...\nVocê pode adicionar usando o comando: {cmd}**"
                )
                return

            fp = BytesIO(bytes(json.dumps(self.data["integration_links"], indent=4), "utf-8"))

            await inter.send(
                embed=disnake.Embed(
                    description=f"Suas integrações estão aqui.\nVocê pode importar usando o comando: {cmd}",
                    color=self.bot.get_color(),
                ),
                file=disnake.File(fp=fp, filename="integrations.json"),
                ephemeral=True,
            )

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        await inter.response.edit_message(content="**Gerenciador fechado.**", view=None)
        self.stop()

    async def mode_callback(self, inter: disnake.MessageInteraction):
        self.mode = inter.values[0][14:]

        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        if self.mode == ViewMode.fav_manager:
            self.components_updater_task = self.bot.loop.create_task(self.auto_update())

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data:
                await inter.response.defer()
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        if inter.response.is_done():
            await inter.edit_original_message(content=self.build_txt(), view=self)
        else:
            await inter.response.edit_message(content=self.build_txt(), view=self)

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True)

# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção transitória. Ainda guarda o editor de skins, que sai no PR seguinte
# (skin_editor); no fim fica só com reexportações.
from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO
from typing import Union, Optional, TYPE_CHECKING, Literal

import disnake

from empiremuse.utils.db import DBModel
from empiremuse.utils.music.errors import error_code_text, log_unexpected_error
from empiremuse.serialization.schema import SchemaError
from empiremuse.serialization.skins import MAX_SKINS_PER_MODE, validate_skin, validate_skin_name
from empiremuse.utils.music.skin_store import load_custom_skins
from empiremuse.utils.music.skin_utils import skin_converter
from empiremuse.utils.others import (
    CustomContext,
)

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

from empiremuse.utils.music.interactions.common import (
    logger as logger,
    youtube_regex as youtube_regex,
    soundcloud_regex as soundcloud_regex,
    process_idle_embed as process_idle_embed,
    ViewMode as ViewMode,
    IMPORT_ECHO_LIMIT as IMPORT_ECHO_LIMIT,
)
from empiremuse.utils.music.interactions.view_modal import (
    ViewModal as ViewModal,
)
from empiremuse.utils.music.interactions.player_views import (
    VolumeInteraction as VolumeInteraction,
    QueueInteraction as QueueInteraction,
    EmbedPaginatorInteraction as EmbedPaginatorInteraction,
    ButtonInteraction as ButtonInteraction,
    SelectInteraction as SelectInteraction,
    AskView as AskView,
    SelectBotVoice as SelectBotVoice,
)
from empiremuse.utils.music.interactions.stage_title import (
    SetStageTitle as SetStageTitle,
)
from empiremuse.utils.music.interactions.favorites_texts import (
    _echo as _echo,
    _invalid_link_text as _invalid_link_text,
    _invalid_name_text as _invalid_name_text,
    _url_error_text as _url_error_text,
    _guild_link_error_text as _guild_link_error_text,
    _name_error_text as _name_error_text,
    _save_error_text as _save_error_text,
    _IMPORT_QUOTA_TEXTS as _IMPORT_QUOTA_TEXTS,
    _import_quota_text as _import_quota_text,
    _NO_ROOM_INTEGRATION_TEXT as _NO_ROOM_INTEGRATION_TEXT,
    _retry_text as _retry_text,
    _wait_text as _wait_text,
    _profile_source as _profile_source,
    _profile_key as _profile_key,
    _profile_saved as _profile_saved,
    _spotify_profile as _spotify_profile,
)
from empiremuse.utils.music.interactions.fav_modals import (
    FavModalImport as FavModalImport,
    FavModalAdd as FavModalAdd,
)
from empiremuse.utils.music.interactions.fav_menu import (
    FavMenuView as FavMenuView,
)

SKIN_NAME_REFUSED = (
    "**O nome da skin precisa ter de 1 a 64 caracteres, sem pontos, cifrão nem caracteres invisíveis ou de controle.**"
)
SKIN_REFUSED = (
    "**Não foi possível salvar a skin: algum campo passa dos limites ou tem conteúdo inválido. "
    "Revise o texto, os embeds e os campos e tente de novo.**"
)
SKIN_LIMIT_REFUSED = (
    "**Não foi possível salvar: cada modo comporta no máximo 25 skins. Exclua uma ou salve por cima de uma existente.**"
)


base_skin = {
    "queue_max_entries": 7,
    "queue_format": "`{track.number}) [{track.duration}]` [`{track.title_42}`]({track.url})",
    "embeds": [
        {"title": "Próximas músicas:", "description": "{queue_format}", "color": "{guild.color}"},
        {
            "description": "**Tocando agora:\n[{track.title}]({track.url})**\n\n**Duração:** `{track.duration}`\n**Pedido por:** {requester.mention}\n**Uploader**: `{track.author}`\n**Playlist de origem:** [`{playlist.name}`]({playlist.url})\n\n{player.log.emoji} **Última ação:** {player.log.text}",
            "image": {"url": "{track.thumb}"},
            "color": "{guild.color}",
            "footer": {"text": "Músicas na lista: {player.queue.size}"},
        },
    ],
}


class SkinSettingsButton(disnake.ui.View):
    def __init__(self, user: disnake.Member, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.mode = "custom_skins_static"
        self.inter = None
        self.controller_enabled = True
        self.update_components()

    def update_components(self):
        self.clear_items()

        select_mode = disnake.ui.Select(
            min_values=1,
            max_values=1,
            options=[
                disnake.SelectOption(
                    label="Modo Normal",
                    description="Aplicar skin ao modo normal do player",
                    value="custom_skins",
                    default=self.mode == "custom_skins",
                ),
                disnake.SelectOption(
                    label="Song-Request",
                    description="Aplicar skin no modo song-request do player",
                    value="custom_skins_static",
                    default=self.mode == "custom_skins_static",
                ),
            ],
        )
        select_mode.callback = self.player_mode
        self.add_item(select_mode)

        if self.mode == "custom_skins":
            controller_btn = disnake.ui.Button(
                emoji="💠",
                label="Ativar Player-Controller" if not self.controller_enabled else "Desativar Player-Controller",
            )
            controller_btn.callback = self.controller_buttons
            self.add_item(controller_btn)

        save_btn = disnake.ui.Button(label="Salvar", emoji="💾")
        save_btn.callback = self.save
        self.add_item(save_btn)

    async def controller_buttons(self, inter: disnake.MessageInteraction):
        self.controller_enabled = not self.controller_enabled
        self.update_components()
        await inter.response.edit_message(view=self)

    async def player_mode(self, inter: disnake.MessageInteraction):
        self.mode = inter.values[0]
        self.update_components()
        await inter.response.edit_message(view=self)

    async def save(self, inter: disnake.ModalInteraction):
        self.inter = inter
        self.stop()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.user.id:
            await inter.send(f"Apenas o membro {self.user.mention} pode usar es botões da mensagem.", ephemeral=True)
            return False

        return True


class SkinEditorMenu(disnake.ui.View):
    def __init__(
        self,
        ctx: Union[CustomContext, disnake.ApplicationCommandInteraction],
        bot: BotCore,
        guild: disnake.Guild,
        global_data: dict,
    ):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.guild = guild
        self.message: Optional[disnake.Message] = None
        self.embed_index = 0
        self.embed_field_index = 0
        self.mode: Literal["editor", "select"] = "select"
        self.global_data = global_data
        self.skin_selected = ""
        self.message_data = {}
        self.update_components()

    def disable_buttons(self):
        for c in self.children:
            if c.custom_id != "skin_editor_placeholders":
                c.disabled = True

    async def new_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.message_data = deepcopy(base_skin)
        self.mode = "editor"
        self.update_components()
        await self.update_message(inter)

    async def _refuse_skin(self, reply, guild_id: int, error: SchemaError, text: str):
        """Não grava nada: avisa o dono e deixa no log só o servidor e o código da falha."""
        logger.warning("Skin do editor não salva: servidor %s, motivo %s", guild_id, error.code)
        await reply.edit_original_message(text, view=None)

    async def load_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        selected = inter.values[0]

        if selected.startswith("> cs: "):
            mode, name = "custom_skins", selected[6:]
        elif selected.startswith("> css: "):
            mode, name = "custom_skins_static", selected[7:]
        else:
            mode = name = None

        message_data = deepcopy(base_skin)

        if mode:
            skins = await load_custom_skins(self.bot, self.guild.id, self.global_data)
            readable = skins.normal if mode == "custom_skins" else skins.static
            if name in readable:
                message_data = readable[name]
            elif self.global_data[mode][name]:
                await inter.send("**Esta skin está em um formato incompatível e não pôde ser aberta.**", ephemeral=True)
                return

        self.skin_selected = selected
        self.mode = "editor"
        self.message_data = message_data
        self.update_components()
        await self.update_message(inter)

    def update_components(self):
        self.clear_items()

        if self.mode == "select":
            add_skin_prefix = lambda d: [f"> cs: {i}" for i in d.keys()]
            skins_opts = [
                disnake.SelectOption(emoji="💠", label=f"Modo normal: {s.replace('> cs: ', '', 1)}", value=s)
                for s in add_skin_prefix(self.global_data["custom_skins"])
            ]
            add_skin_prefix = lambda d: [f"> css: {i}" for i in d.keys()]
            static_skins_opts = [
                disnake.SelectOption(emoji="💠", label=f"Song-Request: {s.replace('> css: ', '', 1)}", value=s)
                for s in add_skin_prefix(self.global_data["custom_skins_static"])
            ]

            has_skins = False

            if skins_opts:
                skin_select = disnake.ui.Select(
                    min_values=1, max_values=1, options=skins_opts, placeholder="Skins do modo normal do player"
                )
                skin_select.callback = self.load_skin
                self.add_item(skin_select)
                has_skins = True

            if static_skins_opts:
                static_skin_select = disnake.ui.Select(
                    min_values=1,
                    max_values=1,
                    options=static_skins_opts,
                    placeholder="Skins do modo song-request do player",
                )
                static_skin_select.callback = self.load_skin
                self.add_item(static_skin_select)
                has_skins = True

            if not has_skins:
                self.message_data = {
                    "embeds": [
                        {
                            "description": "**Não há skins salvas...\nClique no botão abaixo para criar uma nova skin/template.**",
                            "color": self.guild.me.color.value,
                        }
                    ]
                }
                new_skin_btn = disnake.ui.Button(
                    label="Adicionar nova skin",
                    custom_id="skin_editor_new_skin",
                    disabled=len(static_skins_opts) > 2 and len(skins_opts) > 2,
                )
                new_skin_btn.callback = self.new_skin
                self.add_item(new_skin_btn)
            else:
                self.message_data = {
                    "embeds": [
                        {
                            "description": "**Selecione uma skin abaixo para editá-la ou crie uma nova usando um modelo base clicando no botão de adicionar abaixo.**",
                            "color": self.guild.me.color.value,
                        }
                    ]
                }
                new_skin_btn = disnake.ui.Button(
                    label="Adicionar nova skin",
                    custom_id="skin_editor_new_skin",
                    disabled=len(static_skins_opts) > 2 and len(skins_opts) > 2,
                )
                new_skin_btn.callback = self.new_skin
                self.add_item(new_skin_btn)

        elif self.mode == "editor":
            if embeds := self.message_data.get("embeds"):
                select_embed = disnake.ui.Select(
                    min_values=1,
                    max_values=1,
                    options=[
                        disnake.SelectOption(
                            label=f"Embed {n + 1}", value=f"skin_embed_{n}", default=n == self.embed_index
                        )
                        for n, e in enumerate(embeds)
                    ],
                )

                select_embed.callback = self.embed_select_callback
                self.add_item(select_embed)

                if fields := embeds[self.embed_index].get("fields", []):
                    select_embed_field = disnake.ui.Select(
                        min_values=1,
                        max_values=1,
                        options=[
                            disnake.SelectOption(
                                label=f"Field {n + 1}",
                                value=f"skin_embed_field_{n}",
                                default=n == self.embed_field_index,
                            )
                            for n, e in enumerate(fields)
                        ],
                    )
                    select_embed_field.callback = self.embed_value_select_callback
                    self.add_item(select_embed_field)

                if len(fields) < 25:
                    add_field_btn = disnake.ui.Button(label="Adicionar Field", emoji="🔖")
                    add_field_btn.callback = self.add_field
                    self.add_item(add_field_btn)

                if fields:
                    edit_field_btn = disnake.ui.Button(label="Editar Field", emoji="🔖")
                    edit_field_btn.callback = self.edit_embed_field_button
                    self.add_item(edit_field_btn)

                    delete_field_btn = disnake.ui.Button(label="Remover Field", emoji="🔖")
                    delete_field_btn.callback = self.delete_embed_field_button
                    self.add_item(delete_field_btn)

                edit_embed_btn = disnake.ui.Button(label="Editar Embed", emoji="📋")
                edit_embed_btn.callback = self.edit_embed_button
                self.add_item(edit_embed_btn)

                remove_embed_btn = disnake.ui.Button(label="Remover Embed", emoji="📋")
                remove_embed_btn.callback = self.remove_embed
                self.add_item(remove_embed_btn)

                set_author_footer_btn = disnake.ui.Button(label="Embed Author + Footer", emoji="👤")
                set_author_footer_btn.callback = self.set_author_footer
                self.add_item(set_author_footer_btn)

            edit_content_btn = disnake.ui.Button(
                label=("Adicionar" if not self.message_data.get("content") else "Editar") + " Mensagem", emoji="💬"
            )
            edit_content_btn.callback = self.edit_content
            self.add_item(edit_content_btn)

            add_embed_btn = disnake.ui.Button(label="Adicionar Embed", disabled=len(embeds) >= 8, emoji="📋")
            add_embed_btn.callback = self.add_embed
            self.add_item(add_embed_btn)

            setup_queue_btn = disnake.ui.Button(label="Configurar placeholder da fila", emoji="📑")
            setup_queue_btn.callback = self.setup_queue
            self.add_item(setup_queue_btn)

            save_disabled = not embeds and len(self.message_data.get("content", "")) < 15

            export_btn = disnake.ui.Button(label="Exportar Skin", emoji="📤", disabled=save_disabled)
            export_btn.callback = self.export
            self.add_item(export_btn)

            import_btn = disnake.ui.Button(label="Importar Skin", emoji="📥")
            import_btn.callback = self.import_
            self.add_item(import_btn)

            if self.skin_selected:
                delete_skin_btn = disnake.ui.Button(label="Excluir Skin", emoji="🚮")
                delete_skin_btn.callback = self.delete_skin
                self.add_item(delete_skin_btn)

            back_btn = disnake.ui.Button(label="Voltar ao menu anterior", emoji="⬅️")
            back_btn.callback = self.back
            self.add_item(back_btn)

            self.add_item(
                disnake.ui.Button(label="Lista de placeholders", emoji="❓", custom_id="skin_editor_placeholders")
            )

            save_btn = disnake.ui.Button(label="Salvar Skin", emoji="💾", disabled=save_disabled)
            save_btn.callback = self.save
            self.add_item(save_btn)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.ctx.author.id:
            await inter.send(
                f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.disable_buttons()

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

    def build_embeds(self) -> dict:
        player = None
        for b in self.bot.pool.get_guild_bots(self.ctx.guild_id):
            try:
                player = b.music.players[self.ctx.guild_id]
                break
            except KeyError:
                continue

        data = skin_converter(self.message_data, guild=self.guild, ctx=self.ctx, player=player)
        return {"content": data.get("content", ""), "embeds": data.get("embeds", [])}

    async def embed_select_callback(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.embed_index = int(inter.values[0][11:])
        await inter.response.defer()

    async def embed_value_select_callback(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.embed_field_index = int(inter.values[0][17:])
        await inter.response.defer()

    async def edit_content(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Editar/Adicionar conteúdo da mensagem",
                custom_id="skin_editor_message_content",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Mensagem:",
                        custom_id="message_content",
                        value=self.message_data.get("content", ""),
                        max_length=1700,
                        required=False,
                    ),
                ],
            )
        )

    async def add_embed(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Adicionar Embed",
                custom_id="skin_editor_add_embed",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Título da embed:",
                        custom_id="skin_embed_title",
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Descrição da embed:",
                        custom_id="skin_embed_description",
                        max_length=1700,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Cor da embed:",
                        placeholder="Exemplo: #000fff ou {guild.color}",
                        custom_id="skin_embed_color",
                        max_length=15,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da imagem:",
                        custom_id="image_url",
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da miniatura:",
                        custom_id="thumbnail_url",
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def edit_embed_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        embed = self.message_data["embeds"][self.embed_index]

        try:
            image_url = embed["image"]["url"]
        except KeyError:
            image_url = ""

        try:
            thumb_url = embed["thumbnail"]["url"]
        except KeyError:
            thumb_url = ""

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Edite os campos principais da embed",
                custom_id="skin_editor_edit_embed",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Título da embed:",
                        custom_id="skin_embed_title",
                        value=embed.get("title", ""),
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Descrição da embed:",
                        custom_id="skin_embed_description",
                        value=embed.get("description", ""),
                        max_length=1700,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Cor da embed:",
                        placeholder="Exemplo: #000fff ou {guild.color}",
                        custom_id="skin_embed_color",
                        value=str(embed.get("color", "")),
                        max_length=14,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da imagem:",
                        custom_id="image_url",
                        value=image_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da miniatura:",
                        custom_id="thumbnail_url",
                        value=thumb_url,
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def remove_embed(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        del self.message_data["embeds"][self.embed_index]
        self.embed_index = 0
        self.update_components()
        await inter.response.edit_message(view=self, **self.build_embeds())

    async def add_field(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Adicionar field na embed",
                custom_id="skin_editor_add_field",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome:",
                        custom_id="add_field_name",
                        max_length=170,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Valor/Texto:",
                        custom_id="add_field_value",
                        max_length=1700,
                        required=True,
                    ),
                ],
            )
        )

    async def edit_embed_field_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        field = self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index]

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Edição dos campos principais da embed",
                custom_id="skin_editor_edit_field",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome do campo:",
                        custom_id="edit_field_name",
                        value=field["name"],
                        max_length=170,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Valor/Texto do campo:",
                        custom_id="edit_field_value",
                        value=field["value"],
                        max_length=1700,
                        required=True,
                    ),
                ],
            )
        )

    async def delete_embed_field_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        del self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index]
        self.embed_field_index = 0
        self.update_components()
        await inter.response.edit_message(view=self, **self.build_embeds())

    async def set_author_footer(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        try:
            author_name = self.message_data["embeds"][self.embed_index]["author"]["name"]
        except KeyError:
            author_name = ""

        try:
            author_url = self.message_data["embeds"][self.embed_index]["author"]["url"]
        except KeyError:
            author_url = ""

        try:
            author_icon_url = self.message_data["embeds"][self.embed_index]["author"]["icon_url"]
        except KeyError:
            author_icon_url = ""

        try:
            footer_text = self.message_data["embeds"][self.embed_index]["footer"]["text"]
        except KeyError:
            footer_text = ""

        try:
            footer_icon_url = self.message_data["embeds"][self.embed_index]["footer"]["icon_url"]
        except KeyError:
            footer_icon_url = ""

        await inter.response.send_modal(
            ViewModal(
                view=self,
                custom_id="skin_editor_set_authorfooter",
                title="Adicionar/editar autor/footer",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome do author:",
                        custom_id="set_author_name",
                        value=author_name,
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Url do author:",
                        custom_id="set_author_url",
                        value=author_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Url da imagem do author:",
                        custom_id="set_author_icon",
                        value=author_icon_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Texto do footer:",
                        custom_id="footer_text",
                        value=footer_text,
                        max_length=1700,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="URL/Link da imagem do footer:",
                        custom_id="footer_icon_url",
                        value=footer_icon_url,
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def setup_queue(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Placeholder da lista de músicas da fila",
                custom_id="skin_editor_setup_queue",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Formatação de texto no nome das músicas:",
                        custom_id="queue_format",
                        value=self.message_data["queue_format"],
                        max_length=120,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Quantidade de músicas exibidas na lista:",
                        custom_id="queue_max_entries",
                        value=str(self.message_data["queue_max_entries"]),
                        max_length=2,
                        required=True,
                    ),
                ],
            )
        )

    async def export(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        fp = BytesIO(bytes(json.dumps(self.message_data, indent=4), "utf-8"))
        await inter.response.send_message(file=disnake.File(fp=fp, filename="skin.json"), ephemeral=True)

    async def import_(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Importar skin",
                custom_id="skin_editor_import_skin",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Código da skin (json):",
                        custom_id="skin",
                        max_length=2000,
                        required=True,
                    )
                ],
            )
        )

    async def save(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Informe o nome da skin",
                custom_id="skin_editor_save",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome:",
                        custom_id="skin_name",
                        value=self.skin_selected.replace("> css: ", "", 1).replace("> cs: ", "", 1),
                        max_length=15,
                        required=True,
                    )
                ],
            )
        )

    async def delete_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.defer()

        self.global_data = await self.bot.get_global_data(id_=inter.guild_id, db_name=DBModel.guilds)

        if self.skin_selected.startswith("> cs:"):
            try:
                del self.global_data["custom_skins"][self.skin_selected[6:]]
            except KeyError:
                await inter.send(f"**A skin {self.skin_selected[6:]} não existe mais na database...**", ephemeral=True)
                return

        elif self.skin_selected.startswith("> css:"):
            try:
                del self.global_data["custom_skins_static"][self.skin_selected[7:]]
            except KeyError:
                await inter.send(f"**A skin {self.skin_selected[7:]} não existe mais na database...**", ephemeral=True)
                return

        await self.bot.update_global_data(id_=inter.guild_id, data=self.global_data, db_name=DBModel.guilds)

        self.mode = "select"
        self.skin_selected = ""
        self.update_components()

        await inter.edit_original_message(view=self, **self.build_embeds())

    async def back(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.mode = "select"
        self.skin_selected = ""
        self.message_data = {}
        self.update_components()
        await self.update_message(inter)

    async def update_message(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        try:
            if isinstance(self.ctx, CustomContext):
                await inter.response.edit_message(view=self, **self.build_embeds())
            elif not inter.response.is_done():
                await inter.response.edit_message(view=self, **self.build_embeds())
            else:
                await inter.edit_original_message(view=self, **self.build_embeds())
        except Exception as e:
            code = log_unexpected_error(logger, e, "editor de skin: atualização da mensagem")
            await inter.send("**Ocorreu um erro ao processar a mensagem.**" + error_code_text(code), ephemeral=True)

    async def modal_handler(self, inter: disnake.ModalInteraction):
        if inter.custom_id == "skin_editor_message_content":
            self.ctx = inter
            self.message_data["content"] = inter.text_values["message_content"]

        elif inter.custom_id == "skin_editor_add_embed":
            self.ctx = inter

            e = (
                disnake.Embed(
                    title=inter.text_values["skin_embed_title"],
                    description=inter.text_values["skin_embed_description"],
                )
                .set_image(url=inter.text_values["image_url"])
                .set_thumbnail(inter.text_values["thumbnail_url"])
                .to_dict()
            )

            e["color"] = inter.text_values["skin_embed_color"].strip("#")

            self.message_data["embeds"].append(e)
            self.embed_index = len(self.message_data["embeds"]) - 1

        elif inter.custom_id == "skin_editor_edit_embed":
            self.ctx = inter

            self.message_data["embeds"][self.embed_index]["title"] = inter.text_values["skin_embed_title"]
            self.message_data["embeds"][self.embed_index]["description"] = inter.text_values["skin_embed_description"]

            if not inter.text_values["image_url"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["image"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["image"] = {"url": inter.text_values["image_url"]}

            if not inter.text_values["thumbnail_url"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["thumbnail"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["thumbnail"] = {"url": inter.text_values["thumbnail_url"]}

            self.message_data["embeds"][self.embed_index]["color"] = inter.text_values["skin_embed_color"].strip("#")

        elif inter.custom_id == "skin_editor_add_field":
            self.ctx = inter

            if not self.message_data["embeds"][self.embed_index].get("fields"):
                self.message_data["embeds"][self.embed_index]["fields"] = [
                    {"name": inter.text_values["add_field_name"], "value": inter.text_values["add_field_value"]}
                ]
            else:
                self.message_data["embeds"][self.embed_index]["fields"].append(
                    {"name": inter.text_values["add_field_name"], "value": inter.text_values["add_field_value"]}
                )

            self.embed_field_index = len(self.message_data["embeds"][self.embed_index]["fields"]) - 1

        elif inter.custom_id == "skin_editor_edit_field":
            self.ctx = inter
            self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index] = {
                "name": inter.text_values["edit_field_name"],
                "value": inter.text_values["edit_field_value"],
            }

        elif inter.custom_id == "skin_editor_set_authorfooter":
            self.ctx = inter

            if not inter.text_values["footer_text"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["footer"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["footer"] = {
                    "text": inter.text_values["footer_text"],
                    "icon_url": inter.text_values["footer_icon_url"],
                }

            if not inter.text_values["set_author_name"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["author"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["author"] = {
                    "name": inter.text_values["set_author_name"],
                    "url": inter.text_values["set_author_url"],
                    "icon_url": inter.text_values["set_author_icon"],
                }

        elif inter.custom_id == "skin_editor_setup_queue":
            self.ctx = inter
            self.message_data["queue_format"] = inter.text_values["queue_format"]
            try:
                self.message_data["queue_max_entries"] = int(inter.text_values["queue_max_entries"])
            except TypeError:
                pass

        elif inter.custom_id == "skin_editor_import_skin":
            self.ctx = inter

            try:
                info = json.loads(inter.text_values["skin"])
            except (ValueError, RecursionError):
                logger.exception("Editor de skin: JSON inválido na importação")
                await inter.send(
                    "**Ocorreu um erro ao processar sua skin: confira se o conteúdo é um JSON válido.**",
                    ephemeral=True,
                )
                return

            try:
                if len(str(info["queue_max_entries"])) > 2:
                    info["queue_max_entries"] = 7
            except Exception:
                pass

            try:
                if not isinstance(info["queue_format"], str):
                    info["queue_format"] = self.message_data["queue_format"]
            except KeyError:
                pass

            try:
                self.message_data["embeds"] = info["embeds"]
            except KeyError:
                pass
            try:
                self.message_data["content"] = info["content"]
            except KeyError:
                pass
            try:
                self.message_data["queue_format"] = info["queue_format"]
            except KeyError:
                pass
            try:
                self.message_data["queue_max_entries"] = info["queue_max_entries"]
            except KeyError:
                pass

            self.embed_index = 0
            self.embed_field_index = 0

        elif inter.custom_id == "skin_editor_save":
            view = SkinSettingsButton(self.ctx.author, timeout=30)
            view.controller_enabled = self.message_data.get("controller_enabled", True)
            await inter.send("**Selecione o modo de player que será aplicado na skin.**", view=view, ephemeral=True)
            await view.wait()

            if view.mode is None:
                await inter.edit_original_message("Tempo esgotado!", components=[])
                return

            self.message_data["controller_enabled"] = view.controller_enabled

            if view.inter:
                await view.inter.response.defer(ephemeral=True)

            self.global_data = await self.bot.get_global_data(self.ctx.guild_id, db_name=DBModel.guilds)

            skin_name = self.skin_selected.replace("> css: ", "", 1).replace("> cs: ", "", 1)

            try:
                modal_skin_name = validate_skin_name(inter.text_values["skin_name"])
            except SchemaError as error:
                await self._refuse_skin(view.inter or inter, inter.guild_id, error, SKIN_NAME_REFUSED)
                return

            try:
                new_skin = validate_skin(self.message_data)
            except SchemaError as error:
                await self._refuse_skin(view.inter or inter, inter.guild_id, error, SKIN_REFUSED)
                return

            names = set(self.global_data[view.mode])
            if modal_skin_name != skin_name:
                names.discard(skin_name)
            names.add(modal_skin_name)
            if len(names) > MAX_SKINS_PER_MODE:
                await self._refuse_skin(
                    view.inter or inter, inter.guild_id, SchemaError("", "length"), SKIN_LIMIT_REFUSED
                )
                return

            await load_custom_skins(self.bot, inter.guild_id, self.global_data)  # migra as legadas antes de gravar

            if modal_skin_name != skin_name:
                self.global_data[view.mode].pop(skin_name, None)

            self.global_data[view.mode][modal_skin_name] = new_skin

            await self.bot.update_global_data(id_=inter.guild_id, data=self.global_data, db_name=DBModel.guilds)

            for bot in self.bot.pool.get_guild_bots(inter.guild_id):
                try:
                    player = bot.music.players[inter.guild_id]
                except KeyError:
                    continue

                skins = await load_custom_skins(self.bot, inter.guild_id, self.global_data)

                player.custom_skin_data = skins.normal
                player.custom_skin_static_data = skins.static
                player.setup_features()
                player.setup_hints()
                player.process_hint()

            try:
                cmd = (
                    f"</change_skin:"
                    + str(
                        self.bot.get_global_command_named(
                            "change_skin", cmd_type=disnake.ApplicationCommandType.chat_input
                        ).id
                    )
                    + ">"
                )
            except AttributeError:
                cmd = "/change_skin"

            try:
                guild_prefix = self.bot.pool.guild_prefix_cache[self.ctx.guild_id]
            except KeyError:
                guild_prefix = self.global_data.get("prefix")

            if not guild_prefix:
                guild_prefix = self.bot.config.get("DEFAULT_PREFIX") or "!!"

            if not view.inter:
                view.inter = inter

            await view.inter.edit_original_message(
                "**A skin foi salva/editada com sucesso!**\n"
                f"Você pode aplicá-la usando o comando {cmd} ou {guild_prefix}skin",
                view=None,
            )

            self.skin_selected = ("> cs: " if view.mode == "custom_skins" else "> css: ") + modal_skin_name

            self.update_components()

            if isinstance(self.ctx, CustomContext):
                await self.message.edit(view=self, **self.build_embeds())
            else:
                await self.ctx.edit_original_message(view=self, **self.build_embeds())
            return

        self.update_components()
        await self.update_message(inter)

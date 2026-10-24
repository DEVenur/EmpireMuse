# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from io import BytesIO

import disnake

from empiremuse.utils.music.interactions.view_modal import (
    ViewModal,
)


def _nested_text(data: dict, *keys: str) -> str:
    """Lê ``data[k1][k2]...``; devolve ``""`` se alguma chave faltar."""
    try:
        for key in keys:
            data = data[key]
    except KeyError:
        return ""
    return data


class SkinEditorModalsMixin:
    """Callbacks dos botões do editor que abrem modais (ou exportam) a partir do estado atual da skin."""

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

        image_url = _nested_text(embed, "image", "url")
        thumb_url = _nested_text(embed, "thumbnail", "url")

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

        embed = self.message_data["embeds"][self.embed_index]
        author_name = _nested_text(embed, "author", "name")
        author_url = _nested_text(embed, "author", "url")
        author_icon_url = _nested_text(embed, "author", "icon_url")
        footer_text = _nested_text(embed, "footer", "text")
        footer_icon_url = _nested_text(embed, "footer", "icon_url")

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

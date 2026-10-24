# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import disnake

from empiremuse.utils.music.interactions.common import (
    logger,
)

# Máximo de dígitos aceito em `queue_max_entries` numa skin importada; acima disso volta ao padrão.
IMPORT_QUEUE_MAX_ENTRIES_DIGITS = 2
DEFAULT_QUEUE_MAX_ENTRIES = 7
IMPORTED_SKIN_KEYS = ("embeds", "content", "queue_format", "queue_max_entries")


def _set_or_clear(embed: dict, key: str, value: dict | None):
    """Grava ``embed[key]`` ou, se não houver valor, remove a chave (se existir)."""
    if value is None:
        embed.pop(key, None)
        return
    embed[key] = value


class SkinEditorSubmitMixin:
    """Aplica ao estado da skin o que o usuário enviou nos modais do editor."""

    async def modal_handler(self, inter: disnake.ModalInteraction):
        if inter.custom_id == "skin_editor_save":
            await self.save_skin_from_modal(inter)
            return

        applier = self._MODAL_APPLIERS.get(inter.custom_id)

        if inter.custom_id == "skin_editor_import_skin":
            self.ctx = inter
            if not await self._apply_import_skin(inter):
                return

        elif applier:
            self.ctx = inter
            applier(self, inter)

        self.update_components()
        await self.update_message(inter)

    def _apply_message_content(self, inter: disnake.ModalInteraction):
        self.message_data["content"] = inter.text_values["message_content"]

    def _apply_add_embed(self, inter: disnake.ModalInteraction):
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

    def _apply_edit_embed(self, inter: disnake.ModalInteraction):
        embed = self.message_data["embeds"][self.embed_index]

        embed["title"] = inter.text_values["skin_embed_title"]
        embed["description"] = inter.text_values["skin_embed_description"]

        image_url = inter.text_values["image_url"]
        _set_or_clear(embed, "image", {"url": image_url} if image_url else None)

        thumbnail_url = inter.text_values["thumbnail_url"]
        _set_or_clear(embed, "thumbnail", {"url": thumbnail_url} if thumbnail_url else None)

        embed["color"] = inter.text_values["skin_embed_color"].strip("#")

    def _apply_add_field(self, inter: disnake.ModalInteraction):
        embed = self.message_data["embeds"][self.embed_index]
        field = {"name": inter.text_values["add_field_name"], "value": inter.text_values["add_field_value"]}

        if not embed.get("fields"):
            embed["fields"] = [field]
        else:
            embed["fields"].append(field)

        self.embed_field_index = len(embed["fields"]) - 1

    def _apply_edit_field(self, inter: disnake.ModalInteraction):
        self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index] = {
            "name": inter.text_values["edit_field_name"],
            "value": inter.text_values["edit_field_value"],
        }

    def _apply_author_footer(self, inter: disnake.ModalInteraction):
        embed = self.message_data["embeds"][self.embed_index]

        footer_text = inter.text_values["footer_text"]
        _set_or_clear(
            embed,
            "footer",
            {"text": footer_text, "icon_url": inter.text_values["footer_icon_url"]} if footer_text else None,
        )

        author_name = inter.text_values["set_author_name"]
        _set_or_clear(
            embed,
            "author",
            {
                "name": author_name,
                "url": inter.text_values["set_author_url"],
                "icon_url": inter.text_values["set_author_icon"],
            }
            if author_name
            else None,
        )

    def _apply_queue_setup(self, inter: disnake.ModalInteraction):
        self.message_data["queue_format"] = inter.text_values["queue_format"]
        try:
            self.message_data["queue_max_entries"] = int(inter.text_values["queue_max_entries"])
        except TypeError:
            pass

    async def _apply_import_skin(self, inter: disnake.ModalInteraction) -> bool:
        """Importa o JSON enviado; devolve ``False`` se o conteúdo for inválido (nada muda na skin)."""
        try:
            info = json.loads(inter.text_values["skin"])
        except (ValueError, RecursionError):
            logger.exception("Editor de skin: JSON inválido na importação")
            await inter.send(
                "**Ocorreu um erro ao processar sua skin: confira se o conteúdo é um JSON válido.**",
                ephemeral=True,
            )
            return False

        try:
            if len(str(info["queue_max_entries"])) > IMPORT_QUEUE_MAX_ENTRIES_DIGITS:
                info["queue_max_entries"] = DEFAULT_QUEUE_MAX_ENTRIES
        except (KeyError, TypeError):
            pass

        try:
            if not isinstance(info["queue_format"], str):
                info["queue_format"] = self.message_data["queue_format"]
        except KeyError:
            pass

        for key in IMPORTED_SKIN_KEYS:
            try:
                self.message_data[key] = info[key]
            except KeyError:
                pass

        self.embed_index = 0
        self.embed_field_index = 0
        return True

    _MODAL_APPLIERS = {
        "skin_editor_message_content": _apply_message_content,
        "skin_editor_add_embed": _apply_add_embed,
        "skin_editor_edit_embed": _apply_edit_embed,
        "skin_editor_add_field": _apply_add_field,
        "skin_editor_edit_field": _apply_edit_field,
        "skin_editor_set_authorfooter": _apply_author_footer,
        "skin_editor_setup_queue": _apply_queue_setup,
    }

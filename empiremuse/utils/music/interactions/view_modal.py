# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Union, TYPE_CHECKING

import disnake

from empiremuse.utils.music.errors import GenericError

if TYPE_CHECKING:
    from empiremuse.utils.music.interactions import SkinEditorMenu
    from empiremuse.utils.music.interactions.player_views import QueueInteraction


class ViewModal(disnake.ui.Modal):
    def __init__(
        self,
        view: Union[SkinEditorMenu, QueueInteraction],
        title: str,
        components: List[disnake.TextInput],
        custom_id: str,
    ):
        self.view = view
        super().__init__(title=title, components=components, custom_id=custom_id)

    async def callback(self, inter: disnake.ModalInteraction, /) -> None:
        await self.view.modal_handler(inter)

    async def on_error(self, error: Exception, interaction: disnake.ModalInteraction) -> None:
        if not isinstance(error, GenericError):
            await super().on_error(error, interaction)
            return

        await interaction.send(error.text, ephemeral=True)

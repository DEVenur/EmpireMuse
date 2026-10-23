# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Union, TYPE_CHECKING

import disnake


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

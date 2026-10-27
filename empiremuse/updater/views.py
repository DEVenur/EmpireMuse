"""Botões Confirmar/Cancelar do comando ``update``: só quem pediu clica, e a janela fecha em 60 s."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import disnake

logger = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 60

Callback = Callable[[disnake.MessageInteraction], Awaitable[None]]


class ConfirmView(disnake.ui.View):
    """Pede a confirmação do dono. ``on_confirm`` roda uma vez; ``on_close`` roda sempre que a janela acaba sem confirmar.

    ``on_close`` existe para soltar a trava de atualização do pool quando o dono cancela ou deixa expirar.
    """

    def __init__(
        self, requested_by: int, on_confirm: Callback, on_close: Callable[[], None], *, timeout: float = CONFIRM_TIMEOUT
    ) -> None:
        super().__init__(timeout=timeout)
        self.requested_by = requested_by
        self._on_confirm = on_confirm
        self._on_close = on_close
        self._finished = False
        self.message: Any = None

    def _close(self) -> None:
        if not self._finished:
            self._finished = True
            self._on_close()

    def _disable(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        if interaction.author.id != self.requested_by:
            await interaction.send("Só quem pediu a atualização pode confirmar ou cancelar.", ephemeral=True)
            return False
        return True

    @disnake.ui.button(label="Confirmar", style=disnake.ButtonStyle.success, emoji="✅")
    async def confirm(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction) -> None:
        if self._finished:
            return
        self._finished = True  # a trava passa a ser do fluxo de aplicação, que a solta no fim
        self._disable()
        self.stop()
        await self._on_confirm(interaction)

    @disnake.ui.button(label="Cancelar", style=disnake.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction) -> None:
        self._close()
        self._disable()
        self.stop()
        await interaction.response.edit_message(content="Atualização cancelada.", embed=None, view=self)

    async def on_timeout(self) -> None:
        self._close()
        self._disable()
        if self.message is not None:
            try:
                await self.message.edit(content="A confirmação expirou; nada foi alterado.", embed=None, view=self)
            except disnake.HTTPException:
                logger.info("update: não consegui atualizar a mensagem de confirmação expirada")

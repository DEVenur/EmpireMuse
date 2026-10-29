# -*- coding: utf-8 -*-
"""Canal de pedidos único (item 11, P4): a seção ``request`` do documento único e a eleição do bot do painel.

Um canal por servidor para todo o pool. O bot do painel (o principal se está no servidor, senão a 1ª reserva presente) é o ÚNICO que envia,
edita e trata as mensagens do canal. A eleição é decidida DENTRO da trava do servidor, conferindo de novo quem está no servidor (S-V11). Tudo
passa pelo store (``utils/servers``): trava por servidor, ``rev`` +1 e compare-and-set; o painel web e os comandos gravam o mesmo documento.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple, Optional

from empiremuse.rules.request_panel import PanelPeer, elect_panel_bot
from empiremuse.rules.servers import SECTION_REQUEST

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore
    from empiremuse.utils.servers import ServerStore

logger = logging.getLogger(__name__)

SECTIONS = (SECTION_REQUEST,)


class RequestConfig(NamedTuple):
    """O canal de pedidos do servidor. ``panel_bot_id`` é o último bot eleito (``None`` = nunca houve canal)."""

    channel: Optional[int]
    message_id: Optional[int]
    panel_bot_id: Optional[int]
    rev: int


class Election(NamedTuple):
    """Resultado da eleição: o bot do painel agora e se ele MUDOU em relação ao último gravado (quem muda reenvia o painel)."""

    bot: Optional["BotCore"]
    changed: bool


def _as_id(value: object) -> Optional[int]:
    try:
        number = int(value)  # type: ignore[call-overload]
    except TypeError, ValueError:
        return None
    return number if number > 0 else None


def _config(doc: dict) -> RequestConfig:
    request = doc.get(SECTION_REQUEST) or {}
    return RequestConfig(
        _as_id(request.get("channel")),
        _as_id(request.get("message_id")),
        _as_id(request.get("panel_bot_id")),
        int(doc.get("rev", 0)),
    )


class ServerRequest:
    def __init__(self, store: ServerStore) -> None:
        self.store = store

    # ------------------------------------------------------------------ leitura

    async def get(self, gid: int) -> RequestConfig:
        return _config(await self.store.get_sections(gid, *SECTIONS))

    # ------------------------------------------------------------------ escrita

    async def set(
        self, gid: int, channel_id: Optional[int], message_id: Optional[int], *, expected_rev: Optional[int] = None
    ) -> RequestConfig:
        """Grava canal e mensagem juntos (``None`` limpa) sob a trava; sem canal, sem mensagem."""
        channel = str(channel_id) if channel_id else None
        message = str(message_id) if channel and message_id else None

        def apply(doc: dict) -> bool:
            before = dict(doc[SECTION_REQUEST])
            doc[SECTION_REQUEST].update({"channel": channel, "message_id": message})
            return doc[SECTION_REQUEST] != before

        return _config(await self.store.mutate_doc(gid, SECTIONS, apply, expected_rev=expected_rev))

    async def clear(self, gid: int, *, expected_rev: Optional[int] = None) -> RequestConfig:
        return await self.set(gid, None, None, expected_rev=expected_rev)

    # ------------------------------------------------------------------ o bot do painel

    def peers(self, gid: int) -> list[PanelPeer]:
        """Os bots do pool que estão no servidor agora (bot exclusivo de OUTRO servidor não conta)."""
        found = []
        for bot in self.store.pool.get_all_bots():
            exclusive = getattr(bot, "exclusive_guild_id", None)
            if bot.user is None or bot.get_guild(gid) is None or (exclusive and exclusive != gid):
                continue
            found.append(PanelPeer(bot.identifier, bot.user.id, bool(exclusive)))
        return found

    def _bot_by_id(self, bot_id: Optional[int]) -> Optional[BotCore]:
        return next((b for b in self.store.pool.get_all_bots() if b.user is not None and b.user.id == bot_id), None)

    def elected_id(self, gid: int) -> Optional[int]:
        """Quem seria o bot do painel olhando só quem está no servidor agora (sem banco)."""
        return elect_panel_bot(self.peers(gid))

    async def elect(self, gid: int) -> Election:
        """Elege o bot do painel DENTRO da trava (conferindo de novo quem está no servidor) e grava a mudança."""
        outcome: dict = {}

        def apply(doc: dict) -> bool:
            elected = elect_panel_bot(
                self.peers(gid)
            )  # conferido aqui dentro: o que valeu fora da trava pode ter mudado
            stored = doc[SECTION_REQUEST].get("panel_bot_id")
            new = None if elected is None else str(elected)
            outcome["elected"] = elected
            outcome["changed"] = stored != new
            if stored == new:
                return False
            doc[SECTION_REQUEST]["panel_bot_id"] = new
            return True

        await self.store.mutate_doc(gid, SECTIONS, apply)
        return Election(self._bot_by_id(outcome["elected"]), bool(outcome["changed"]))

    async def panel_bot(self, gid: int) -> Optional[BotCore]:
        """O bot do painel do servidor (grava a eleição se mudou). ``None`` se nenhum bot do pool está no servidor."""
        elected = self.elected_id(gid)
        if elected is None:
            return None
        if (await self.get(gid)).panel_bot_id != elected:
            return (await self.elect(gid)).bot
        return self._bot_by_id(elected)

    async def is_panel_bot(self, gid: int, bot: BotCore) -> bool:
        """``bot`` é o bot do painel? Quem não foi eleito pela presença responde sem tocar no banco."""
        if bot.user is None or self.elected_id(gid) != bot.user.id:
            return False
        if (await self.get(gid)).panel_bot_id != bot.user.id:
            await self.elect(gid)
        return True

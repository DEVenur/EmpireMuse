# -*- coding: utf-8 -*-
"""Servidores banidos pelo dono: lista persistida, cópia em memória e a saída dos bots do pool.

A lista fica na coleção ``banned_guilds`` do banco global (um documento por servidor: nome no momento do ban, data e motivo) e uma
cópia em memória responde ``is_banned`` na hora, sem I/O, para os tratadores de entrada em servidor. Quem pode banir é decidido por
quem chama (o painel ``servers``, restrito ao dono); aqui só há a mecânica.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from empiremuse.rules.usage import (
    MS_PER_SECOND,
    BanRecord,
    ban_from_doc,
    ban_to_doc,
    guilds_to_leave,
    new_ban_record,
    should_leave,
)
from empiremuse.utils.db import DBModel

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore, BotPool

logger = logging.getLogger(__name__)

BANS_DB = "global"


class GuildBans:
    def __init__(self, pool: BotPool) -> None:
        self.pool = pool
        self._records: dict[int, BanRecord] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def is_banned(self, guild_id: int) -> bool:
        return should_leave(guild_id, self._records)

    def records(self) -> list[BanRecord]:
        """Os banimentos, do mais recente para o mais antigo."""
        return sorted(self._records.values(), key=lambda record: (record.banned_at, record.guild_id), reverse=True)

    async def ensure_loaded(self) -> None:
        """Carrega a lista do banco uma vez; se o banco falhar, avisa e tenta de novo na próxima chamada."""
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            try:
                documents = await self.pool.database.query_data(DBModel.banned_guilds, BANS_DB)
                loaded = {}
                for document in documents:
                    if (record := ban_from_doc(document)) is not None:
                        loaded[record.guild_id] = record
            except Exception as exc:  # noqa: BLE001 - sem a lista o bot segue; os banimentos valem quando o banco voltar
                logger.warning("Lista de servidores banidos não carregada (%s)", type(exc).__name__)
                return
            self._records = loaded
            self._loaded = True

    async def ban(self, guild_id: int, name: object, reason: object) -> BanRecord:
        """Grava o banimento (o erro do banco sobe: o dono precisa saber que não valeu) e só então guarda em memória."""
        await self.ensure_loaded()
        record = new_ban_record(guild_id, name, reason, int(time.time() * MS_PER_SECOND))
        await self.pool.database.update_data(
            guild_id, ban_to_doc(record), db_name=DBModel.banned_guilds, collection=BANS_DB
        )
        self._records[record.guild_id] = record
        return record

    async def unban(self, guild_id: int) -> bool:
        await self.ensure_loaded()
        if guild_id not in self._records:
            return False
        await self.pool.database.delete_data(guild_id, DBModel.banned_guilds, BANS_DB)
        del self._records[guild_id]
        return True

    async def _leave(self, bot: BotCore, guild: Any) -> bool:
        try:
            await guild.leave()
        except Exception as exc:  # noqa: BLE001 - um bot que falha não impede os outros
            logger.warning("Bot %s não saiu do servidor banido [%s] (%s)", bot.identifier, guild.id, type(exc).__name__)
            return False
        return True

    async def leave_everywhere(self, guild_id: int) -> int:
        """Todos os bots do pool saem do servidor; devolve quantos saíram."""
        left = 0
        for bot in self.pool.get_all_bots():
            if (guild := bot.get_guild(guild_id)) is not None and await self._leave(bot, guild):
                left += 1
        return left

    async def enforce_join(self, bot: BotCore, guild: Any) -> bool:
        """Entrou em um servidor banido? Sai na hora, com uma linha de log. ``True`` quando o servidor é banido."""
        await self.ensure_loaded()
        if not self.is_banned(guild.id):
            return False
        logger.info("Servidor banido tentou readicionar o bot %s [%s]; saindo.", bot.identifier, guild.id)
        await self._leave(bot, guild)
        return True

    async def enforce_ready(self, bot: BotCore) -> int:
        """Ao ficar pronto: sai de todo servidor banido em que o bot ainda está. Devolve quantos."""
        await self.ensure_loaded()
        left = 0
        for guild_id in guilds_to_leave((guild.id for guild in bot.guilds), self._records):
            if (guild := bot.get_guild(guild_id)) is None:
                continue
            logger.info("Bot %s está em servidor banido [%s]; saindo.", bot.identifier, guild_id)
            if await self._leave(bot, guild):
                left += 1
        return left


def bans_of(owner: object) -> GuildBans | None:
    """A lista de banidos do pool de um bot ou do próprio pool; ``None`` se não houver (fakes de teste)."""
    pool = getattr(owner, "pool", owner)
    bans = getattr(pool, "guild_bans", None)
    return bans if isinstance(bans, GuildBans) else None

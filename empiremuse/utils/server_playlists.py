# -*- coding: utf-8 -*-
"""Playlists do servidor (item 17): a seção ``playlists`` do documento único, a mesma lista para todos os bots do pool.

``pool.servers.playlists`` lê e grava SÓ pelo store (``utils/servers``): trava por servidor, ``rev`` +1 a cada escrita e compare-and-set
no MongoDB. Validação e decisões são de ``rules/playlists``. Toda escrita que muda a lista atualiza o embed ocioso dos bots do servidor
em segundo plano (falha só vai para o log). Quem chama decide a permissão (``may_manage``) antes de gravar.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

import disnake

from empiremuse.rules.errors import RuleError
from empiremuse.rules.limits import MAX_SERVER_PLAYLISTS
from empiremuse.rules.playlists import (
    ImportReport,
    ParsedFile,
    Playlist,
    add_item,
    check_playlist,
    edit_item,
    find_item,
    from_doc,
    plan_import,
    remove_item,
    select_description,
    sorted_by_order,
    to_doc,
    to_export,
)
from empiremuse.rules.servers import SECTION_PLAYLISTS
from empiremuse.utils.db import DBModel

if TYPE_CHECKING:
    from empiremuse.utils.servers import ServerStore

logger = logging.getLogger(__name__)

SECTIONS = (SECTION_PLAYLISTS,)


def _items(doc: dict) -> tuple[Playlist, ...]:
    """As playlists gravadas, relidas com as mesmas regras e por ``order`` (dado gravado ruim é ignorado, nunca levanta)."""
    return sorted_by_order(item for raw in doc.get("playlists", []) if (item := from_doc(raw)) is not None)


def _validated(item: Playlist) -> Playlist | RuleError:
    """O item revalidado: nada chega ao banco sem passar pelas regras, venha de onde vier (``icon`` só de arquivo do bot)."""
    checked = check_playlist(item._asdict(), allow_icon=False, default_order=item.order)
    return checked if isinstance(checked, RuleError) else checked._replace(order=item.order)


def select_options(
    bot, playlists: tuple[Playlist, ...], limit: int = MAX_SERVER_PLAYLISTS
) -> list[disnake.SelectOption]:
    """As primeiras ``limit`` playlists por ordem como opções de select (o Discord aceita 25): nome, descrição cortada e o emoji da plataforma.

    O ``value`` é o nome; quem trata a escolha o resolve de novo no store, nunca confia no valor recebido.
    """
    from empiremuse.utils.others import music_source_emoji_url  # tarde: utils.others importa muita coisa

    return [
        disnake.SelectOption(
            label=p.name,
            value=p.name,
            description=select_description(p.description) or None,
            emoji=music_source_emoji_url(p.url, bot)[0],
        )
        for p in playlists[:limit]
    ]


async def safe_list(bot, gid: int) -> tuple[Playlist, ...]:
    """As playlists do servidor para EXIBIR (embed ocioso, select, menu): store indisponível ou servidor desconhecido = lista vazia."""
    from empiremuse.utils.servers import (  # tarde: servers cria o ServerPlaylists
        ServerConfigConflict,
        ServerConfigUnavailable,
        UnknownGuild,
    )

    try:
        return await bot.pool.servers.playlists.list(gid)
    except ServerConfigUnavailable, ServerConfigConflict, UnknownGuild:
        return ()


async def load_select_options(bot, gid: int) -> list[disnake.SelectOption]:
    """As opções do select de playlists do servidor; sem playlists, ou com o store indisponível, a lista vazia (o select some)."""
    return select_options(bot, await safe_list(bot, gid))


class ServerPlaylists:
    def __init__(self, store: ServerStore) -> None:
        self.store = store
        self._refresh_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ leitura

    async def snapshot(self, gid: int) -> tuple[tuple[Playlist, ...], int]:
        """As playlists por ``order`` e o ``rev`` do documento (o painel leva o ``rev`` no formulário e o devolve ao gravar)."""
        doc = await self.store.get_sections(gid, *SECTIONS)
        return _items(doc), int(doc["rev"])

    async def list(self, gid: int) -> tuple[Playlist, ...]:
        return (await self.snapshot(gid))[0]

    async def ver(self, gid: int) -> int:
        return (await self.snapshot(gid))[1]

    async def find(self, gid: int, name: str) -> Playlist | None:
        """A playlist pelo nome (``casefold``), ou ``None``."""
        return find_item(await self.list(gid), name)

    async def export_bytes(self, gid: int) -> bytes:
        """O formato novo (sem ``icon``): ``ensure_ascii=False``, indentação 2."""
        return json.dumps(to_export(await self.list(gid)), ensure_ascii=False, indent=2).encode("utf-8")

    # ------------------------------------------------------------------ escrita

    async def _write(
        self,
        gid: int,
        change: Callable[[tuple[Playlist, ...]], tuple[Playlist, ...] | RuleError],
        expected_rev: Optional[int],
    ) -> tuple[Any, tuple[Playlist, ...]]:
        """Roda ``change(lista) -> nova lista | RuleError`` sob a trava; grava só se a lista mudou e então atualiza o embed ocioso."""
        outcome: dict[str, Any] = {"result": None, "changed": False}

        def apply(doc: dict) -> bool:
            current = _items(doc)
            result = change(current)
            outcome["result"] = result
            if isinstance(result, RuleError) or tuple(result) == current:
                return False
            outcome["changed"] = True
            doc["playlists"] = [to_doc(p) for p in result]
            return True

        written = await self.store.mutate_doc(gid, SECTIONS, apply, expected_rev=expected_rev)
        if outcome["changed"]:
            self.refresh_idle(gid)  # só depois de gravar
        result = outcome["result"]
        return result, (() if isinstance(result, RuleError) else _items(written))

    async def add(self, gid: int, item: Playlist, expected_rev: Optional[int] = None) -> Playlist | RuleError:
        checked = _validated(item)
        if isinstance(checked, RuleError):
            return checked
        result, items = await self._write(gid, lambda current: add_item(current, checked), expected_rev)
        return result if isinstance(result, RuleError) else find_item(items, checked.name)  # type: ignore[return-value]

    async def edit(
        self, gid: int, name: str, item: Playlist, expected_rev: Optional[int] = None
    ) -> Playlist | RuleError:
        checked = _validated(item)
        if isinstance(checked, RuleError):
            return checked
        result, items = await self._write(gid, lambda current: edit_item(current, name, checked), expected_rev)
        return result if isinstance(result, RuleError) else find_item(items, checked.name)  # type: ignore[return-value]

    async def remove(self, gid: int, name: str, expected_rev: Optional[int] = None) -> Playlist | RuleError:
        """Remove a playlist e devolve a removida."""
        removed: dict[str, Optional[Playlist]] = {}

        def change(current: tuple[Playlist, ...]):
            removed["item"] = find_item(current, name)
            return remove_item(current, name)

        result, _ = await self._write(gid, change, expected_rev)
        return result if isinstance(result, RuleError) else removed["item"]  # type: ignore[return-value]

    async def clear(self, gid: int, expected_rev: Optional[int] = None) -> int:
        """Apaga todas e devolve quantas eram (o chamador exporta antes)."""
        count: dict[str, int] = {}

        def change(current: tuple[Playlist, ...]):
            count["n"] = len(current)
            return ()

        await self._write(gid, change, expected_rev)
        return count["n"]

    async def import_file(self, gid: int, parsed: ParsedFile, expected_rev: Optional[int] = None) -> ImportReport:
        """Só acrescenta (nunca altera nem remove). O relatório só existe depois de gravar."""
        report: dict[str, ImportReport] = {}

        def change(current: tuple[Playlist, ...]):
            planned = plan_import(current, parsed.items)
            report["value"] = planned
            return (*current, *planned.added)

        await self._write(gid, change, expected_rev)
        planned = report["value"]
        return ImportReport(planned.added, (*parsed.invalid, *planned.skipped))

    # ------------------------------------------------------------------ embed ocioso

    def refresh_idle(self, gid: int) -> None:
        """Atualiza, em segundo plano, o embed ocioso de CADA bot do pool no servidor (até o painel único do P4)."""
        task = asyncio.get_running_loop().create_task(self._refresh(gid))
        self._refresh_tasks.add(task)
        task.add_done_callback(self._refresh_tasks.discard)

    async def _refresh(self, gid: int) -> None:
        for bot in self.store.pool.get_all_bots():
            try:
                await self._refresh_bot(bot, gid)
            except Exception as exc:  # noqa: BLE001 - enfeite: a lista já foi gravada
                logger.warning(
                    "Embed ocioso do bot %s não atualizado [%s] (%s)", bot.identifier, gid, type(exc).__name__
                )

    async def _refresh_bot(self, bot, gid: int) -> None:
        from empiremuse.utils.others import send_idle_embed  # tarde: utils.others importa muita coisa

        if bot.user is None or bot.get_guild(gid) is None or gid in bot.music.players:
            return  # tocando, o player mostra o próprio embed
        data = await bot.get_data(gid, db_name=DBModel.guilds)
        controller = data["player_controller"]
        if not controller["channel"]:
            return
        channel = bot.get_channel(int(controller["channel"]))
        if isinstance(channel, disnake.Thread):
            target = channel
        elif isinstance(channel, disnake.TextChannel) and controller["message_id"]:
            target = await channel.fetch_message(int(controller["message_id"]))
        else:
            return
        await send_idle_embed(target, bot=bot, guild_data=data, force=True)

# -*- coding: utf-8 -*-
"""Painel do canal de pedidos único (item 11, P4): quem edita a mensagem, quantos players há e a edição agrupada por servidor.

O bot do painel é o AUTOR da mensagem e por isso o único que pode editá-la; os players dos outros bots a recebem já ligada ao bot do painel
(``fetch_panel_message``), então ``player.message.edit`` sai com o token certo. Com 0 players o painel é o embed ocioso; com 1 é a skin
estática desse player; com 2 ou mais é a lista (``interactions/request_panel.render_panel``). Edição do painel: no máximo uma por servidor a
cada 3 s, agrupada (várias mudanças viram uma só). Toda falha vai para o log; o painel é enfeite sobre uma lista já gravada.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from typing import TYPE_CHECKING, Any, Optional

import disnake

from empiremuse.rules.request_panel import PanelEntry, make_entry, refresh_wait_ms

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore, BotPool
    from empiremuse.utils.music.models import LavalinkPlayer

logger = logging.getLogger(__name__)

NO_MENTIONS = disnake.AllowedMentions.none()


def is_private(voice_channel: Any) -> bool:
    """A call é privada? ``@everyone`` não enxerga ou não entra: a faixa e quem pediu não aparecem no painel (S-V7)."""
    try:
        perms = voice_channel.permissions_for(voice_channel.guild.default_role)
    except AttributeError:
        return True
    return not (perms.view_channel and perms.connect)


def entry_for(bot: BotCore, player: LavalinkPlayer) -> Optional[PanelEntry]:
    """O bloco do painel para um player conectado; ``None`` se ele não está em call."""
    voice = getattr(getattr(player.guild.me, "voice", None), "channel", None)
    if voice is None:
        return None
    track = player.current
    requester = None
    if track is not None and getattr(track, "requester", None):
        member = player.guild.get_member(int(track.requester)) if str(track.requester).isdigit() else None
        requester = member.display_name if member else None
    return make_entry(
        bot_name=bot.user.display_name,
        bot_id=bot.user.id,
        voice_name=voice.name,
        private=is_private(voice),
        title=getattr(track, "title", None),
        url=getattr(track, "uri", None),
        paused=bool(getattr(player, "paused", False)),
        queue=len(player.queue),
        requester=requester,
    )


async def fetch_panel_message(pool: BotPool, guild_id: int) -> Optional[disnake.Message]:
    """A mensagem do painel vista PELO BOT DO PAINEL (o autor): só ela pode ser editada. ``None`` se não há canal ou mensagem."""
    request = pool.servers.request
    config = await request.get(guild_id)
    if not config.channel or not config.message_id:
        return None
    bot = await request.panel_bot(guild_id)
    if bot is None:
        return None
    channel = bot.get_channel(config.channel) or await bot.fetch_channel(config.channel)
    if isinstance(channel, disnake.Thread) and not isinstance(channel.parent, disnake.ForumChannel):
        return await channel.parent.fetch_message(config.message_id)
    return await channel.fetch_message(config.message_id)


class RequestPanel:
    def __init__(self, pool: BotPool) -> None:
        self.pool = pool
        self._last: dict[int, int] = {}
        self._pending: dict[int, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()
        self._locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()
        self._resend_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()

    # ------------------------------------------------------------------ quem está tocando

    def players(self, guild_id: int) -> list[tuple[BotCore, LavalinkPlayer]]:
        """Os players estáticos (do canal de pedidos) do servidor, de todos os bots, na ordem do ``identifier``."""
        found = []
        for bot in sorted(self.pool.get_all_bots(), key=lambda b: b.identifier):
            player = bot.music.players.get(guild_id) if bot.user else None
            if player is not None and player.static and not player.is_closing:
                found.append((bot, player))
        return found

    def takes_over(self, guild_id: int) -> bool:
        """O painel inteiro (lista) assume a mensagem? Só com 2 ou mais players: com 1, vale a skin estática do player."""
        return len(self.players(guild_id)) >= 2

    # ------------------------------------------------------------------ edição agrupada

    async def refresh(self, guild_id: int, *, now: bool = False) -> None:
        """Redesenha o painel do servidor, no máximo 1 vez a cada 3 s: pedidos no meio da janela viram UMA edição no fim dela."""
        wait = 0 if now else refresh_wait_ms(self._last.get(guild_id), int(time.monotonic() * 1000))
        if wait <= 0:
            await self._render(guild_id)
            return
        task = self._pending.get(guild_id)
        if task is None or task.done():
            self._pending[guild_id] = self._spawn(self._later(guild_id, wait / 1000), guild_id)

    def _spawn(self, coro, guild_id: Optional[int] = None) -> asyncio.Task:
        """Tarefa de fundo COM referência (o laço só guarda referência fraca) e removida quando termina."""
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)

        def done(finished: asyncio.Task) -> None:
            self._tasks.discard(finished)
            if guild_id is not None and self._pending.get(guild_id) is finished:
                del self._pending[guild_id]

        task.add_done_callback(done)
        return task

    async def _later(self, guild_id: int, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._render(guild_id)

    def _lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = self._locks[guild_id] = asyncio.Lock()
        return lock

    async def _render(self, guild_id: int) -> None:
        async with self._lock(guild_id):
            self._last[guild_id] = int(time.monotonic() * 1000)
            try:
                await self._draw(guild_id)
            except Exception as exc:  # noqa: BLE001 - enfeite sobre dados já gravados
                logger.warning("Painel do canal de pedidos não atualizado [%s] (%s)", guild_id, type(exc).__name__)

    async def _draw(self, guild_id: int) -> None:
        from empiremuse.utils.others import send_idle_embed  # tarde: utils.others importa muita coisa
        from empiremuse.utils.music.interactions.request_panel import render_panel
        from empiremuse.utils.server_playlists import load_select_options

        panel_bot = await self.pool.servers.request.panel_bot(guild_id)
        message = await fetch_panel_message(self.pool, guild_id)
        if panel_bot is None or message is None:
            return
        players = self.players(guild_id)
        if not players:
            await send_idle_embed(message, bot=panel_bot, force=True)
        elif len(players) == 1:
            await players[0][1].invoke_np(force=True, panel_render=True)  # a skin estática do player, como sempre foi
        else:
            for _, player in players:
                player.last_data = {}  # o painel vira lista: ao voltar à skin, ela precisa ser redesenhada
            entries = [e for bot, player in players if (e := entry_for(bot, player)) is not None]
            payload = render_panel(
                panel_bot,
                message.guild,
                entries,
                playlist_options=await load_select_options(panel_bot, guild_id),
            )
            await message.edit(allowed_mentions=NO_MENTIONS, **payload)

    async def resend(self, guild_id: int, *, replace_message_id: Optional[int] = None) -> Optional[disnake.Message]:
        """O BOT DO PAINEL envia um painel novo no canal de pedidos e grava o id (a mensagem anterior sumiu ou era de outro bot).

        ``replace_message_id``: a mensagem antiga (do bot que saiu); o novo painel tenta apagá-la, sem insistir se não puder.
        """
        from empiremuse.utils.others import send_idle_embed  # tarde: utils.others importa muita coisa

        lock = self._resend_locks.get(guild_id)
        if lock is None:
            lock = self._resend_locks[guild_id] = asyncio.Lock()
        async with lock:  # dois reenvios juntos mandariam dois painéis: o segundo encontra o do primeiro
            request = self.pool.servers.request
            config = await request.get(guild_id)
            bot = await request.panel_bot(guild_id)
            if not config.channel or bot is None:
                return None
            if replace_message_id is None:
                try:
                    if (existing := await fetch_panel_message(self.pool, guild_id)) is not None:
                        return existing
                except disnake.HTTPException:
                    pass
            channel = bot.get_channel(config.channel) or await bot.fetch_channel(config.channel)
            message = await send_idle_embed(channel, bot=bot, force=True)
            try:
                await request.set(guild_id, config.channel, message.id, expected=config.current)
            except Exception:
                await message.delete()  # a configuração mudou no meio: não deixa painel órfão
                raise
        if replace_message_id and replace_message_id != message.id:
            try:
                await channel.get_partial_message(replace_message_id).delete()
            except disnake.HTTPException:
                pass
        return message

    async def on_roster_change(self, guild_id: int) -> None:
        """Um bot entrou ou saiu do servidor: se o bot do painel mudou, o novo reenvia o painel (e a mensagem do antigo sai)."""
        request = self.pool.servers.request
        config = await request.get(guild_id)
        election = await request.elect(guild_id)
        if election.bot is None or not election.changed or not config.channel:
            return
        message = await self.resend(guild_id, replace_message_id=config.message_id)
        if message is None or (await request.get(guild_id)).message_id != message.id:
            return  # outro reenvio gravou uma mensagem mais nova durante este: religar à antiga deixaria os players numa apagada
        for _, player in self.players(guild_id):
            player.message = message  # a anterior foi apagada; os players passam a editar o painel novo
            player.last_data = {}
        await self.refresh(guild_id, now=True)

    def forget(self, guild_id: int) -> None:
        """Um player acabou ou saiu da call: o painel se refaz (volta ao ocioso, ou à skin do que sobrou)."""
        try:
            self._spawn(self.refresh(guild_id))
        except RuntimeError:
            return

    def close(self) -> None:
        """Cancela as tarefas de fundo do painel (encerramento do pool)."""
        for task in list(self._tasks):
            task.cancel()

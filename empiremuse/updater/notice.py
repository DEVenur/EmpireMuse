"""Aviso pós-boot do update: quando o pool fica saudável, conta no canal de origem se deu certo ou se voltou.

O sucesso da subida é do pool (``on_pool_ready`` marca o pendente como ``ready``), não de um bot específico; o aviso sai pelo
bot que pediu ou, se ele não está mais no pool, pelo primeiro bot pronto. Uma única entrega: o pendente é apagado antes do
envio (quem chegar depois não encontra nada). Sem canal alcançável o aviso vai por DM a quem pediu, pelo mesmo bot; sem os
dois, só o log. Nenhuma menção é permitida e nada do conteúdo vai para o log.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import disnake

from empiremuse import paths
from empiremuse.rules.release import Version, changelog_sections
from empiremuse.updater.git_flow import installed_version
from empiremuse.updater.state import PendingUpdate, clear_pending, read_pending, write_pending
from empiremuse.utils import branding

logger = logging.getLogger(__name__)

CHANGELOG_MAX_CHARS = 3500
COLOR_OK = 0x2ECC71
COLOR_FAIL = 0xE74C3C
COLOR_UNKNOWN = 0xF1C40F

VersionDetector = Callable[[PendingUpdate], Awaitable[Version | None]]


async def detect_running_version(pending: PendingUpdate) -> Version | None:
    """Versão que de fato subiu: a tag do clone (fluxo git)."""
    if pending.flow == "git":
        return await installed_version(paths.PROJECT_DIR)
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")[: 1024 * 1024]
    except OSError, ValueError:
        return ""


def build_notice(pending: PendingUpdate, running: Version | None, changelog: str) -> disnake.Embed:
    """Embed do resultado, decidido pela versão que de fato subiu (``running``), não só pelo estado gravado.

    ``running == from`` → voltou; ``running == to`` com o pendente ainda ``pending`` → sucesso; qualquer outra combinação
    (inclusive ``rolled_back`` cuja reversão não se confirmou) → resultado incerto.
    """
    link = f"{branding.REPO_URL}/blob/v{pending.to_version}/CHANGELOG.md"
    if running == pending.from_version:
        text = (
            f"⚠️ **A atualização para {pending.to_version} falhou e o bot voltou para a versão {pending.from_version}.**"
            f"\nVeja o log do servidor para o motivo."
        )
        return disnake.Embed(description=text, colour=COLOR_FAIL)
    if pending.status in ("pending", "ready") and running == pending.to_version:
        text = f"✅ **Atualizado de {pending.from_version} para {pending.to_version}.**"
        if changelog:
            text += f"\n\n{changelog}"
        return disnake.Embed(description=f"{text}\n\n[Histórico completo]({link})", colour=COLOR_OK)
    if pending.status == "rolled_back":
        text = (
            f"❔ **A atualização para {pending.to_version} falhou e tentei voltar para a versão {pending.from_version}, "
            "mas não consegui confirmar a versão instalada.**\nConfira o servidor."
        )
    else:
        text = (
            f"❔ **A atualização de {pending.from_version} para {pending.to_version} terminou, mas não consegui confirmar a "
            "versão instalada.**\nConfira o servidor."
        )
    return disnake.Embed(description=text, colour=COLOR_UNKNOWN)


async def _send(bot: Any, pending: PendingUpdate, embed: disnake.Embed) -> bool:
    """Canal de origem; se não der, DM a quem pediu. ``True`` se alguma entrega funcionou."""
    allowed = disnake.AllowedMentions.none()
    try:
        channel = bot.get_channel(pending.channel_id) or await bot.fetch_channel(pending.channel_id)
        await channel.send(embed=embed, allowed_mentions=allowed)
        return True
    except disnake.HTTPException, AttributeError:
        logger.info("update: canal %s inalcançável; tentando DM a quem pediu", pending.channel_id)
    try:
        user = bot.get_user(pending.requested_by) or await bot.fetch_user(pending.requested_by)
        await user.send(embed=embed, allowed_mentions=allowed)
        return True
    except disnake.HTTPException, AttributeError:
        logger.warning("update: não consegui entregar o aviso nem por DM")
        return False


def _sender(pool: Any, pending: PendingUpdate) -> Any | None:
    """O bot que pediu, se ainda está em ``pool.bots`` e pronto; senão o primeiro bot pronto do pool (ou ``None``)."""
    ready = [bot for bot in pool.bots if bot.bot_ready]
    for bot in ready:
        if getattr(bot.user, "id", None) == pending.bot_id:
            return bot
    return ready[0] if ready else None


async def deliver_update_notice(
    pool: Any,
    *,
    runtime_dir: Path | None = None,
    now: Callable[[], float] = time.time,
    detect_version: VersionDetector = detect_running_version,
) -> None:
    """Entrega o aviso do pendente por um bot pronto do pool (o que pediu, ou outro); sem bot pronto não faz nada."""
    runtime_dir = runtime_dir or paths.get_runtime_dir()
    pending = read_pending(runtime_dir, now())
    if pending is None:
        return
    bot = _sender(pool, pending)
    if bot is None:
        return
    clear_pending(runtime_dir)  # uma única entrega, mesmo que o envio falhe
    running = await detect_version(pending)
    changelog = ""
    if running == pending.to_version and pending.status in ("pending", "ready"):
        text = await asyncio.get_running_loop().run_in_executor(None, _read_text, paths.PROJECT_DIR / "CHANGELOG.md")
        changelog = changelog_sections(text, pending.from_version, pending.to_version, CHANGELOG_MAX_CHARS)
    await _send(bot, pending, build_notice(pending, running, changelog))


async def on_pool_ready(
    pool: Any,
    *,
    runtime_dir: Path | None = None,
    now: Callable[[], float] = time.time,
    detect_version: VersionDetector = detect_running_version,
) -> None:
    """Chamado quando o pool fica saudável: um pendente ``pending`` vira ``ready`` (a subida deu certo) e o aviso sai.

    O ``ready`` é gravado ANTES de qualquer envio e zera a contagem do ``boot_guard``: um token que não loga mais, ou um
    envio que falha, não pode levar o próximo boot a reverter uma atualização boa. Sem pendente ou com o pool doente não
    faz nada; chamado duas vezes, entrega uma vez só (a primeira apaga o pendente).
    """
    if not pool.pool_is_healthy():
        return
    runtime_dir = runtime_dir or paths.get_runtime_dir()
    pending = read_pending(runtime_dir, now())
    if pending is None:
        return
    if pending.status == "pending":
        write_pending(runtime_dir, dataclasses.replace(pending, status="ready", boots=0))
    await deliver_update_notice(pool, runtime_dir=runtime_dir, now=now, detect_version=detect_version)

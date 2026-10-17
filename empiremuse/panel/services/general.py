"""Categoria Geral: prefixo (G-12) e status automático do canal de voz (G-13)."""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

import disnake

from empiremuse.panel.services.base import Args, FormContext, ParseResult, SettingsForm, first
from empiremuse.panel.services.player import active_player

logger = logging.getLogger(__name__)

# Mesmos limites dos comandos: legacy_cmds.setprefix (5 caracteres) e SetStageTitle (496 caracteres, 9 placeholders).
PREFIX_MAX_LENGTH = 5
VOICE_STATUS_MAX_LENGTH = 496
VOICE_PLACEHOLDERS = (
    "{track.title}",
    "{track.timestamp}",
    "{track.emoji}",
    "{track.author}",
    "{track.duration}",
    "{track.source}",
    "{track.playlist}",
    "{requester.name}",
    "{requester.id}",
)
MSG_PREFIX_LENGTH = f"O prefixo pode ter no máximo {PREFIX_MAX_LENGTH} caracteres."
MSG_PREFIX_CHARS = "O prefixo não pode conter espaços nem caracteres de controle."
MSG_VOICE_PLACEHOLDER = "Use pelo menos um placeholder válido, como {track.title}."
MSG_VOICE_LENGTH = f"O texto pode ter no máximo {VOICE_STATUS_MAX_LENGTH} caracteres."


class PrefixForm(SettingsForm):
    key = "prefixo"
    category = "geral"
    scope_kind = "global"
    fields = ("prefix",)
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        return {"prefix": doc["prefix"]}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["prefix"] = new["prefix"]

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        raw = first(args, "prefix") or ""
        echo = {"prefix": raw}
        if len(raw) > PREFIX_MAX_LENGTH:
            return ParseResult({}, {"prefix": MSG_PREFIX_LENGTH}, echo)
        if any(char.isspace() or unicodedata.category(char) in ("Cc", "Cf") for char in raw):
            return ParseResult({}, {"prefix": MSG_PREFIX_CHARS}, echo)
        return ParseResult({"prefix": raw}, {}, echo)  # vazio = voltar ao prefixo padrão (como resetprefix)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        ctx.pool.guild_prefix_cache[ctx.guild_id] = new["prefix"]


def normalize_status(text: str) -> str:
    """Quebras de linha viram espaço e as pontas são aparadas, como o modal do comando."""
    flat = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    return flat.strip()


class VoiceStatusForm(SettingsForm):
    key = "status_voz"
    category = "geral"
    scope_kind = "global"
    fields = ("voice_channel_status",)
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        return {"voice_channel_status": doc["voice_channel_status"]}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["voice_channel_status"] = new["voice_channel_status"]

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"placeholders": VOICE_PLACEHOLDERS}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        raw = first(args, "voice_channel_status") or ""
        text = normalize_status(raw)
        echo = {"voice_channel_status": raw}
        if len(text) > VOICE_STATUS_MAX_LENGTH:
            return ParseResult({}, {"voice_channel_status": MSG_VOICE_LENGTH}, echo)
        if text and not any(placeholder in text for placeholder in VOICE_PLACEHOLDERS):
            return ParseResult({}, {"voice_channel_status": MSG_VOICE_PLACEHOLDER}, echo)
        return ParseResult({"voice_channel_status": text}, {}, echo)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        text = new["voice_channel_status"]
        for bot in ctx.pool.get_guild_bots(ctx.guild_id):
            player = active_player(bot, ctx.guild_id)
            if player is not None:
                await self._update_player(player, text)

    @staticmethod
    async def _update_player(player: Any, text: str) -> None:
        player.stage_title_event = bool(text)
        player.stage_title_template = text
        player.start_time = disnake.utils.utcnow()
        player.set_command_log(
            text="O painel " + ("ativou" if text else "desativou") + " o status automático.", emoji="📢"
        )
        player.update = True
        await player.update_stage_topic(clear=not text)
        await player.process_save_queue()

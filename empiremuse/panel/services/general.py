"""Categoria Geral: prefixo (G-12) e status automático do canal de voz (G-13)."""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

import disnake

from empiremuse.panel.services.base import Args, FormContext, ParseResult, SettingsForm, first
from empiremuse.panel.services.player import active_player
from empiremuse.rules import limits
from empiremuse.rules.errors import PREFIX_LENGTH, STATUS_CHARS, STATUS_TOO_LONG, RuleError
from empiremuse.rules.settings import validate_prefix, validate_voice_status

logger = logging.getLogger(__name__)

MSG_PREFIX_LENGTH = f"O prefixo pode ter no máximo {limits.PREFIX_MAX_LENGTH} caracteres."
MSG_PREFIX_CHARS = "O prefixo não pode conter espaços nem caracteres de controle."
MSG_VOICE_PLACEHOLDER = "Use pelo menos um placeholder válido, como {track.title}."
MSG_VOICE_LENGTH = f"O texto pode ter no máximo {limits.VOICE_STATUS_MAX_LENGTH} caracteres."
MSG_VOICE_CHARS = "O texto não pode ter caracteres de controle nem de formatação."


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
        sent = first(args, "prefix") or ""
        echo = {"prefix": sent}
        if not sent.strip():
            return ParseResult({"prefix": ""}, {}, echo)  # vazio = voltar ao prefixo padrão (como resetprefix)
        prefix = validate_prefix(sent)
        if isinstance(prefix, RuleError):
            return ParseResult(
                {}, {"prefix": MSG_PREFIX_LENGTH if prefix.code == PREFIX_LENGTH else MSG_PREFIX_CHARS}, echo
            )
        return ParseResult({"prefix": prefix}, {}, echo)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        ctx.pool.guild_prefix_cache[ctx.guild_id] = new["prefix"]


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
        return {"placeholders": limits.VOICE_PLACEHOLDERS}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        raw = first(args, "voice_channel_status") or ""
        echo = {"voice_channel_status": raw}
        text = validate_voice_status(raw)
        if isinstance(text, RuleError):
            message = {STATUS_TOO_LONG: MSG_VOICE_LENGTH, STATUS_CHARS: MSG_VOICE_CHARS}.get(
                text.code, MSG_VOICE_PLACEHOLDER
            )
            return ParseResult({}, {"voice_channel_status": message}, echo)
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

"""Categoria Geral: prefixo (G-12) e status automático do canal de voz (G-13)."""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from empiremuse.panel.services.base import Args, FormContext, ParseResult, SettingsForm, first, flag
from empiremuse.panel.services.player import active_player
from empiremuse.rules import limits
from empiremuse.rules.errors import PREFIX_LENGTH, STATUS_CHARS, STATUS_TOO_LONG, RuleError
from empiremuse.rules.settings import validate_prefix, validate_voice_status
from empiremuse.rules.voice_status import DEFAULT_VOICE_TEMPLATE, resolve_voice_status
from empiremuse.utils.music.models.player_voice import schedule_permanent_voice_status

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
    fields = ("voice_status_permanent", "voice_channel_status")
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        cfg = resolve_voice_status(doc)
        return {
            "voice_status_permanent": cfg.permanent,
            "voice_channel_status": "" if cfg.template == DEFAULT_VOICE_TEMPLATE else cfg.template,
        }

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["voice_status_permanent"] = new["voice_status_permanent"]
        doc["voice_channel_status"] = new["voice_channel_status"]

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"placeholders": limits.VOICE_PLACEHOLDERS, "modelo_padrao": DEFAULT_VOICE_TEMPLATE}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        raw = first(args, "voice_channel_status") or ""
        permanent = flag(args, "voice_status_permanent")
        echo = {"voice_status_permanent": permanent, "voice_channel_status": raw}
        text = validate_voice_status(raw)
        if isinstance(text, RuleError):
            message = {STATUS_TOO_LONG: MSG_VOICE_LENGTH, STATUS_CHARS: MSG_VOICE_CHARS}.get(
                text.code, MSG_VOICE_PLACEHOLDER
            )
            return ParseResult({}, {"voice_channel_status": message}, echo)
        return ParseResult({"voice_status_permanent": permanent, "voice_channel_status": text}, {}, echo)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        cfg = resolve_voice_status(new)
        for bot in ctx.pool.get_guild_bots(ctx.guild_id):
            player = active_player(bot, ctx.guild_id)
            if player is not None:
                schedule_permanent_voice_status(player, cfg)  # não espera: o POST responde sem aguardar o Discord

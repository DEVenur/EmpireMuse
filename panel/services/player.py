"""Categorias Player (G-01…G-04) e DJ (G-05)."""
from __future__ import annotations

import re
from typing import Any, NamedTuple

from panel.services.base import DIGITS, Args, FormContext, ParseResult, SettingsForm, flag, first

# Mesmo conjunto do comando (modules/music_settings.py, PlayerSettings): 5…100 de 5 em 5 e 110…150 de 10 em 10.
VOLUMES = tuple(range(5, 101, 5)) + tuple(range(110, 151, 10))
MAX_DJ_ROLES = 25
_VOLUME = re.compile(r"[0-9]{1,3}", re.ASCII)
MSG_VOLUME = "Escolha um volume válido: de 5 a 100 (de 5 em 5) ou de 110 a 150 (de 10 em 10)."
MSG_ROLE_INVALID = "Selecione apenas cargos que existem neste servidor."
MSG_ROLE_DUPLICATE = "Há cargos repetidos na seleção."
MSG_ROLE_LIMIT = f"Selecione no máximo {MAX_DJ_ROLES} cargos."


def active_player(bot: Any, guild_id: int) -> Any:
    """Player ativo do bot no servidor, ou ``None``."""
    try:
        return bot.music.players[guild_id]
    except KeyError:
        return None


class PlayerForm(SettingsForm):
    key = "player"
    category = "player"
    fields = ("default_player_volume", "autoplay", "check_other_bots_in_vc", "enable_restrict_mode")
    markers = fields
    _FLAGS = fields[1:]

    def extract(self, doc: dict) -> dict[str, Any]:
        return {name: doc[name] for name in self.fields}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc.update(new)

    def display(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "default_player_volume": str(current["default_player_volume"])}

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"volumes": VOLUMES}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        raw = first(args, "default_player_volume") or ""
        flags = {name: flag(args, name) for name in self._FLAGS}
        echo = {"default_player_volume": raw, **flags}
        volume = int(raw) if _VOLUME.fullmatch(raw) else None
        if volume not in VOLUMES:
            return ParseResult({}, {"default_player_volume": MSG_VOLUME}, echo)
        return ParseResult({"default_player_volume": volume, **flags}, {}, echo)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        player = active_player(ctx.bot, ctx.guild_id)
        if player is not None:
            await player.process_save_queue()


class RoleOption(NamedTuple):
    id: str
    name: str


class DjForm(SettingsForm):
    key = "dj"
    category = "dj"
    fields = ("djroles",)
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        return {"djroles": [str(role_id) for role_id in doc["djroles"]]}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["djroles"] = list(new["djroles"])

    def _roles(self, ctx: FormContext) -> tuple[RoleOption, ...]:
        everyone = ctx.guild.default_role.id
        return tuple(RoleOption(str(role.id), role.name) for role in ctx.guild.roles if role.id != everyone)

    def display(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        existing = {role.id for role in self._roles(ctx)}
        return {"djroles": [role_id for role_id in current["djroles"] if role_id in existing]}

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"cargos": self._roles(ctx)}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        sent = list(args.get("djroles", []))
        error = self._validate(ctx, sent)
        if error:
            return ParseResult({}, {"djroles": error}, {"djroles": sent})
        stored = current["djroles"]
        chosen = set(sent)
        # Ordem estável: o que já estava gravado mantém a posição; o novo entra no fim, na ordem enviada.
        ordered = [role_id for role_id in stored if role_id in chosen]
        ordered += [role_id for role_id in sent if role_id not in set(stored)]
        return ParseResult({"djroles": ordered}, {}, {"djroles": sent})

    def _validate(self, ctx: FormContext, sent: list[str]) -> str:
        if len(sent) > MAX_DJ_ROLES:
            return MSG_ROLE_LIMIT
        if len(set(sent)) != len(sent):
            return MSG_ROLE_DUPLICATE
        valid = {role.id for role in self._roles(ctx)}
        if any(not DIGITS.fullmatch(role_id) or role_id not in valid for role_id in sent):
            return MSG_ROLE_INVALID
        return ""

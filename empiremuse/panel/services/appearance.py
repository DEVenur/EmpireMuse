"""Categoria Aparência: skins do servidor (G-08, G-09; doc único, valem para todos os bots) e skins globais (G-10, G-11).

As skins personalizadas do servidor não são lidas nem gravadas pelo painel: um valor atual "> custom_skin: X" só é
exibido e mantido se o formulário reenviar exatamente esse valor.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from empiremuse.panel.services.base import DBModel, Args, FormContext, ParseResult, SettingsForm, first, flag
from empiremuse.panel.services.player import active_player, guild_players
from empiremuse.rules import limits
from empiremuse.rules.settings import allowed_names

logger = logging.getLogger(__name__)

MSG_SKIN = "Escolha uma skin da lista."


def allowed_skins(bot: Any) -> tuple[str, ...]:
    """Skins do modo normal, menos as de IGNORE_SKINS (lido da config a cada requisição, como o comando)."""
    return allowed_names(bot.player_skins, bot.config["IGNORE_SKINS"])


def allowed_static_skins(bot: Any) -> tuple[str, ...]:
    return allowed_names(bot.player_static_skins, bot.config["IGNORE_STATIC_SKINS"])


def _pick(raw: Optional[str], allowed: tuple[str, ...], stored: Optional[str]) -> bool:
    """Skin aceita se estiver na lista ou for exatamente o valor já gravado (reenviar não é trocar)."""
    return bool(raw) and (raw in allowed or raw == stored)


async def reload_skin(player: Any, skin: str, static_skin: str, text: str) -> None:
    """Recarrega a skin de um player ativo como o comando (music_settings.py), se a skin relevante mudou."""
    target, current = (static_skin, player.skin_static) if player.static else (skin, player.skin)
    if target == str(current):
        return
    if skin.startswith(limits.CUSTOM_SKIN_PREFIX) or static_skin.startswith(limits.CUSTOM_SKIN_PREFIX):
        logger.info("Skin personalizada não é recarregada pelo painel; use o Discord para aplicá-la.")
        return
    try:
        await player.destroy_message()
    except Exception as exc:
        logger.warning("Falha ao remover a mensagem do player (%s)", type(exc).__name__)
    player.skin = skin
    player.skin_static = static_skin
    player.setup_features()
    player.setup_hints()
    player.process_hint()
    player.set_command_log(text=text, emoji="🎨")
    await player.invoke_np(force=True)


class SkinsServerForm(SettingsForm):
    key = "skin_servidor"
    category = "aparencia"
    scope_kind = "servidor"
    fields = ("skin", "static_skin")
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        return {"skin": doc["skin"], "static_skin": doc["static_skin"]}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc.update(new)

    def display(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {
            "skin": current["skin"] or ctx.pool.default_skin,
            "static_skin": current["static_skin"] or ctx.pool.default_static_skin,
        }

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"skins": allowed_skins(ctx.bot), "skins_estaticas": allowed_static_skins(ctx.bot)}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        shown = self.display(ctx, current)
        echo = {name: first(args, name) or "" for name in self.fields}
        lists = {"skin": allowed_skins(ctx.bot), "static_skin": allowed_static_skins(ctx.bot)}
        errors = {name: MSG_SKIN for name in self.fields if not _pick(echo[name], lists[name], shown[name])}
        return ParseResult({} if errors else dict(echo), errors, echo)

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        global_data = await ctx.bot.get_global_data(ctx.guild_id, db_name=DBModel.guilds)
        if global_data["global_skin"]:
            return  # no modo global os players seguem a skin global
        for player in guild_players(ctx):
            await reload_skin(player, new["skin"], new["static_skin"], "O painel alterou a skin do player.")


class SkinsGlobalForm(SettingsForm):
    key = "skin_global"
    category = "aparencia"
    scope_kind = "global"
    fields = ("global_skin", "player_skin", "player_skin_static")
    markers = ("player_skin", "player_skin_static")

    def extract(self, doc: dict) -> dict[str, Any]:
        return {
            "global_skin": bool(doc["global_skin"]),
            "player_skin": doc["player_skin"],
            "player_skin_static": doc["player_skin_static"],
        }

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc.update(new)

    def display(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {
            "global_skin": current["global_skin"],
            "player_skin": current["player_skin"] or "",
            "player_skin_static": current["player_skin_static"] or "",
        }

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"skins": allowed_skins(ctx.bot), "skins_estaticas": allowed_static_skins(ctx.bot)}

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        echo = {
            "global_skin": flag(args, "global_skin"),
            "player_skin": first(args, "player_skin"),
            "player_skin_static": first(args, "player_skin_static"),
        }
        lists = {"player_skin": allowed_skins(ctx.bot), "player_skin_static": allowed_static_skins(ctx.bot)}
        errors = {
            name: MSG_SKIN
            for name, allowed in lists.items()
            if echo[name] is None or (echo[name] != "" and not _pick(echo[name], allowed, current[name]))
        }
        echo = {name: ("" if value is None else value) for name, value in echo.items()}
        if errors:
            return ParseResult({}, errors, echo)
        return ParseResult(
            {
                "global_skin": echo["global_skin"],
                "player_skin": echo["player_skin"] or None,
                "player_skin_static": echo["player_skin_static"] or None,
            },
            {},
            echo,
        )

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        players = guild_players(ctx)
        if not players:
            return
        skin, static_skin = await self._effective(ctx, new)
        for player in players:
            await reload_skin(player, skin, static_skin, "O painel alterou a skin do player.")

    @staticmethod
    async def _effective(ctx: FormContext, new: dict[str, Any]) -> tuple[str, str]:
        """Skins que os players devem usar: as globais (modo global) ou as do servidor."""
        if new["global_skin"]:
            return (
                new["player_skin"] or ctx.pool.default_skin,
                new["player_skin_static"] or ctx.pool.default_static_skin,
            )
        own = await ctx.pool.servers.settings(ctx.guild_id)
        return own["skin"] or ctx.pool.default_skin, own["static_skin"] or ctx.pool.default_static_skin

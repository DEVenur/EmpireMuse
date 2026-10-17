"""Categoria Aparência: skins por bot (G-08, G-09) e skins globais (G-10, G-11).

As skins personalizadas do servidor não são lidas nem gravadas pelo painel: um valor atual "> custom_skin: X" só é
exibido e mantido se o formulário reenviar exatamente esse valor.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from empiremuse.panel.services.base import DBModel, Args, FormContext, ParseResult, SettingsForm, first, flag
from empiremuse.panel.services.player import active_player

logger = logging.getLogger(__name__)

CUSTOM_PREFIX = "> custom_skin: "
MSG_SKIN = "Escolha uma skin da lista."


def allowed_skins(bot: Any) -> tuple[str, ...]:
    """Skins do modo normal, menos as de IGNORE_SKINS (lido da config a cada requisição, como o comando)."""
    ignored = bot.config["IGNORE_SKINS"].split()
    return tuple(name for name in bot.player_skins if name not in ignored)


def allowed_static_skins(bot: Any) -> tuple[str, ...]:
    ignored = bot.config["IGNORE_STATIC_SKINS"].split()
    return tuple(name for name in bot.player_static_skins if name not in ignored)


def _pick(raw: Optional[str], allowed: tuple[str, ...], stored: Optional[str]) -> bool:
    """Skin aceita se estiver na lista ou for exatamente o valor já gravado (reenviar não é trocar)."""
    return bool(raw) and (raw in allowed or raw == stored)


async def reload_skin(player: Any, skin: str, static_skin: str, text: str) -> None:
    """Recarrega a skin de um player ativo como o comando (music_settings.py), se a skin relevante mudou."""
    target, current = (static_skin, player.skin_static) if player.static else (skin, player.skin)
    if target == str(current):
        return
    if skin.startswith(CUSTOM_PREFIX) or static_skin.startswith(CUSTOM_PREFIX):
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


class SkinsBotForm(SettingsForm):
    key = "skin_bot"
    category = "aparencia"
    fields = ("skin", "static_skin")
    markers = fields

    def extract(self, doc: dict) -> dict[str, Any]:
        controller = doc["player_controller"]
        return {"skin": controller.get("skin"), "static_skin": controller.get("static_skin")}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["player_controller"].update(new)

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
        player = active_player(ctx.bot, ctx.guild_id)
        if global_data["global_skin"] or player is None:
            return  # no modo global o player segue a skin global
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
        for bot in ctx.pool.get_guild_bots(ctx.guild_id):
            player = active_player(bot, ctx.guild_id)
            if player is None:
                continue
            skin, static_skin = await self._effective(ctx, bot, new)
            await reload_skin(player, skin, static_skin, "O painel alterou a skin do player.")

    @staticmethod
    async def _effective(ctx: FormContext, bot: Any, new: dict[str, Any]) -> tuple[str, str]:
        """Skins que o player do bot deve usar: as globais (modo global) ou as do próprio bot."""
        if new["global_skin"]:
            return (
                new["player_skin"] or ctx.pool.default_skin,
                new["player_skin_static"] or ctx.pool.default_static_skin,
            )
        own = (await bot.get_data(ctx.guild_id, db_name=DBModel.guilds))["player_controller"]
        return own["skin"] or ctx.pool.default_skin, own["static_skin"] or ctx.pool.default_static_skin

"""Categoria Links (G-16): links fixos do servidor (``player_controller.fav_links``), escopo por bot.

Espelha o modo ``guild_fav_manager`` de ``utils/music/interactions.py`` (FavModalAdd / FavModalImport). O painel é
mais estrito que o comando em pontos já aprovados: nome duplicado ao adicionar e nomes inexistentes em editar/remover
são recusados, editar nunca renomeia e a importação valida todos os itens.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, NamedTuple, Optional

from empiremuse.panel.services.base import (
    DBModel,
    Args,
    FormContext,
    ParseResult,
    SettingsForm,
    first,
    load_json_object,
)
from empiremuse.rules import limits
from empiremuse.rules.entries import check_name, merge_import, save_entry
from empiremuse.rules.errors import NAME_TAKEN, RuleError
from empiremuse.rules.guild_links import check_description, import_entry
from empiremuse.rules.quota import has_room
from empiremuse.rules.text import clean_import_name
from empiremuse.rules.urls import clean_url

logger = logging.getLogger(__name__)

ACTIONS = ("adicionar", "editar", "remover", "importar")
MSG_ACTION = "Ação desconhecida."
MSG_NO_CHANNEL = "Configure o canal de pedidos primeiro."
MSG_NAME = f"O nome deve ter de {limits.GUILD_LINK_NAME_MIN} a {limits.GUILD_LINK_NAME_MAX} caracteres."
MSG_NAME_TAKEN = "Já existe um link com esse nome."
MSG_NAME_UNKNOWN = "Link não encontrado."
MSG_URL = f"Informe um endereço http(s) válido de {limits.GUILD_LINK_URL_MIN} a {limits.GUILD_LINK_URL_MAX} caracteres."
MSG_DESCRIPTION = (
    f"A descrição deve ficar vazia ou ter de {limits.GUILD_LINK_DESCRIPTION_MIN} a "
    f"{limits.GUILD_LINK_DESCRIPTION_MAX} caracteres."
)
MSG_FULL = f"A lista já tem o máximo de {limits.MAX_GUILD_LINKS} links; remova algum para adicionar outro."
MSG_IMPORT_JSON = "O conteúdo precisa ser um JSON válido, no formato exportado por este painel ou pelo bot."
MSG_IMPORT_EMPTY = "O arquivo não tem nenhum link."
MSG_IMPORT_ITEM = "Um dos itens do arquivo é inválido (nome, URL ou descrição)."
MSG_IMPORT_COUNT = f"O arquivo tem mais de {limits.MAX_GUILD_LINKS} links."
MSG_IMPORT_SPACE = "A lista do servidor não tem espaço suficiente para todos os itens do arquivo."


class LinkView(NamedTuple):
    nome: str
    url: str
    descricao: str


def _links_of(doc: dict) -> dict[str, dict[str, str]]:
    return copy.deepcopy(doc["player_controller"]["fav_links"])


def _error(field: str, message: str, echo: dict[str, Any]) -> ParseResult:
    return ParseResult({}, {field: message}, echo)


def _valid_fields(url_raw: str, description: str, stored: str = "") -> tuple[Optional[str], dict[str, str]]:
    """(URL extraída, erros) com os limites do modal do comando; reenviar a descrição já gravada não é troca."""
    errors: dict[str, str] = {}
    url = None
    if limits.GUILD_LINK_URL_MIN <= len(url_raw) <= limits.GUILD_LINK_URL_MAX:
        url = clean_url(url_raw)
    if url is None:
        errors["url"] = MSG_URL
    if isinstance(check_description(description, stored), RuleError):
        errors["descricao"] = MSG_DESCRIPTION
    return url, errors


class LinksForm(SettingsForm):
    key = "links"
    category = "links"
    fields = ("fav_links",)
    markers = ("acao",)
    template_alias = "estado"

    @property
    def template(self) -> str:
        return "bloco_links.html"

    @property
    def form_id(self) -> str:
        return "bloco-links"

    def extract(self, doc: dict) -> dict[str, Any]:
        return {"fav_links": _links_of(doc)}

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["player_controller"]["fav_links"] = new["fav_links"]

    def aux(self, ctx: FormContext, doc: dict) -> dict[str, Any]:
        return {"canal_configurado": self._has_request_channel(ctx, doc)}

    @staticmethod
    def _has_request_channel(ctx: FormContext, doc: dict) -> bool:
        raw = doc["player_controller"].get("channel")
        if not raw:
            return False
        try:
            return ctx.bot.get_channel(int(raw)) is not None
        except TypeError, ValueError:
            return False

    def display(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        return {"acao_erro": None, "alvo_erro": None, "nome": "", "url": "", "descricao": "", "dados": ""}

    def extras(self, ctx: FormContext, current: dict[str, Any]) -> dict[str, Any]:
        items = tuple(
            LinkView(name, str(data.get("url", "")), str(data.get("description", "")))
            for name, data in current["fav_links"].items()
        )
        return {
            "itens": items,
            "total": len(items),
            "maximo": limits.MAX_GUILD_LINKS,
            "pode_editar": bool(current["canal_configurado"]),
        }

    def parse(self, ctx: FormContext, current: dict[str, Any], args: Args) -> ParseResult:
        action = first(args, "acao") or ""
        name = (first(args, "nome") or "").strip()
        echo = {
            "acao_erro": action,
            "alvo_erro": name if action == "editar" else None,
            "nome": name,
            "url": (first(args, "url") or "").strip(),
            "descricao": (first(args, "descricao") or "").strip(),
            "dados": first(args, "dados") or "",
        }
        if action not in ACTIONS:
            return _error("acao", MSG_ACTION, echo)
        if action != "remover" and not current["canal_configurado"]:
            return _error("acao", MSG_NO_CHANNEL, echo)
        handler = {"adicionar": self._add, "editar": self._edit, "remover": self._remove, "importar": self._import}
        return handler[action](ctx, current["fav_links"], echo)

    def _add(self, ctx: FormContext, links: dict, echo: dict) -> ParseResult:
        name = check_name(
            links, None, echo["nome"], name_min=limits.GUILD_LINK_NAME_MIN, name_max=limits.GUILD_LINK_NAME_MAX
        )
        if isinstance(name, RuleError):
            return _error("nome", MSG_NAME_TAKEN if name.code == NAME_TAKEN else MSG_NAME, echo)
        if not has_room(links, name, limits.MAX_GUILD_LINKS):
            return _error("nome", MSG_FULL, echo)
        url, errors = _valid_fields(echo["url"], echo["descricao"])
        if errors:
            return ParseResult({}, errors, echo)
        return ParseResult({"fav_links": {**links, name: {"url": url, "description": echo["descricao"]}}}, {}, echo)

    def _edit(self, ctx: FormContext, links: dict, echo: dict) -> ParseResult:
        name = echo["nome"]
        if name not in links:
            return _error("nome", MSG_NAME_UNKNOWN, echo)
        url, errors = _valid_fields(echo["url"], echo["descricao"], str(links[name].get("description", "")))
        if errors:
            return ParseResult({}, errors, echo)
        entry = {"url": url, "description": echo["descricao"]}
        saved = save_entry(
            links,
            name,
            name,
            entry,
            name_min=limits.GUILD_LINK_NAME_MIN,
            name_max=limits.GUILD_LINK_NAME_MAX,
            limit=0,
        )
        return ParseResult({"fav_links": saved}, {}, echo)

    def _remove(self, ctx: FormContext, links: dict, echo: dict) -> ParseResult:
        name = echo["nome"]
        if name not in links:
            return _error("nome", MSG_NAME_UNKNOWN, echo)
        return ParseResult({"fav_links": {key: value for key, value in links.items() if key != name}}, {}, echo)

    def _import(self, ctx: FormContext, links: dict, echo: dict) -> ParseResult:
        items, message = self._parse_import(ctx, echo["dados"])
        if message:
            return _error("dados", message, echo)
        merged = merge_import(links, items, limits.MAX_GUILD_LINKS)
        if isinstance(merged, RuleError):
            return _error("dados", MSG_IMPORT_SPACE, echo)
        return ParseResult({"fav_links": merged}, {}, echo)

    @staticmethod
    def _parse_import(ctx: FormContext, raw: str) -> tuple[dict, str]:
        """Itens do JSON no formato do comando (``FavModalImport``), todos validados: ``(itens, "")`` ou ``({}, erro)``."""
        data = load_json_object(raw)
        if data is None:
            return {}, MSG_IMPORT_JSON
        if not data:
            return {}, MSG_IMPORT_EMPTY
        if len(data) > limits.MAX_GUILD_LINKS:
            return {}, MSG_IMPORT_COUNT
        items: dict[str, dict[str, str]] = {}
        for raw_name, item in data.items():
            # colisão após o strip/caixa é recusada
            name = clean_import_name(raw_name, limits.GUILD_LINK_NAME_MIN, limits.GUILD_LINK_NAME_MAX, items)
            clean = import_entry(item)
            if name is None or isinstance(clean, RuleError):
                return {}, MSG_IMPORT_ITEM
            items[name] = clean
        return items, ""

    async def effects(self, ctx: FormContext, current: dict[str, Any], new: dict[str, Any]) -> None:
        # Como o comando: atualiza o embed ocioso do canal de pedidos (no-op se há player ativo).
        from empiremuse.utils.music import interactions

        guild_data = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
        await interactions.process_idle_embed(ctx.bot, ctx.guild, guild_data)

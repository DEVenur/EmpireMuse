"""Seções da conta: favoritos pessoais (U-02, ``fav_links``) e integrações (U-03, ``integration_links``).

Espelham o ``fav_manager`` e o ``integrations_manager`` de ``utils/music/interactions.py`` (FavModalAdd/FavModalImport)
e o ``/fav add``: adicionar usa o modal (nome 2–25, URL 10–200 extraída com ``URL_REG.findall``); importar usa os limites
``USER_FAV_MAX_*`` e grava só o trecho que é URL (``URL_REG.match``). Limites de quantidade vêm de ``bot.config`` a cada
requisição (0 = ilimitado; o dono do bot é isento). Nada aqui faz requisição externa.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional

from empiremuse.panel.services.account_base import AccountContext, AccountSection, Parsed, effective_limit, is_web_link
from empiremuse.panel.services.base import Args, first, load_json_object
from empiremuse.rules.entries import check_name, merge_import, save_entry
from empiremuse.rules.errors import NAME_TAKEN, RuleError
from empiremuse.rules.favorites import check_import_name, name_limit
from empiremuse.rules.limits import (
    FAV_NAME_MAX as FAV_NAME_MAX,
    FAV_NAME_MIN as FAV_NAME_MIN,
    FAV_URL_MAX,
    FAV_URL_MIN,
    ITG_AVATAR_MAX as ITG_AVATAR_MAX,
    ITG_TITLE_MAX as ITG_TITLE_MAX,
    ITG_URL_MAX as ITG_URL_MAX,
)
from empiremuse.rules.quota import has_room
from empiremuse.rules.text import clean_import_name
from empiremuse.rules.urls import extract_url_legacy, url_prefix_legacy

EXPORT_PATH = "/painel/conta/favoritos/exportar"

MSG_NAME = f"O nome deve ter de {FAV_NAME_MIN} a {FAV_NAME_MAX} caracteres, sem quebras de linha."
MSG_NAME_TAKEN = "Você já tem um favorito com esse nome."
MSG_URL = f"Informe um endereço http(s) válido de {FAV_URL_MIN} a {FAV_URL_MAX} caracteres."
MSG_FAV_UNKNOWN = "Favorito não encontrado."
MSG_FAV_FULL = "Você atingiu o limite de favoritos; remova algum para adicionar outro."
MSG_FAV_JSON = 'O conteúdo precisa ser um JSON válido no formato {"nome": "endereço"}.'
MSG_FAV_EMPTY = "O conteúdo não tem nenhum favorito."
MSG_FAV_ITEM = "Um dos itens é inválido (nome, tamanho do endereço ou endereço http/https)."
MSG_FAV_SPACE = "Você não tem espaço para todos os favoritos do conteúdo; remova algum e tente novamente."
MSG_ITG_UNKNOWN = "Integração não encontrada."
MSG_ITG_JSON = "O conteúdo precisa ser um JSON válido no formato exportado pelo bot."
MSG_ITG_EMPTY = "O conteúdo não tem nenhuma integração."
MSG_ITG_ITEM = "Um dos itens é inválido (título, endereço ou imagem)."
MSG_ITG_SPACE = "Você não tem espaço para todas as integrações do conteúdo; remova alguma e tente novamente."


class FavView(NamedTuple):
    nome: str
    url: str
    link: bool


class IntegrationView(NamedTuple):
    titulo: str
    url: str
    avatar: str
    link: bool


def modal_url(raw: str) -> Optional[str]:
    """URL do modal do comando: tamanho 10–200 no texto enviado e primeiro trecho que casa com ``URL_REG``."""
    text = raw.strip()
    if not FAV_URL_MIN <= len(text) <= FAV_URL_MAX:
        return None
    return extract_url_legacy(text)


def import_url(value: Any, max_chars: int) -> Optional[str]:
    """URL do importador: texto, até ``max_chars`` e começando com URL; grava só o trecho que casa."""
    return url_prefix_legacy(value, max_chars)


def _msg_name(name_max: int) -> str:
    """Mensagem do nome inválido; com o teto da configuração abaixo de 25 o limite citado é o dela."""
    return MSG_NAME if name_max == FAV_NAME_MAX else MSG_NAME.replace(str(FAV_NAME_MAX), str(name_max))


def _unknown(echo: dict, message: str) -> Parsed:
    return Parsed({}, {"acao": message}, echo)


class FavoritesSection(AccountSection):
    key = "favoritos"
    actions = ("favorito_adicionar", "favorito_editar", "favorito_remover", "favoritos_importar")

    @staticmethod
    def favs(doc: dict) -> dict[str, Any]:
        return dict(doc.get("fav_links") or {})

    def values(self, doc: dict) -> dict[str, Any]:
        return {"fav_links": self.favs(doc)}

    def defaults(self, doc: dict) -> dict[str, Any]:
        return {"acao_erro": None, "alvo_erro": None, "nome": "", "url": "", "dados": ""}

    async def extras(self, ctx: AccountContext, doc: dict) -> dict[str, Any]:
        favs = self.favs(doc)
        limit = await effective_limit(ctx, "MAX_USER_FAVS")
        items = tuple(FavView(name, str(url), is_web_link(str(url))) for name, url in favs.items())
        return {
            "itens": items,
            "total": len(items),
            "maximo": int(ctx.bot.config["MAX_USER_FAVS"]),
            "ilimitado": limit == 0,
            "cheio": bool(limit) and len(items) >= limit,
            "exportar_url": EXPORT_PATH,
        }

    async def parse(self, ctx: AccountContext, doc: dict, action: str, args: Args) -> Parsed:
        name = (first(args, "nome") or "").strip()
        echo = {
            "acao_erro": action,
            "alvo_erro": name if action in ("favorito_editar", "favorito_remover") else None,
            "nome": name,
            "url": (first(args, "url") or "").strip(),
            "dados": first(args, "dados") or "",
        }
        favs = self.favs(doc)
        if action == "favorito_adicionar":
            return await self._add(ctx, favs, echo)
        if action == "favorito_editar":
            return self._edit(favs, first(args, "nome") or "", echo)
        if action == "favorito_remover":
            return self._remove(favs, first(args, "nome") or "", echo)
        return await self._import(ctx, favs, echo)

    async def _add(self, ctx: AccountContext, favs: dict, echo: dict) -> Parsed:
        errors: dict[str, str] = {}
        name_max = name_limit(ctx.bot.config["USER_FAV_MAX_NAME_LENGTH"])
        name = check_name(favs, None, echo["nome"], name_min=FAV_NAME_MIN, name_max=name_max)
        if isinstance(name, RuleError):
            errors["nome"] = MSG_NAME_TAKEN if name.code == NAME_TAKEN else _msg_name(name_max)
        url = modal_url(echo["url"])
        if url is None:
            errors["url"] = MSG_URL
        limit = await effective_limit(ctx, "MAX_USER_FAVS")
        if not errors and not has_room(favs, name, limit):
            errors["nome"] = MSG_FAV_FULL
        if errors:
            return Parsed({}, errors, echo)
        return Parsed({"fav_links": {**favs, name: url}}, {}, echo)

    @staticmethod
    def _edit(favs: dict, name: str, echo: dict) -> Parsed:
        if name not in favs:
            return _unknown(echo, MSG_FAV_UNKNOWN)
        url = modal_url(echo["url"])
        if url is None:
            return Parsed({}, {"url": MSG_URL}, echo)
        return Parsed(
            {"fav_links": save_entry(favs, name, name, url, name_min=FAV_NAME_MIN, name_max=FAV_NAME_MAX, limit=0)},
            {},
            echo,
        )

    @staticmethod
    def _remove(favs: dict, name: str, echo: dict) -> Parsed:
        if name not in favs:
            return _unknown(echo, MSG_FAV_UNKNOWN)
        return Parsed({"fav_links": {key: value for key, value in favs.items() if key != name}}, {}, echo)

    async def _import(self, ctx: AccountContext, favs: dict, echo: dict) -> Parsed:
        data = load_json_object(echo["dados"])
        if data is None:
            return Parsed({}, {"dados": MSG_FAV_JSON}, echo)
        if not data:
            return Parsed({}, {"dados": MSG_FAV_EMPTY}, echo)
        config = ctx.bot.config
        items = self._import_items(
            data, int(config["USER_FAV_MAX_NAME_LENGTH"]), int(config["USER_FAV_MAX_URL_LENGTH"])
        )
        if items is None:
            return Parsed({}, {"dados": MSG_FAV_ITEM}, echo)
        limit = await effective_limit(ctx, "MAX_USER_FAVS")
        merged = merge_import(favs, items, limit)  # sobrescrever (sem diferenciar a caixa) não ocupa vaga
        if isinstance(merged, RuleError):
            return Parsed({}, {"dados": MSG_FAV_SPACE}, echo)
        return Parsed({"fav_links": merged}, {}, echo)

    @staticmethod
    def _import_items(data: dict, max_name: int, max_url: int) -> Optional[dict[str, str]]:
        items: dict[str, str] = {}
        for raw_name, raw_url in data.items():
            name = check_import_name(raw_name, items, max_name)  # nomes que colidem após o strip/caixa são recusados
            url = import_url(raw_url, max_url)
            if isinstance(name, RuleError) or url is None:
                return None
            items[name] = url
        return items

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["fav_links"] = new["fav_links"]


class IntegrationsSection(AccountSection):
    key = "integracoes"
    actions = ("integracao_remover", "integracoes_importar")

    @staticmethod
    def links(doc: dict) -> dict[str, Any]:
        return dict(doc.get("integration_links") or {})

    def values(self, doc: dict) -> dict[str, Any]:
        return {"integration_links": self.links(doc)}

    def defaults(self, doc: dict) -> dict[str, Any]:
        return {"acao_erro": None, "alvo_erro": None, "dados": ""}

    async def extras(self, ctx: AccountContext, doc: dict) -> dict[str, Any]:
        limit = await effective_limit(ctx, "MAX_USER_INTEGRATIONS")
        items = tuple(self._view(title, value) for title, value in self.links(doc).items())
        return {
            "itens": items,
            "total": len(items),
            "maximo": int(ctx.bot.config["MAX_USER_INTEGRATIONS"]),
            "ilimitado": limit == 0,
            "cheio": bool(limit) and len(items) >= limit,
        }

    @staticmethod
    def _view(title: str, value: Any) -> IntegrationView:
        data = value if isinstance(value, dict) else {"url": value}  # o comando guarda objeto; o importador, texto
        url, avatar = str(data.get("url") or ""), str(data.get("avatar") or "")
        return IntegrationView(title, url, avatar, is_web_link(url))

    async def parse(self, ctx: AccountContext, doc: dict, action: str, args: Args) -> Parsed:
        echo = {
            "acao_erro": action,
            "alvo_erro": first(args, "nome") if action == "integracao_remover" else None,
            "dados": first(args, "dados") or "",
        }
        links = self.links(doc)
        if action == "integracao_remover":
            name = first(args, "nome") or ""
            if name not in links:
                return _unknown(echo, MSG_ITG_UNKNOWN)
            return Parsed({"integration_links": {key: value for key, value in links.items() if key != name}}, {}, echo)
        return await self._import(ctx, links, echo)

    async def _import(self, ctx: AccountContext, links: dict, echo: dict) -> Parsed:
        data = load_json_object(echo["dados"])
        if data is None:
            return Parsed({}, {"dados": MSG_ITG_JSON}, echo)
        if not data:
            return Parsed({}, {"dados": MSG_ITG_EMPTY}, echo)
        items = self._import_items(data)
        if items is None:
            return Parsed({}, {"dados": MSG_ITG_ITEM}, echo)
        limit = await effective_limit(ctx, "MAX_USER_INTEGRATIONS")
        merged = merge_import(links, items, limit)
        if isinstance(merged, RuleError):
            return Parsed({}, {"dados": MSG_ITG_SPACE}, echo)
        return Parsed({"integration_links": merged}, {}, echo)

    @staticmethod
    def _import_items(data: dict) -> Optional[dict[str, dict[str, str]]]:
        """Aceita texto-URL (formato do importador do comando) e ``{url, avatar?}`` (formato do próprio export)."""
        items: dict[str, dict[str, str]] = {}
        for raw_title, raw_value in data.items():
            title = clean_import_name(raw_title, 1, ITG_TITLE_MAX, items)
            entry = IntegrationsSection._entry(raw_value)
            if title is None or entry is None:
                return None
            items[title] = entry
        return items

    @staticmethod
    def _entry(value: Any) -> Optional[dict[str, str]]:
        if isinstance(value, dict):
            url, avatar = import_url(value.get("url"), ITG_URL_MAX), value.get("avatar")
        else:
            url, avatar = import_url(value, ITG_URL_MAX), None
        if url is None:
            return None
        if avatar in (None, ""):
            return {"url": url}
        avatar_url = import_url(avatar, ITG_AVATAR_MAX)
        return {"url": url, "avatar": avatar_url} if avatar_url else None

    def apply(self, doc: dict, new: dict[str, Any]) -> None:
        doc["integration_links"] = new["integration_links"]

# -*- coding: utf-8 -*-
# KI-29: módulo acima de 800 linhas por exceção transitória. Ainda guarda os favoritos e o editor de skins, que saem
# nos PRs seguintes (favorites_texts/fav_modals/fav_menu e skin_editor); no fim fica só com reexportações.
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from copy import deepcopy
from io import BytesIO
from itertools import islice
from typing import Union, Optional, TYPE_CHECKING, Literal

import disnake

from empiremuse.rules.entries import merge_import, save_entry
from empiremuse.rules.errors import (
    AVATAR_INVALID,
    DESCRIPTION_INVALID,
    DESCRIPTION_TOO_LONG,
    FILE_TOO_LARGE,
    ITEM_FORMAT,
    NAME_TAKEN,
    NAME_TOO_LONG,
    QUOTA_FULL,
    URL_TOO_LONG,
    RuleError,
)
from empiremuse.rules.favorites import check_import_name, name_limit
from empiremuse.rules.guild_links import check_description, import_entry as guild_link_entry
from empiremuse.rules.integrations import import_entry as integration_entry, save_external
from empiremuse.rules.limits import (
    FAV_NAME_MAX,
    FAV_NAME_MIN,
    FAV_URL_MAX,
    GUILD_LINK_DESCRIPTION_MAX,
    GUILD_LINK_URL_MAX,
    GUILD_LINK_NAME_MAX,
    GUILD_LINK_NAME_MIN,
    ITG_TITLE_MAX,
    ITG_URL_MAX,
    MAX_GUILD_LINKS,
)
from empiremuse.rules.text import clean_import_name
from empiremuse.rules.urls import check_url, clean_url
from empiremuse.utils.db import DBModel
from empiremuse.utils.music.audio_sources.deezer import deezer_regex
from empiremuse.utils.music.audio_sources.spotify import spotify_regex_w_user
from empiremuse.utils.music.checks import check_pool_bots
from empiremuse.utils.music.converters import time_format, fix_characters
from empiremuse.utils.music.errors import GenericError, error_code_text, log_unexpected_error
from empiremuse.serialization.schema import SchemaError
from empiremuse.serialization.skins import MAX_SKINS_PER_MODE, validate_skin, validate_skin_name
from empiremuse.utils.music.skin_store import load_custom_skins
from empiremuse.utils.music.skin_utils import skin_converter
from empiremuse.utils.music.user_limits import quota_for
from empiremuse.utils.others import (
    CustomContext,
    music_source_emoji_url,
    PlayerControls,
    get_source_emoji_cfg,
    paginator,
)

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

from empiremuse.utils.music.interactions.common import (
    youtube_regex as youtube_regex,
    soundcloud_regex as soundcloud_regex,
    process_idle_embed as process_idle_embed,
    ViewMode as ViewMode,
    IMPORT_ECHO_LIMIT as IMPORT_ECHO_LIMIT,
)
from empiremuse.utils.music.interactions.view_modal import (
    ViewModal as ViewModal,
)
from empiremuse.utils.music.interactions.player_views import (
    VolumeInteraction as VolumeInteraction,
    QueueInteraction as QueueInteraction,
    EmbedPaginatorInteraction as EmbedPaginatorInteraction,
    ButtonInteraction as ButtonInteraction,
    SelectInteraction as SelectInteraction,
    AskView as AskView,
    SelectBotVoice as SelectBotVoice,
)
from empiremuse.utils.music.interactions.stage_title import (
    SetStageTitle as SetStageTitle,
)

logger = logging.getLogger(__name__)

SKIN_NAME_REFUSED = (
    "**O nome da skin precisa ter de 1 a 64 caracteres, sem pontos, cifrão nem caracteres invisíveis ou de controle.**"
)
SKIN_REFUSED = (
    "**Não foi possível salvar a skin: algum campo passa dos limites ou tem conteúdo inválido. "
    "Revise o texto, os embeds e os campos e tente de novo.**"
)
SKIN_LIMIT_REFUSED = (
    "**Não foi possível salvar: cada modo comporta no máximo 25 skins. Exclua uma ou salve por cima de uma existente.**"
)


def _echo(value, limit: int = IMPORT_ECHO_LIMIT) -> str:
    """Trecho de um valor do arquivo importado para mensagens: curto e sem crases (não fecha o bloco de código)."""
    text = str(value).replace("`", "'")
    return text if len(text) <= limit else f"{text[:limit]}…"


def _invalid_link_text(value) -> str:
    return f"O seu arquivo contém link inválido: ```ldif\n{_echo(value)}```"


def _invalid_name_text(name, low: int, high: int) -> str:
    return (
        f"**O nome `{_echo(name, 40)}` do seu arquivo é inválido ou está repetido:** use de {low} a {high} "
        "caracteres, sem caracteres de controle e sem repetir nomes (maiúsculas e minúsculas contam como iguais)."
    )


def _url_error_text(error: RuleError, *, with_label: bool = False) -> str:
    """Mensagem de uma URL de arquivo recusada: longa demais (cita o limite) ou inválida."""
    if error.code == URL_TOO_LONG:
        if with_label:
            return (
                f"**Um item de seu arquivo ultrapassa a quantidade de caracteres permitido:{error.limit}\n"
                f"URL:** {_echo(error.value)}"
            )
        return (
            f"**Um item de seu arquivo {_echo(error.value)} ultrapassa a quantidade de caracteres "
            f"permitido:{error.limit}**"
        )
    return _invalid_link_text(error.value)


def _guild_link_error_text(name, error: RuleError) -> str:
    """Mensagem de um item de link do servidor recusado: formato, URL ou descrição."""
    if error.code == ITEM_FORMAT:
        return (
            f"**O item `{_echo(name, 25)}` do seu arquivo está mal formatado:** cada item precisa ser um "
            'objeto com os campos "url" e "description" em texto.'
        )
    if error.code == DESCRIPTION_TOO_LONG:
        return (
            f"**Um item de seu arquivo ultrapassa a quantidade de caracteres permitido:{error.limit}\n"
            f"Descrição:** {_echo(error.value)}"
        )
    if error.code == DESCRIPTION_INVALID:
        return (
            "**A descrição de um item do seu arquivo deve ficar vazia ou ter de 3 a 100 caracteres, "
            f"sem caracteres de controle:** {_echo(error.value)}"
        )
    return _url_error_text(error, with_label=True)


def _name_error_text(error: RuleError, low: int, high: int) -> str:
    """Mensagem de um nome de arquivo recusado: acima do teto da configuração ou inválido/repetido."""
    if error.code == NAME_TOO_LONG:
        return (
            f"**Um item de seu arquivo ({_echo(error.value)}) ultrapassa a quantidade de caracteres "
            f"permitido:{error.limit}**"
        )
    return _invalid_name_text(error.value, low, high)


def _save_error_text(error: RuleError, low: int, high: int, taken: str) -> str:
    """Mensagem de uma recusa ao salvar um favorito/link pelo modal (``taken``: texto do nome repetido)."""
    if error.code == NAME_TAKEN:
        return f"**{taken}**"
    if error.code == QUOTA_FULL:
        return "**Não há espaço disponível para adicionar novos favorito (remova algum e tente novamente).**"
    return f"**O nome informado é inválido: use de {low} a {high} caracteres, sem caracteres de controle.**"


_IMPORT_QUOTA_TEXTS = {
    "favoritos": (
        "A quantidade de itens no seu arquivo de favorito excede a quantidade máxima permitida ({limit}).",
        "Você não possui espaço suficiente para adicionar todos os favoritos de seu arquivo...",
        "Quantidade de favoritos salvos",
    ),
    "integrações": (
        "A quantidade de itens no seu arquivo de integrações excede a quantidade máxima permitida ({limit}).",
        "Você não possui espaço suficiente para adicionar todos as integrações de seu arquivo...",
        "Quantidade de integrações salvas",
    ),
    "links": (
        "A quantidade de itens no arquivo excede a quantidade máxima permitida ({limit}).",
        "A lista de músicas/playlist do servidor não possui espaço suficiente para adicionar todos os itens de seu arquivo...",
        "Quantidade de links salvos",
    ),
}


def _import_quota_text(error: RuleError, kind: str) -> str:
    """Mensagem de cota de uma importação (``kind``: favoritos, integrações ou links)."""
    too_large, no_space, saved = _IMPORT_QUOTA_TEXTS[kind]
    if error.code == FILE_TOO_LARGE:
        return too_large.format(limit=error.limit)
    kept, incoming = error.value
    return f"{no_space}\nLimite atual: {error.limit}\n{saved}: {kept}\nVocê precisa de: {kept + incoming - error.limit}"


_NO_ROOM_INTEGRATION_TEXT = (
    "**Não há espaço disponível para adicionar novas integrações (remova alguma e tente novamente).**"
)


def _retry_text(retry_after: float) -> str:
    """Mensagem neutra do cooldown ao adicionar uma integração (o balde é o do importador, mas não é uma importação)."""
    return "**Aguarde {} antes de tentar novamente.**".format(
        time_format(int(max(retry_after, 1)) * 1000, use_names=True)
    )


def _wait_text(retry_after: float) -> str:
    """Mensagem do cooldown por membro do importador (a do exportador e a do modal de integração são outras)."""
    return "**Você deve aguardar {} para importar.**".format(
        time_format(int(max(retry_after, 1)) * 1000, use_names=True)
    )


def _profile_source(url: str) -> Optional[str]:
    """De onde vem o perfil do link (``spotify``, ``deezer``, ``youtube`` ou ``soundcloud``), ou ``None`` se não é suportado."""
    if spotify_regex_w_user.match(url):
        return "spotify"
    if deezer_regex.match(url):
        return "deezer"
    if youtube_regex.search(url):
        return "youtube"
    if soundcloud_regex.search(url):
        return "soundcloud"
    return None


def _profile_key(url) -> Optional[tuple]:
    """Identifica o perfil de um link (fonte e id), para saber se duas URLs diferentes são do mesmo perfil."""
    if not isinstance(url, str):
        return None
    if match := spotify_regex_w_user.match(url):
        return "spotify", match.groups()[-1]
    if match := deezer_regex.match(url):
        return "deezer", match.groups()[-1]
    if match := youtube_regex.search(url):
        return "youtube", match.group(0).lower()
    if match := soundcloud_regex.search(url):
        return "soundcloud", match.group(1).lower()
    return None


def _profile_saved(entries: dict, url: str) -> bool:
    """Alguma integração já salva é do mesmo perfil do link (gravar de novo sobrescreve, não ocupa vaga)?"""
    key = _profile_key(url)
    return key is not None and any(
        _profile_key(entry.get("url") if isinstance(entry, dict) else entry) == key for entry in entries.values()
    )


class FavModalImport(disnake.ui.Modal):
    def __init__(self, view):
        self.view = view

        if self.view.mode == ViewMode.fav_manager:
            super().__init__(
                title="Importar Favoritos",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Inserir dados (em formato json)",
                        custom_id="json_data",
                        min_length=20,
                        required=True,
                    )
                ],
            )
            return

        if self.view.mode == ViewMode.guild_fav_manager:
            super().__init__(
                title="Importar Playlists para o Servidor",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Inserir dados (em formato json)",
                        custom_id="json_data",
                        min_length=20,
                        required=True,
                    )
                ],
            )
            return

        if self.view.mode == ViewMode.integrations_manager:
            super().__init__(
                title="Importar integração",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Inserir dados (em formato json)",
                        custom_id="json_data",
                        min_length=20,
                        required=True,
                    )
                ],
            )
            return

        raise GenericError(f"Modo atual ainda não implementado: {self.view.mode} | {type(self.view.mode)}")

    async def _reject_rate_limited(self, inter: disnake.ModalInteraction, retry_after: float) -> None:
        await inter.send(_wait_text(retry_after), ephemeral=True)

    async def callback(self, inter: disnake.ModalInteraction, /) -> None:
        try:
            json_data = json.loads(inter.text_values["json_data"])
        except (ValueError, RecursionError):
            logger.exception("Importação de favoritos/links/integrações: JSON inválido")
            await inter.send(
                "**Ocorreu um erro ao analisar os dados ou foi enviado dados inválidos/não-formatado "
                "em formato json.**",
                ephemeral=True,
            )
            return

        if not isinstance(json_data, dict) or not json_data:
            await inter.send(
                "**O arquivo precisa conter um objeto json com pelo menos um item.**",
                ephemeral=True,
            )
            return

        importers = {
            ViewMode.fav_manager: self._import_favorites,
            ViewMode.guild_fav_manager: self._import_guild_links,
            ViewMode.integrations_manager: self._import_integrations,
        }

        if (importer := importers.get(self.view.mode)) is None:
            raise GenericError(f"**Modo ainda não implementado: {self.view.mode} | {type(self.view.mode)}**")

        if retry_after := self.view.bot.get_cog("Music").fav_import_export_cd.get_bucket(inter).update_rate_limit():
            await self._reject_rate_limited(inter, retry_after)
            return

        if not await importer(inter, json_data):
            return

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(content=self.view.build_txt(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(content=self.view.build_txt(), view=self.view)

    async def _import_favorites(self, inter: disnake.ModalInteraction, json_data: dict) -> bool:
        clean_data = {}

        for name, url in json_data.items():
            url = check_url(url, self.view.bot.config["USER_FAV_MAX_URL_LENGTH"])

            if isinstance(url, RuleError):
                await inter.send(_url_error_text(url), ephemeral=True)
                return False

            clean_name = check_import_name(name, clean_data, self.view.bot.config["USER_FAV_MAX_NAME_LENGTH"])

            if isinstance(clean_name, RuleError):
                await inter.send(_name_error_text(clean_name, FAV_NAME_MIN, FAV_NAME_MAX), ephemeral=True)
                return False

            clean_data[clean_name] = url

        await inter.response.defer(ephemeral=True)

        work = deepcopy(await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users))

        limit = await quota_for(self.view.bot, inter.author, "MAX_USER_FAVS")

        merged = merge_import(work["fav_links"], clean_data, limit)

        if isinstance(merged, RuleError):
            await inter.edit_original_message(_import_quota_text(merged, "favoritos"))
            return False

        work["fav_links"] = merged
        self.view.data = work  # só depois de todas as checagens: uma recusa não altera a tela

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        await inter.edit_original_message(content="**Favoritos importados com sucesso!**")

        if (s := len(clean_data)) > 1:
            self.view.log = f"{s} favoritos foram importados com sucesso."
        else:
            name = next(iter(clean_data))
            self.view.log = f"O favorito [`{name}`]({clean_data[name]}) foi importado com sucesso."

        return True

    async def _import_guild_links(self, inter: disnake.ModalInteraction, json_data: dict) -> bool:
        clean_data = {}

        for name, data in json_data.items():
            entry = guild_link_entry(data)

            if isinstance(entry, RuleError):
                await inter.send(_guild_link_error_text(name, entry), ephemeral=True)
                return False

            if (clean_name := clean_import_name(name, FAV_NAME_MIN, FAV_NAME_MAX, clean_data)) is None:
                await inter.send(_invalid_name_text(name, FAV_NAME_MIN, FAV_NAME_MAX), ephemeral=True)
                return False

            clean_data[clean_name] = entry

        await inter.response.defer(ephemeral=True)

        work = deepcopy(await self.view.bot.get_data(inter.guild_id, db_name=DBModel.guilds))

        if not work["player_controller"]["channel"] or not self.view.bot.get_channel(
            int(work["player_controller"]["channel"])
        ):
            await inter.edit_original_message("**Não há player configurado no servidor! Use o comando /setup**")
            return False

        merged = merge_import(work["player_controller"]["fav_links"], clean_data, MAX_GUILD_LINKS)

        if isinstance(merged, RuleError):
            await inter.edit_original_message(_import_quota_text(merged, "links"))
            return False

        work["player_controller"]["fav_links"] = merged
        self.view.guild_data = work  # só depois de todas as checagens: uma recusa não altera a tela

        await self.view.bot.update_data(inter.guild_id, self.view.guild_data, db_name=DBModel.guilds)

        guild = self.view.bot.get_guild(inter.guild_id)

        await inter.edit_original_message(content="**Links fixos do servidor foram importados com sucesso!**")

        if (s := len(clean_data)) > 1:
            self.view.log = f"{s} links foram importados com sucesso para a lista de favoritos do servidor."
        else:
            name = next(iter(clean_data))
            self.view.log = f"O link [`{name}`]({clean_data[name]['url']}) foi importado com sucesso para a lista de links do servidor.."

        await process_idle_embed(self.view.bot, guild, guild_data=self.view.guild_data)

        return True

    async def _import_integrations(self, inter: disnake.ModalInteraction, json_data: dict) -> bool:
        clean_data = {}

        for name, value in json_data.items():
            entry = integration_entry(value)

            if isinstance(entry, RuleError):
                text = _invalid_link_text(entry.value) if entry.code == AVATAR_INVALID else _url_error_text(entry)
                await inter.send(text, ephemeral=True)
                return False

            if (clean_name := clean_import_name(name, 1, ITG_TITLE_MAX, clean_data)) is None:
                await inter.send(_invalid_name_text(name, 1, ITG_TITLE_MAX), ephemeral=True)
                return False

            clean_data[clean_name] = entry

        await inter.response.defer(ephemeral=True)

        work = deepcopy(await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users))

        limit = await quota_for(self.view.bot, inter.author, "MAX_USER_INTEGRATIONS")

        merged = merge_import(work["integration_links"], clean_data, limit)

        if isinstance(merged, RuleError):
            await inter.edit_original_message(_import_quota_text(merged, "integrações"))
            return False

        work["integration_links"] = merged
        self.view.data = work  # só depois de todas as checagens: uma recusa não altera a tela

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        await inter.edit_original_message(content="**Integrações importadas com sucesso!**")

        if (s := len(clean_data)) > 1:
            self.view.log = f"{s} integrações foram importadas com sucesso."
        else:
            name = next(iter(clean_data))
            self.view.log = f"A integração [`{name}`]({clean_data[name]['url']}) foi importada com sucesso."

        return True


def _spotify_profile(result: dict, user_id: str, url: str) -> dict:
    """Título, URL e avatar da resposta do Spotify; perfil sem nome, sem imagem ou sem link não quebra (N-4)."""
    name = str(result.get("display_name") or "").strip() or user_id
    profile = {"title": f"[SP]: {name[:90]}", "url": (result.get("external_urls") or {}).get("spotify") or url}
    images = result.get("images") or []
    if images and isinstance(images[-1], dict) and images[-1].get("url"):
        profile["avatar"] = images[-1]["url"]
    return profile


class FavModalAdd(disnake.ui.Modal):
    def __init__(self, name: Optional[str], url: Optional[str], view, **kwargs):
        self.view = view
        self.name = name

        if self.view.mode == ViewMode.fav_manager:
            super().__init__(
                title="Adicionar/Editar playlist/favorito",
                custom_id="user_fav_edit",
                timeout=180,
                components=[
                    disnake.ui.TextInput(
                        label="Nome da playlist/favorito:",
                        custom_id="user_fav_name",
                        min_length=2,
                        max_length=25,
                        value=name or None,
                    ),
                    disnake.ui.TextInput(
                        label="Link/Url:", custom_id="user_fav_url", min_length=10, max_length=200, value=url or None
                    ),
                ],
            )
            return

        if self.view.mode == ViewMode.guild_fav_manager:
            super().__init__(
                title="Adicionar/Editar playlist/favorito",
                custom_id="guild_fav_edit",
                timeout=180,
                components=[
                    disnake.ui.TextInput(
                        label="Nome do favorito/playlist:",
                        custom_id="guild_fav_name",
                        min_length=2,
                        max_length=25,
                        value=name or None,
                    ),
                    disnake.ui.TextInput(
                        label="Descrição:",
                        custom_id="guild_fav_description",
                        min_length=3,
                        max_length=GUILD_LINK_DESCRIPTION_MAX,
                        value=kwargs.get("description", None),
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        label="Link/Url:", custom_id="guild_fav_url", min_length=10, max_length=250, value=url or None
                    ),
                ],
            )
            return

        if self.view.mode == ViewMode.integrations_manager:
            super().__init__(
                title="Adicionar integração",
                custom_id="user_integration_add",
                timeout=180,
                components=[
                    disnake.ui.TextInput(
                        label="Link/Url:",
                        custom_id="user_integration_url",
                        min_length=10,
                        max_length=200,
                        value=url or None,
                    ),
                ],
            )
            return

        raise GenericError(f"**Modo ainda não implementado: {self.view.mode} | {type(self.view.mode)}**")

    async def callback(self, inter: disnake.ModalInteraction):
        if self.view.mode == ViewMode.fav_manager:
            url = inter.text_values["user_fav_url"].strip()

            if (valid_url := clean_url(url, FAV_URL_MAX)) is None:
                await inter.send(
                    embed=disnake.Embed(
                        description=f"**Nenhum link válido encontrado:** {_echo(url)}", color=disnake.Color.red()
                    ),
                    ephemeral=True,
                )
                return

            await inter.response.defer(ephemeral=True)

            work = deepcopy(await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users))

            name_max = name_limit(self.view.bot.config["USER_FAV_MAX_NAME_LENGTH"])
            limit = await quota_for(self.view.bot, inter.author, "MAX_USER_FAVS")

            saved = save_entry(
                work["fav_links"],
                self.name,
                inter.text_values["user_fav_name"],
                valid_url,
                name_min=FAV_NAME_MIN,
                name_max=name_max,
                limit=limit,
            )

            if isinstance(saved, RuleError):
                await inter.edit_original_message(
                    _save_error_text(saved, FAV_NAME_MIN, name_max, "Você já tem um favorito com esse nome.")
                )
                return

            work["fav_links"] = saved
            self.view.data = work  # só depois de todas as checagens: uma recusa não altera a tela

            await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

            try:
                me = (inter.guild or self.view.bot.get_guild(inter.guild_id)).me
            except AttributeError:
                me = None

            await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**Link salvo/atualizado com sucesso nos seus favoritos!\n"
                    "Ele vai aparecer nas seguintes ocasições:** ```\n"
                    "- Ao usar o comando /play (selecionando no preenchimento automático da busca)\n"
                    "- Ao clicar no botão de tocar favorito do player.\n"
                    "- Ao usar o comando play (prefixed) sem nome ou link.```",
                    color=self.view.bot.get_color(me),
                )
            )

        elif self.view.mode == ViewMode.guild_fav_manager:
            url = inter.text_values["guild_fav_url"].strip()

            if (valid_url := clean_url(url, GUILD_LINK_URL_MAX)) is None:
                await inter.send(
                    embed=disnake.Embed(
                        description=f"**Nenhum link válido encontrado:** {_echo(url)}", color=disnake.Color.red()
                    ),
                    ephemeral=True,
                )
                return

            description = check_description(inter.text_values["guild_fav_description"])

            if isinstance(description, RuleError):
                await inter.send(
                    "**A descrição deve ficar vazia ou ter de 3 a 100 caracteres, sem caracteres de controle.**",
                    ephemeral=True,
                )
                return

            await inter.response.defer(ephemeral=True)

            work = deepcopy(await self.view.bot.get_data(inter.guild_id, db_name=DBModel.guilds))

            if not work["player_controller"]["channel"] or not self.view.bot.get_channel(
                int(work["player_controller"]["channel"])
            ):
                await inter.edit_original_message("**Não há player configurado no servidor! Use o comando /setup**")
                return

            saved = save_entry(
                work["player_controller"]["fav_links"],
                self.name,
                inter.text_values["guild_fav_name"],
                {"url": valid_url, "description": description},
                name_min=GUILD_LINK_NAME_MIN,
                name_max=GUILD_LINK_NAME_MAX,
                limit=MAX_GUILD_LINKS,
            )

            if isinstance(saved, RuleError):
                await inter.edit_original_message(
                    _save_error_text(
                        saved, GUILD_LINK_NAME_MIN, GUILD_LINK_NAME_MAX, "Já existe um link com esse nome."
                    )
                )
                return

            work["player_controller"]["fav_links"] = saved
            self.view.guild_data = work  # só depois de todas as checagens: uma recusa não altera a tela

            await self.view.bot.update_data(inter.guild_id, self.view.guild_data, db_name=DBModel.guilds)

            guild = inter.guild or self.view.bot.get_guild(inter.guild_id)

            await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**Link adicionado/atualizado com sucesso nos fixos do player!\n"
                    "Membros podem usá-lo diretamente no player-controller quando não estiver em uso.**",
                    color=self.view.bot.get_color(guild.me),
                ),
                view=None,
            )

            await process_idle_embed(self.view.bot, guild, guild_data=self.view.guild_data)

        elif self.view.mode == ViewMode.integrations_manager:
            if not await self._add_integration(inter):
                return

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(content=self.view.build_txt(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(content=self.view.build_txt(), view=self.view)

    async def _add_integration(self, inter: disnake.ModalInteraction) -> bool:
        """Adiciona/edita uma integração a partir do link de um perfil; ``False`` se nada foi gravado."""
        try:
            await inter.response.defer(ephemeral=True, with_message=True)
        except (disnake.HTTPException, disnake.InteractionResponded):
            pass

        work = deepcopy(await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users))

        typed_url = inter.text_values["user_integration_url"].strip()

        if (url := clean_url(typed_url, ITG_URL_MAX)) is None:
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description=f"**Nenhum link válido encontrado:** {_echo(typed_url)}", color=disnake.Color.red()
                )
            )
            return False

        if (source := _profile_source(url)) is None:
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description=f"**Link informado não é suportado:** {_echo(url)}", color=disnake.Color.red()
                )
            )
            return False

        # antes de qualquer consulta externa: o cooldown por membro e a lista cheia com um perfil que ainda não está salvo
        if retry_after := self.view.bot.get_cog("Music").fav_import_export_cd.get_bucket(inter).update_rate_limit():
            await inter.edit_original_message(_retry_text(retry_after))
            return False

        limit = await quota_for(self.view.bot, inter.author, "MAX_USER_INTEGRATIONS")

        if limit and len(work["integration_links"]) >= limit and not _profile_saved(work["integration_links"], url):
            await inter.edit_original_message(_NO_ROOM_INTEGRATION_TEXT)
            return False

        if (data := await self._lookup_profile(inter, url, source)) is None:
            return False

        saved = save_external(
            work["integration_links"],
            fix_characters(data["title"], 80),
            data.get("url"),
            data.get("avatar"),
            limit=limit,
        )

        if isinstance(saved, RuleError):
            await inter.edit_original_message(
                _NO_ROOM_INTEGRATION_TEXT
                if saved.code == QUOTA_FULL
                else "**Não foi possível usar os dados devolvidos pelo serviço. Tente novamente mais tarde.**"
            )
            return False

        work["integration_links"] = saved.entries
        self.view.data = work  # só depois de todas as checagens: uma recusa não altera a tela

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        try:
            me = (inter.guild or self.view.bot.get_guild(inter.guild_id)).me
        except AttributeError:
            me = None

        await inter.edit_original_message(
            embed=disnake.Embed(
                description=f"**Integração adicionada/editada com sucesso:** [`{saved.name}`]({saved.url})\n"
                "**Ela vai aparecer nas seguintes ocasições:** ```\n"
                "- Ao usar o comando /play (selecionando a integração no preenchimento automático da busca)\n"
                "- Ao clicar no botão de tocar favorito do player.\n"
                "- Ao usar o comando play (prefixed) sem nome ou link.```",
                color=self.view.bot.get_color(me),
            ),
            view=None,
        )

        self.view.log = f"[`{saved.name}`](<{saved.url}>) foi adicionado nas suas integrações."

        return True

    async def _lookup_profile(self, inter: disnake.ModalInteraction, url: str, source: str) -> Optional[dict]:
        """Consulta o perfil no Spotify, Deezer ou yt-dlp (``source``); ``None`` (com a mensagem já enviada) se falhar."""
        if source == "spotify":
            return await self._lookup_spotify(inter, url)

        if source == "deezer":
            return await self._lookup_deezer(inter, url)

        return await self._lookup_ytdl(inter, url, source)

    async def _lookup_spotify(self, inter: disnake.ModalInteraction, url: str) -> Optional[dict]:
        if not self.view.bot.spotify:
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**O suporte ao spotify não está disponível no momento...**",
                    color=disnake.Color.red(),
                )
            )
            return None

        url_type, user_id = spotify_regex_w_user.match(url).groups()

        if url_type != "user":
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description=f"**Você deve usar link de um perfil de usuário do spotify.** {_echo(url)}",
                    color=disnake.Color.red(),
                )
            )
            return None

        try:
            result = await self.view.bot.spotify.get_user_info(user_id)
            profile = _spotify_profile(result, user_id, url) if result else None
        except Exception as e:  # inclui resposta que não é um dict: mensagem genérica, o detalhe só vai para o log
            code = log_unexpected_error(logger, e, "integração: consulta do perfil (spotify)")
            await self._profile_error(inter, code)
            return None

        if not profile:
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**O usuário do link informado não possui playlists públicas...**",
                    color=self.view.bot.get_color(),
                )
            )
            return None

        return profile

    async def _lookup_deezer(self, inter: disnake.ModalInteraction, url: str) -> Optional[dict]:
        url_type, url_id = deezer_regex.match(url).groups()[-2:]

        if url_type != "profile":
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description=f"**Você deve usar link de um perfil de usuário do deezer.** {_echo(url)}",
                    color=disnake.Color.red(),
                )
            )
            return None

        try:
            result = await self.view.bot.deezer.get_user_info(int(url_id))
            return {"title": f"[DZ]: {result['name'][:90]}", "url": result["link"], "avatar": result["picture"]}
        except Exception as e:  # inclui resposta sem name/link/picture ou que não é um dict (ex.: erro da API)
            code = log_unexpected_error(logger, e, "integração: consulta do perfil (deezer)")
            await self._profile_error(inter, code)
            return None

    async def _lookup_ytdl(self, inter: disnake.ModalInteraction, url: str, source: str) -> Optional[dict]:
        if source == "youtube":
            base_url, label = f"{youtube_regex.search(url).group(0)}/playlists", "[YT]:"
        else:
            base_url, label = f"https://soundcloud.com/{soundcloud_regex.search(url).group(1)}/sets", "[SC]:"

        loop = self.view.bot.loop or asyncio.get_event_loop()

        try:
            info = await loop.run_in_executor(
                None, lambda: self.view.bot.pool.ytdl.extract_info(base_url, download=False)
            )
        except Exception as e:
            code = log_unexpected_error(logger, e, "integração: leitura da URL com o yt-dlp")
            await inter.edit_original_message(
                "**Ocorreu um erro ao obter informação da url. Tente novamente mais tarde.**" + error_code_text(code)
            )
            return None

        if not info:
            msg = f"**O usuário/canal do link informado não existe:**\n{_echo(url)}"

            if label == "[YT]:":
                msg += "\n\n`Nota: Confira se no link contém usuário com @, ex: @ytchannel`"

            await inter.edit_original_message(embed=disnake.Embed(description=msg, color=disnake.Color.red()))
            return None

        if not info["entries"]:
            await inter.edit_original_message(
                embed=disnake.Embed(
                    description="**O usuário/canal do link informado não possui playlists públicas...**",
                    color=disnake.Color.red(),
                )
            )
            return None

        return {"title": f"{label} {info['title']}", "url": info["original_url"]}

    async def _profile_error(self, inter: disnake.ModalInteraction, error_code: str = "") -> None:
        await inter.edit_original_message(
            embed=disnake.Embed(
                description="**Ocorreu um erro ao obter as informações do perfil. Tente novamente mais tarde.**"
                + error_code_text(error_code),
                color=self.view.bot.get_color(),
            )
        )


class FavMenuView(disnake.ui.View):
    def __init__(
        self,
        bot: BotCore,
        ctx: Union[disnake.ApplicationCommandInteraction, CustomContext],
        data: dict,
        log: str = "",
        prefix="",
        mode: str = ViewMode.fav_manager,
        is_owner=False,
    ):
        super().__init__(timeout=180)
        self.mode = mode
        self.bot = bot
        self.ctx = ctx
        self.guild = ctx.guild
        self.current = None
        self.data = data
        self.guild_data = {}
        self.message = None
        self.log = log
        self.prefix = prefix
        self.components_updater_task = bot.loop.create_task(self.auto_update())
        self.is_owner = is_owner
        self.light_mode = False

        if not self.guild:
            for b in self.bot.pool.get_guild_bots(ctx.guild_id):
                guild = b.get_guild(ctx.guild_id)
                if guild:
                    self.guild = guild
                    break

            if not self.guild:
                self.light_mode = True

    def update_components(self):
        self.clear_items()

        if not self.light_mode:
            mode_select = disnake.ui.Select(
                options=[
                    disnake.SelectOption(
                        label="Gerenciador de Favoritos",
                        value=f"fav_view_mode_{ViewMode.fav_manager}",
                        emoji="⭐",
                        default=self.mode == ViewMode.fav_manager,
                    )
                ],
                min_values=1,
                max_values=1,
            )

            mode_select.append_option(
                disnake.SelectOption(
                    label="Gerenciador de Integrações",
                    value=f"fav_view_mode_{ViewMode.integrations_manager}",
                    emoji="💠",
                    default=self.mode == ViewMode.integrations_manager,
                )
            )

            if self.guild and (self.ctx.author.guild_permissions.manage_guild or self.is_owner):
                mode_select.options.insert(
                    1,
                    disnake.SelectOption(
                        label="Gerenciador de Playlists do Servidor",
                        value=f"fav_view_mode_{ViewMode.guild_fav_manager}",
                        emoji="📌",
                        default=self.mode == ViewMode.guild_fav_manager,
                    ),
                )

            if len(mode_select.options) < 2:
                mode_select.disabled = True

            mode_select.callback = self.mode_callback
            self.add_item(mode_select)

        if self.mode == ViewMode.fav_manager:
            if self.data["fav_links"]:
                opts = []
                for k, v in list(self.data["fav_links"].items())[
                    :25
                ]:  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    emoji, platform = music_source_emoji_url(v)
                    opts.append(disnake.SelectOption(label=k, emoji=emoji, description=platform))
                fav_select = disnake.ui.Select(options=opts, min_values=1, max_values=1)
                fav_select.options[0].default = True
                self.current = fav_select.options[0].label
                fav_select.callback = self.select_callback
                self.add_item(fav_select)

        elif self.mode == ViewMode.guild_fav_manager and self.guild:
            bots_in_guild = []

            for b in sorted(self.bot.pool.get_guild_bots(self.guild.id), key=lambda b: b.identifier):
                if b.bot_ready and b.user in self.guild.members:
                    bots_in_guild.append(
                        disnake.SelectOption(
                            emoji="🎶",
                            label=f"Bot: {b.user.display_name}"[:25],
                            value=f"bot_select_{b.user.id}",
                            description=f"ID: {b.user.id}",
                            default=b == self.bot,
                        )
                    )

            if bots_in_guild:
                bot_select = disnake.ui.Select(options=bots_in_guild, min_values=1, max_values=1)
                bot_select.callback = self.bot_select
                self.add_item(bot_select)

            if self.guild_data["player_controller"]["fav_links"]:
                fav_select = disnake.ui.Select(
                    options=[
                        disnake.SelectOption(
                            label=k, emoji=music_source_emoji_url(v["url"])[0], description=v.get("description")
                        )
                        for k, v in list(self.guild_data["player_controller"]["fav_links"].items())[
                            :25
                        ]  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    ],
                    min_values=1,
                    max_values=1,
                )
                fav_select.options[0].default = True
                self.current = fav_select.options[0].label
                fav_select.callback = self.select_callback
                self.add_item(fav_select)

        elif self.mode == ViewMode.integrations_manager:
            if self.data["integration_links"]:
                opts = []
                for k, v in list(self.data["integration_links"].items())[
                    :25
                ]:  # TODO: Lidar depois com os dados existentes que excedem a quantidade permitida
                    if isinstance(v, dict):
                        v = v["url"]
                    emoji, platform = music_source_emoji_url(v)
                    opts.append(disnake.SelectOption(label=k[5:], emoji=emoji, description=platform, value=k))
                integration_select = disnake.ui.Select(options=opts, min_values=1, max_values=1)
                integration_select.options[0].default = True
                self.current = integration_select.options[0].value
                integration_select.callback = self.select_callback
                self.add_item(integration_select)

        add_button = disnake.ui.Button(label="Adicionar", emoji="➕")
        add_button.callback = self.add_callback
        self.add_item(add_button)

        if self.mode == ViewMode.fav_manager:
            edit_button = disnake.ui.Button(label="Editar", emoji="✍️", disabled=not self.data["fav_links"])
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(label="Remover", emoji="♻️", disabled=not self.data["fav_links"])
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Limpar favoritos", emoji="🚮", disabled=not self.data["fav_links"])
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤", disabled=not self.data["fav_links"])
            export_button.callback = self.export_callback
            self.add_item(export_button)

        elif self.mode == ViewMode.guild_fav_manager:
            edit_button = disnake.ui.Button(
                label="Editar", emoji="✍️", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(
                label="Remover", emoji="♻️", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(
                label="Limpar favoritos", emoji="🚮", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(
                label="Exportar", emoji="📤", disabled=not self.guild_data["player_controller"]["fav_links"]
            )
            export_button.callback = self.export_callback
            self.add_item(export_button)

        elif self.mode == ViewMode.integrations_manager:
            remove_button = disnake.ui.Button(label="Remover", emoji="♻️", disabled=not self.data["integration_links"])
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(
                label="Limpar Integrações", emoji="🚮", disabled=not self.data["integration_links"]
            )
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤", disabled=not self.data["integration_links"])
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Importar", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        if self.mode == ViewMode.fav_manager:
            if self.data["fav_links"] and not self.light_mode:
                play_button = disnake.ui.Button(
                    label="Tocar o favorito selecionado", emoji="▶", custom_id="favmanager_play_button"
                )
                play_button.callback = self.play_callback
                self.add_item(play_button)

        elif self.mode == ViewMode.integrations_manager:
            if self.data["integration_links"]:
                play_button = disnake.ui.Button(
                    label="Tocar uma playlist da integração selecionada", emoji="▶", custom_id="favmanager_play_button"
                )
                play_button.callback = self.play_callback
                self.add_item(play_button)

        cancel_button = disnake.ui.Button(label="Fechar", emoji="❌")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def auto_update(self):
        while True:
            if self.mode != ViewMode.fav_manager:
                return

            user, data, url = await self.bot.wait_for(
                "fav_add", check=lambda user, data, url: user.id == self.ctx.author.id
            )

            self.log = f"<{url}> foi adicionado nos seus favoritos."

            if not isinstance(self.ctx, CustomContext):
                await self.ctx.edit_original_message(content=self.build_txt(), view=self)
            elif self.message:
                await self.message.edit(content=self.build_txt(), view=self)

    async def on_timeout(self):
        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        try:
            for i in self.children[1].options:
                i.default = self.current == i.value
        except Exception:
            pass

        for c in self.children:
            c.disabled = True

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

        else:
            try:
                await self.ctx.edit_original_message(view=self)
            except Exception:
                pass

        self.stop()

    def build_txt(self):
        supported_platforms = []

        if self.mode == ViewMode.integrations_manager:
            supported_platforms.extend(
                ["[`Youtube`](<https://www.youtube.com/>)", "[`Soundcloud`](<https://soundcloud.com/>)"]
            )

            if self.bot.spotify:
                supported_platforms.append("[`Spotify`](<https://open.spotify.com/>)")

            supported_platforms.append("[`Deezer`](<https://www.deezer.com/>)")

        self.update_components()

        try:
            cmd = (
                f"</play:"
                + str(self.bot.get_global_command_named("play", cmd_type=disnake.ApplicationCommandType.chat_input).id)
                + ">"
            )
        except AttributeError:
            cmd = "/play"

        if self.mode == ViewMode.fav_manager:
            txt = "### Gerenciador de favoritos.\n"

            if not self.data["fav_links"]:
                txt += "Você não possui favoritos (clique no botão de adicionar abaixo).\n"

            else:

                def format_fav(index, data):
                    name, url = data
                    e = get_source_emoji_cfg(self.bot, url)
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name, 40)}`](<{url}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{url}>)"

                txt += paginator(
                    "\n".join(
                        f"> {format_fav(n + 1, d)}" for n, d in enumerate(islice(self.data["fav_links"].items(), 22))
                    ),
                    max_size=1400,
                )[0]

            if not self.light_mode:
                txt += (
                    "\n\n**Como usá-los?**\n"
                    f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                    "* Clicando no botão/select de tocar favorito/integração do player.\n"
                    f"* Usando o comando {self.prefix}{self.bot.get_cog('Music').play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                    "* Usando o botão de tocar favorito abaixo.\n"
                )

        elif self.mode == ViewMode.guild_fav_manager:
            txt = "### Gerenciador de favoritos do servidor.\n"

            if not self.guild_data["player_controller"]["fav_links"]:
                txt += (
                    f"Não há links adicionados no bot {self.bot.user.mention} (clique no botão de adicionar abaixo).\n"
                )

            else:

                def format_gfav(index, data):
                    name, data = data
                    e = get_source_emoji_cfg(self.bot, data["url"])
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name, 40)}`](<{data['url']}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{data['url']}>)"

                txt += (
                    f"**Links atuais no bot {self.bot.user.mention}:**\n"
                    + paginator(
                        "\n".join(
                            f"> {format_gfav(n + 1, d)}"
                            for n, d in enumerate(islice(self.guild_data["player_controller"]["fav_links"].items(), 22))
                        ),
                        max_size=1400,
                    )[0]
                )

                txt += (
                    "\n\n**Como usá-los?**\n"
                    f"* Usando o menu de seleção do player durante o modo de espera.\n"
                    f"\n`Bot selecionado:` {self.bot.user.mention}"
                )

        elif self.mode == ViewMode.integrations_manager:
            txt = "### Gerenciador de integrações de canais/perfis com playlists públicas.\n"

            if not self.data["integration_links"]:
                txt += "**Você não possui integrações no momento (clique no botão de adicionar abaixo).**\n"

            else:

                def format_itg(bot, index, data):
                    name, url = data
                    if isinstance(url, dict):
                        url = url["url"]
                    e = get_source_emoji_cfg(bot, url)
                    if e:
                        return f"` {index:02} ` {e} [`{fix_characters(name[5:], 40)}`](<{url}>)"
                    return f"` {index:02} ` [`{fix_characters(name, 40)}`](<{url}>)"

                txt += (
                    f"### Suas integrações atuais:\n"
                    + paginator(
                        "\n".join(
                            f"> {format_itg(self.bot, n + 1, d)}"
                            for n, d in enumerate(islice(self.data["integration_links"].items(), 22))
                        ),
                        max_size=1400,
                    )[0]
                )

                if not self.light_mode:
                    txt += (
                        "\n\n**Como usá-los?**\n"
                        f"* Usando o comando {cmd} (selecionando o favorito no preenchimento automático da busca)\n"
                        "* Clicando no botão/select de tocar favorito/integração do player.\n"
                        f"* Usando o comando {self.prefix}{self.bot.get_cog('Music').play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                        "* Usando o botão de tocar favorito abaixo.\n"
                    )

        else:
            raise GenericError(f"**Modo não implementado:** {self.mode} | {type(self.mode)}")

        if self.log:
            txt += f"\n**Última interação:**\n{self.log}\n"

        if self.mode == ViewMode.integrations_manager:
            txt += f"\n**Links de perfis/canais suportados:**\n{', '.join(supported_platforms)}"

        return txt

    async def add_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(FavModalAdd(name=None, url=None, view=self))

    async def edit_callback(self, inter: disnake.MessageInteraction):
        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        if self.mode == ViewMode.fav_manager:
            try:
                await inter.response.send_modal(
                    FavModalAdd(name=self.current, url=self.data["fav_links"][self.current], view=self)
                )
            except KeyError:
                await inter.send(f"**Não há favorito com o nome:** {self.current}", ephemeral=True)

        elif self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return
            try:
                await inter.response.send_modal(
                    FavModalAdd(
                        bot=self.bot,
                        name=self.current,
                        url=self.data["player_controller"]["fav_links"][self.current]["url"],
                        description=self.data["player_controller"]["fav_links"][self.current]["description"],
                        view=self,
                    )
                )
            except KeyError:
                await inter.send(f"**Não há favorito com nome:** {self.current}", ephemeral=True)

    async def remove_callback(self, inter: disnake.MessageInteraction):
        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        guild = None

        if self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id)

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return

            if not self.guild_data:
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        else:
            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        if self.mode == ViewMode.fav_manager:
            try:
                url = f"[`{self.current}`]({self.data['fav_links'][self.current]})"
                del self.data["fav_links"][self.current]
            except Exception:
                await inter.edit_original_message(f"**Não há favorito na lista com o nome:** {self.current}")
                return

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = f"Favorito {url} foi removido com sucesso!"

        elif self.mode == ViewMode.guild_fav_manager:
            try:
                url = f"[`{self.current}`]({self.guild_data['player_controller']['fav_links'][self.current]})"
                del self.guild_data["player_controller"]["fav_links"][self.current]
            except KeyError:
                try:
                    await process_idle_embed(self.bot, guild, guild_data=self.guild_data)
                except Exception:
                    traceback.print_exc()

                await inter.edit_original_message(
                    embed=disnake.Embed(
                        description=f"**Não há links da lista com o nome:** {self.current}",
                        color=self.bot.get_color(guild.me),
                    ),
                    view=None,
                )
                return

            await self.bot.update_data(inter.guild_id, self.guild_data, db_name=DBModel.guilds)

            self.log = f"Link {url} foi removido com sucesso da lista de favoritos do servidor!"

        elif self.mode == ViewMode.integrations_manager:
            item = self.data["integration_links"][self.current]

            if isinstance(inter, dict):
                item = item["url"]

            try:
                url = f"[`{self.current}`]({item})"
                del self.data["integration_links"][self.current]
            except Exception:
                await inter.send(f"**Não há integração na lista com o nome:** {self.current}", ephemeral=True)
                return

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = f"Integração {url} foi removida com sucesso!"

        await inter.edit_original_message(content=self.build_txt(), view=self)

    async def bot_select(self, inter: disnake.MessageInteraction):
        value = int(inter.values[0][11:])

        for b in self.bot.pool.get_guild_bots(inter.guild_id):
            try:
                if b.user.id == value:
                    self.bot = b
            except AttributeError:
                continue

        self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        await inter.response.edit_message(content=self.build_txt(), view=self)

    async def clear_callback(self, inter: disnake.MessageInteraction):
        guild = None

        if self.mode == ViewMode.guild_fav_manager:
            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            if not guild:
                await inter.send("Você não pode executar essa ação fora de um servidor.", ephemeral=True)
                return

            await inter.response.defer(ephemeral=True)

            if not self.guild_data:
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        else:
            await inter.response.defer(ephemeral=True)

            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        if self.mode == ViewMode.fav_manager:
            if not self.data["fav_links"]:
                await inter.send("**Você não possui links favoritos!**", ephemeral=True)
                return

            fp = BytesIO(bytes(json.dumps(self.data["fav_links"], indent=4), "utf-8"))

            self.data["fav_links"].clear()

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = "Sua lista de favoritos foi limpa com sucesso!"

            await inter.send(
                "### Seus favoritos foram excluídos com sucesso!\n"
                "`Um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="favs.json"),
            )

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data["player_controller"]["fav_links"]:
                await inter.send("**Não há links favoritos no servidor.**", ephemeral=True)
                return

            fp = BytesIO(bytes(json.dumps(self.guild_data["player_controller"]["fav_links"], indent=4), "utf-8"))

            self.guild_data["player_controller"]["fav_links"].clear()

            await self.bot.update_data(inter.guild_id, self.guild_data, db_name=DBModel.guilds)

            try:
                await process_idle_embed(self.bot, guild, guild_data=self.guild_data)
            except Exception:
                traceback.print_exc()

            self.log = "Lista de favoritos do server foi limpa com sucesso!"

            await inter.send(
                "### Os links de favoritos do server foram excluídos com sucesso!\n"
                "`um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="guild_favs.json"),
            )

        elif self.mode == ViewMode.integrations_manager:
            if not self.data["integration_links"]:
                await inter.response.edit_message(content="**Você não possui integrações salvas!**", view=None)
                return

            fp = BytesIO(bytes(json.dumps(self.data["integration_links"], indent=4), "utf-8"))

            self.data["integration_links"].clear()

            await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

            self.log = "Sua lista de integrações foi limpa com sucesso!"

            await inter.send(
                "### Suas integrações foram excluídas com sucesso!\n"
                "`um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                'conteúdo do arquivo e clique no botão "importar" e cole o conteudo no campo indicado.`',
                ephemeral=True,
                file=disnake.File(fp, filename="integrations.json"),
            )

        self.current = None

        if not isinstance(self.ctx, CustomContext):
            await self.ctx.edit_original_message(content=self.build_txt(), view=self)
        elif self.message:
            await self.message.edit(content=self.build_txt(), view=self)

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(FavModalImport(view=self))

    async def play_callback(self, inter: disnake.MessageInteraction):
        await check_pool_bots(inter, check_player=False)
        await self.bot.get_cog("Music").player_controller(
            inter,
            PlayerControls.add_song,
            query=f"> itg: {self.current}" if self.mode == ViewMode.integrations_manager else f"> fav: {self.current}",
        )

    async def export_callback(self, inter: disnake.MessageInteraction):
        cog = self.bot.get_cog("Music")

        if retry_after := cog.fav_import_export_cd.get_bucket(inter).update_rate_limit():
            if retry_after < 1:
                retry_after = 1
            await inter.send(
                "**Você deve aguardar {} para exportar.**".format(time_format(int(retry_after) * 1000, use_names=True)),
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        try:
            cmd = (
                f"</{cog.fav_manager.name}:"
                + str(
                    self.bot.get_global_command_named(
                        cog.fav_manager.name, cmd_type=disnake.ApplicationCommandType.chat_input
                    ).id
                )
                + ">"
            )
        except AttributeError:
            cmd = "/play"

        if self.mode == ViewMode.fav_manager:
            if not self.data["fav_links"]:
                await inter.send(
                    f"**Você não possui links favoritos..\nVocê pode adicionar usando o comando: {cmd}**",
                    ephemeral=True,
                )
                return

            fp = BytesIO(bytes(json.dumps(self.data["fav_links"], indent=4), "utf-8"))

            await inter.send(
                embed=disnake.Embed(
                    description=f"Seus favoritos estão aqui.\nVocê pode importar usando o comando: {cmd}",
                    color=self.bot.get_color(),
                ),
                file=disnake.File(fp=fp, filename="favoritos.json"),
                ephemeral=True,
            )

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data["player_controller"]["fav_links"]:
                await inter.edit_original_message(
                    content=f"**Não há músicas/playlists fixadas no servidor..\n"
                    f"Você pode adicionar usando o comando: {cmd}**"
                )

            fp = BytesIO(bytes(json.dumps(self.guild_data["player_controller"]["fav_links"], indent=4), "utf-8"))

            guild = self.bot.get_guild(inter.guild_id) or inter.guild

            embed = disnake.Embed(
                description=f"**Os dados dos links de músicas/playlists fixas do servidor estão aqui.\n"
                f"Você pode importar usando o comando:** {cmd}",
                color=self.bot.get_color(guild.me),
            )

            await inter.send(embed=embed, file=disnake.File(fp=fp, filename="guild_favs.json"), ephemeral=True)

        elif self.mode == ViewMode.integrations_manager:
            if not self.data["integration_links"]:
                await inter.edit_original_message(
                    f"**Você não possui integrações adicionadas...\nVocê pode adicionar usando o comando: {cmd}**"
                )
                return

            fp = BytesIO(bytes(json.dumps(self.data["integration_links"], indent=4), "utf-8"))

            await inter.send(
                embed=disnake.Embed(
                    description=f"Suas integrações estão aqui.\nVocê pode importar usando o comando: {cmd}",
                    color=self.bot.get_color(),
                ),
                file=disnake.File(fp=fp, filename="integrations.json"),
                ephemeral=True,
            )

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        await inter.response.edit_message(content="**Gerenciador fechado.**", view=None)
        self.stop()

    async def mode_callback(self, inter: disnake.MessageInteraction):
        self.mode = inter.values[0][14:]

        try:
            self.components_updater_task.cancel()
        except Exception:
            pass

        if self.mode == ViewMode.fav_manager:
            self.components_updater_task = self.bot.loop.create_task(self.auto_update())

        elif self.mode == ViewMode.guild_fav_manager:
            if not self.guild_data:
                await inter.response.defer()
                self.guild_data = await self.bot.get_data(inter.guild_id, db_name=DBModel.guilds)

        if inter.response.is_done():
            await inter.edit_original_message(content=self.build_txt(), view=self)
        else:
            await inter.response.edit_message(content=self.build_txt(), view=self)

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True)


base_skin = {
    "queue_max_entries": 7,
    "queue_format": "`{track.number}) [{track.duration}]` [`{track.title_42}`]({track.url})",
    "embeds": [
        {"title": "Próximas músicas:", "description": "{queue_format}", "color": "{guild.color}"},
        {
            "description": "**Tocando agora:\n[{track.title}]({track.url})**\n\n**Duração:** `{track.duration}`\n**Pedido por:** {requester.mention}\n**Uploader**: `{track.author}`\n**Playlist de origem:** [`{playlist.name}`]({playlist.url})\n\n{player.log.emoji} **Última ação:** {player.log.text}",
            "image": {"url": "{track.thumb}"},
            "color": "{guild.color}",
            "footer": {"text": "Músicas na lista: {player.queue.size}"},
        },
    ],
}


class SkinSettingsButton(disnake.ui.View):
    def __init__(self, user: disnake.Member, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.mode = "custom_skins_static"
        self.inter = None
        self.controller_enabled = True
        self.update_components()

    def update_components(self):
        self.clear_items()

        select_mode = disnake.ui.Select(
            min_values=1,
            max_values=1,
            options=[
                disnake.SelectOption(
                    label="Modo Normal",
                    description="Aplicar skin ao modo normal do player",
                    value="custom_skins",
                    default=self.mode == "custom_skins",
                ),
                disnake.SelectOption(
                    label="Song-Request",
                    description="Aplicar skin no modo song-request do player",
                    value="custom_skins_static",
                    default=self.mode == "custom_skins_static",
                ),
            ],
        )
        select_mode.callback = self.player_mode
        self.add_item(select_mode)

        if self.mode == "custom_skins":
            controller_btn = disnake.ui.Button(
                emoji="💠",
                label="Ativar Player-Controller" if not self.controller_enabled else "Desativar Player-Controller",
            )
            controller_btn.callback = self.controller_buttons
            self.add_item(controller_btn)

        save_btn = disnake.ui.Button(label="Salvar", emoji="💾")
        save_btn.callback = self.save
        self.add_item(save_btn)

    async def controller_buttons(self, inter: disnake.MessageInteraction):
        self.controller_enabled = not self.controller_enabled
        self.update_components()
        await inter.response.edit_message(view=self)

    async def player_mode(self, inter: disnake.MessageInteraction):
        self.mode = inter.values[0]
        self.update_components()
        await inter.response.edit_message(view=self)

    async def save(self, inter: disnake.ModalInteraction):
        self.inter = inter
        self.stop()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.user.id:
            await inter.send(f"Apenas o membro {self.user.mention} pode usar es botões da mensagem.", ephemeral=True)
            return False

        return True


class SkinEditorMenu(disnake.ui.View):
    def __init__(
        self,
        ctx: Union[CustomContext, disnake.ApplicationCommandInteraction],
        bot: BotCore,
        guild: disnake.Guild,
        global_data: dict,
    ):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.guild = guild
        self.message: Optional[disnake.Message] = None
        self.embed_index = 0
        self.embed_field_index = 0
        self.mode: Literal["editor", "select"] = "select"
        self.global_data = global_data
        self.skin_selected = ""
        self.message_data = {}
        self.update_components()

    def disable_buttons(self):
        for c in self.children:
            if c.custom_id != "skin_editor_placeholders":
                c.disabled = True

    async def new_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.message_data = deepcopy(base_skin)
        self.mode = "editor"
        self.update_components()
        await self.update_message(inter)

    async def _refuse_skin(self, reply, guild_id: int, error: SchemaError, text: str):
        """Não grava nada: avisa o dono e deixa no log só o servidor e o código da falha."""
        logger.warning("Skin do editor não salva: servidor %s, motivo %s", guild_id, error.code)
        await reply.edit_original_message(text, view=None)

    async def load_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        selected = inter.values[0]

        if selected.startswith("> cs: "):
            mode, name = "custom_skins", selected[6:]
        elif selected.startswith("> css: "):
            mode, name = "custom_skins_static", selected[7:]
        else:
            mode = name = None

        message_data = deepcopy(base_skin)

        if mode:
            skins = await load_custom_skins(self.bot, self.guild.id, self.global_data)
            readable = skins.normal if mode == "custom_skins" else skins.static
            if name in readable:
                message_data = readable[name]
            elif self.global_data[mode][name]:
                await inter.send("**Esta skin está em um formato incompatível e não pôde ser aberta.**", ephemeral=True)
                return

        self.skin_selected = selected
        self.mode = "editor"
        self.message_data = message_data
        self.update_components()
        await self.update_message(inter)

    def update_components(self):
        self.clear_items()

        if self.mode == "select":
            add_skin_prefix = lambda d: [f"> cs: {i}" for i in d.keys()]
            skins_opts = [
                disnake.SelectOption(emoji="💠", label=f"Modo normal: {s.replace('> cs: ', '', 1)}", value=s)
                for s in add_skin_prefix(self.global_data["custom_skins"])
            ]
            add_skin_prefix = lambda d: [f"> css: {i}" for i in d.keys()]
            static_skins_opts = [
                disnake.SelectOption(emoji="💠", label=f"Song-Request: {s.replace('> css: ', '', 1)}", value=s)
                for s in add_skin_prefix(self.global_data["custom_skins_static"])
            ]

            has_skins = False

            if skins_opts:
                skin_select = disnake.ui.Select(
                    min_values=1, max_values=1, options=skins_opts, placeholder="Skins do modo normal do player"
                )
                skin_select.callback = self.load_skin
                self.add_item(skin_select)
                has_skins = True

            if static_skins_opts:
                static_skin_select = disnake.ui.Select(
                    min_values=1,
                    max_values=1,
                    options=static_skins_opts,
                    placeholder="Skins do modo song-request do player",
                )
                static_skin_select.callback = self.load_skin
                self.add_item(static_skin_select)
                has_skins = True

            if not has_skins:
                self.message_data = {
                    "embeds": [
                        {
                            "description": "**Não há skins salvas...\nClique no botão abaixo para criar uma nova skin/template.**",
                            "color": self.guild.me.color.value,
                        }
                    ]
                }
                new_skin_btn = disnake.ui.Button(
                    label="Adicionar nova skin",
                    custom_id="skin_editor_new_skin",
                    disabled=len(static_skins_opts) > 2 and len(skins_opts) > 2,
                )
                new_skin_btn.callback = self.new_skin
                self.add_item(new_skin_btn)
            else:
                self.message_data = {
                    "embeds": [
                        {
                            "description": "**Selecione uma skin abaixo para editá-la ou crie uma nova usando um modelo base clicando no botão de adicionar abaixo.**",
                            "color": self.guild.me.color.value,
                        }
                    ]
                }
                new_skin_btn = disnake.ui.Button(
                    label="Adicionar nova skin",
                    custom_id="skin_editor_new_skin",
                    disabled=len(static_skins_opts) > 2 and len(skins_opts) > 2,
                )
                new_skin_btn.callback = self.new_skin
                self.add_item(new_skin_btn)

        elif self.mode == "editor":
            if embeds := self.message_data.get("embeds"):
                select_embed = disnake.ui.Select(
                    min_values=1,
                    max_values=1,
                    options=[
                        disnake.SelectOption(
                            label=f"Embed {n + 1}", value=f"skin_embed_{n}", default=n == self.embed_index
                        )
                        for n, e in enumerate(embeds)
                    ],
                )

                select_embed.callback = self.embed_select_callback
                self.add_item(select_embed)

                if fields := embeds[self.embed_index].get("fields", []):
                    select_embed_field = disnake.ui.Select(
                        min_values=1,
                        max_values=1,
                        options=[
                            disnake.SelectOption(
                                label=f"Field {n + 1}",
                                value=f"skin_embed_field_{n}",
                                default=n == self.embed_field_index,
                            )
                            for n, e in enumerate(fields)
                        ],
                    )
                    select_embed_field.callback = self.embed_value_select_callback
                    self.add_item(select_embed_field)

                if len(fields) < 25:
                    add_field_btn = disnake.ui.Button(label="Adicionar Field", emoji="🔖")
                    add_field_btn.callback = self.add_field
                    self.add_item(add_field_btn)

                if fields:
                    edit_field_btn = disnake.ui.Button(label="Editar Field", emoji="🔖")
                    edit_field_btn.callback = self.edit_embed_field_button
                    self.add_item(edit_field_btn)

                    delete_field_btn = disnake.ui.Button(label="Remover Field", emoji="🔖")
                    delete_field_btn.callback = self.delete_embed_field_button
                    self.add_item(delete_field_btn)

                edit_embed_btn = disnake.ui.Button(label="Editar Embed", emoji="📋")
                edit_embed_btn.callback = self.edit_embed_button
                self.add_item(edit_embed_btn)

                remove_embed_btn = disnake.ui.Button(label="Remover Embed", emoji="📋")
                remove_embed_btn.callback = self.remove_embed
                self.add_item(remove_embed_btn)

                set_author_footer_btn = disnake.ui.Button(label="Embed Author + Footer", emoji="👤")
                set_author_footer_btn.callback = self.set_author_footer
                self.add_item(set_author_footer_btn)

            edit_content_btn = disnake.ui.Button(
                label=("Adicionar" if not self.message_data.get("content") else "Editar") + " Mensagem", emoji="💬"
            )
            edit_content_btn.callback = self.edit_content
            self.add_item(edit_content_btn)

            add_embed_btn = disnake.ui.Button(label="Adicionar Embed", disabled=len(embeds) >= 8, emoji="📋")
            add_embed_btn.callback = self.add_embed
            self.add_item(add_embed_btn)

            setup_queue_btn = disnake.ui.Button(label="Configurar placeholder da fila", emoji="📑")
            setup_queue_btn.callback = self.setup_queue
            self.add_item(setup_queue_btn)

            save_disabled = not embeds and len(self.message_data.get("content", "")) < 15

            export_btn = disnake.ui.Button(label="Exportar Skin", emoji="📤", disabled=save_disabled)
            export_btn.callback = self.export
            self.add_item(export_btn)

            import_btn = disnake.ui.Button(label="Importar Skin", emoji="📥")
            import_btn.callback = self.import_
            self.add_item(import_btn)

            if self.skin_selected:
                delete_skin_btn = disnake.ui.Button(label="Excluir Skin", emoji="🚮")
                delete_skin_btn.callback = self.delete_skin
                self.add_item(delete_skin_btn)

            back_btn = disnake.ui.Button(label="Voltar ao menu anterior", emoji="⬅️")
            back_btn.callback = self.back
            self.add_item(back_btn)

            self.add_item(
                disnake.ui.Button(label="Lista de placeholders", emoji="❓", custom_id="skin_editor_placeholders")
            )

            save_btn = disnake.ui.Button(label="Salvar Skin", emoji="💾", disabled=save_disabled)
            save_btn.callback = self.save
            self.add_item(save_btn)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.ctx.author.id:
            await inter.send(
                f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.disable_buttons()

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        else:
            try:
                await self.ctx.edit_original_message(view=self)
            except Exception:
                pass

    def build_embeds(self) -> dict:
        player = None
        for b in self.bot.pool.get_guild_bots(self.ctx.guild_id):
            try:
                player = b.music.players[self.ctx.guild_id]
                break
            except KeyError:
                continue

        data = skin_converter(self.message_data, guild=self.guild, ctx=self.ctx, player=player)
        return {"content": data.get("content", ""), "embeds": data.get("embeds", [])}

    async def embed_select_callback(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.embed_index = int(inter.values[0][11:])
        await inter.response.defer()

    async def embed_value_select_callback(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.embed_field_index = int(inter.values[0][17:])
        await inter.response.defer()

    async def edit_content(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Editar/Adicionar conteúdo da mensagem",
                custom_id="skin_editor_message_content",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Mensagem:",
                        custom_id="message_content",
                        value=self.message_data.get("content", ""),
                        max_length=1700,
                        required=False,
                    ),
                ],
            )
        )

    async def add_embed(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Adicionar Embed",
                custom_id="skin_editor_add_embed",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Título da embed:",
                        custom_id="skin_embed_title",
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Descrição da embed:",
                        custom_id="skin_embed_description",
                        max_length=1700,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Cor da embed:",
                        placeholder="Exemplo: #000fff ou {guild.color}",
                        custom_id="skin_embed_color",
                        max_length=15,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da imagem:",
                        custom_id="image_url",
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da miniatura:",
                        custom_id="thumbnail_url",
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def edit_embed_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        embed = self.message_data["embeds"][self.embed_index]

        try:
            image_url = embed["image"]["url"]
        except KeyError:
            image_url = ""

        try:
            thumb_url = embed["thumbnail"]["url"]
        except KeyError:
            thumb_url = ""

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Edite os campos principais da embed",
                custom_id="skin_editor_edit_embed",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Título da embed:",
                        custom_id="skin_embed_title",
                        value=embed.get("title", ""),
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Descrição da embed:",
                        custom_id="skin_embed_description",
                        value=embed.get("description", ""),
                        max_length=1700,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Cor da embed:",
                        placeholder="Exemplo: #000fff ou {guild.color}",
                        custom_id="skin_embed_color",
                        value=str(embed.get("color", "")),
                        max_length=14,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da imagem:",
                        custom_id="image_url",
                        value=image_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Placeholder da miniatura:",
                        custom_id="thumbnail_url",
                        value=thumb_url,
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def remove_embed(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        del self.message_data["embeds"][self.embed_index]
        self.embed_index = 0
        self.update_components()
        await inter.response.edit_message(view=self, **self.build_embeds())

    async def add_field(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Adicionar field na embed",
                custom_id="skin_editor_add_field",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome:",
                        custom_id="add_field_name",
                        max_length=170,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Valor/Texto:",
                        custom_id="add_field_value",
                        max_length=1700,
                        required=True,
                    ),
                ],
            )
        )

    async def edit_embed_field_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        field = self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index]

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Edição dos campos principais da embed",
                custom_id="skin_editor_edit_field",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome do campo:",
                        custom_id="edit_field_name",
                        value=field["name"],
                        max_length=170,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Valor/Texto do campo:",
                        custom_id="edit_field_value",
                        value=field["value"],
                        max_length=1700,
                        required=True,
                    ),
                ],
            )
        )

    async def delete_embed_field_button(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        del self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index]
        self.embed_field_index = 0
        self.update_components()
        await inter.response.edit_message(view=self, **self.build_embeds())

    async def set_author_footer(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        try:
            author_name = self.message_data["embeds"][self.embed_index]["author"]["name"]
        except KeyError:
            author_name = ""

        try:
            author_url = self.message_data["embeds"][self.embed_index]["author"]["url"]
        except KeyError:
            author_url = ""

        try:
            author_icon_url = self.message_data["embeds"][self.embed_index]["author"]["icon_url"]
        except KeyError:
            author_icon_url = ""

        try:
            footer_text = self.message_data["embeds"][self.embed_index]["footer"]["text"]
        except KeyError:
            footer_text = ""

        try:
            footer_icon_url = self.message_data["embeds"][self.embed_index]["footer"]["icon_url"]
        except KeyError:
            footer_icon_url = ""

        await inter.response.send_modal(
            ViewModal(
                view=self,
                custom_id="skin_editor_set_authorfooter",
                title="Adicionar/editar autor/footer",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome do author:",
                        custom_id="set_author_name",
                        value=author_name,
                        max_length=170,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Url do author:",
                        custom_id="set_author_url",
                        value=author_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Link/Url da imagem do author:",
                        custom_id="set_author_icon",
                        value=author_icon_url,
                        max_length=400,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Texto do footer:",
                        custom_id="footer_text",
                        value=footer_text,
                        max_length=1700,
                        required=False,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="URL/Link da imagem do footer:",
                        custom_id="footer_icon_url",
                        value=footer_icon_url,
                        max_length=400,
                        required=False,
                    ),
                ],
            )
        )

    async def setup_queue(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Placeholder da lista de músicas da fila",
                custom_id="skin_editor_setup_queue",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Formatação de texto no nome das músicas:",
                        custom_id="queue_format",
                        value=self.message_data["queue_format"],
                        max_length=120,
                        required=True,
                    ),
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Quantidade de músicas exibidas na lista:",
                        custom_id="queue_max_entries",
                        value=str(self.message_data["queue_max_entries"]),
                        max_length=2,
                        required=True,
                    ),
                ],
            )
        )

    async def export(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        fp = BytesIO(bytes(json.dumps(self.message_data, indent=4), "utf-8"))
        await inter.response.send_message(file=disnake.File(fp=fp, filename="skin.json"), ephemeral=True)

    async def import_(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Importar skin",
                custom_id="skin_editor_import_skin",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.long,
                        label="Código da skin (json):",
                        custom_id="skin",
                        max_length=2000,
                        required=True,
                    )
                ],
            )
        )

    async def save(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        await inter.response.send_modal(
            ViewModal(
                view=self,
                title="Informe o nome da skin",
                custom_id="skin_editor_save",
                components=[
                    disnake.ui.TextInput(
                        style=disnake.TextInputStyle.short,
                        label="Nome:",
                        custom_id="skin_name",
                        value=self.skin_selected.replace("> css: ", "", 1).replace("> cs: ", "", 1),
                        max_length=15,
                        required=True,
                    )
                ],
            )
        )

    async def delete_skin(self, inter: disnake.MessageInteraction):
        self.ctx = inter

        await inter.response.defer()

        self.global_data = await self.bot.get_global_data(id_=inter.guild_id, db_name=DBModel.guilds)

        if self.skin_selected.startswith("> cs:"):
            try:
                del self.global_data["custom_skins"][self.skin_selected[6:]]
            except KeyError:
                await inter.send(f"**A skin {self.skin_selected[6:]} não existe mais na database...**", ephemeral=True)
                return

        elif self.skin_selected.startswith("> css:"):
            try:
                del self.global_data["custom_skins_static"][self.skin_selected[7:]]
            except KeyError:
                await inter.send(f"**A skin {self.skin_selected[7:]} não existe mais na database...**", ephemeral=True)
                return

        await self.bot.update_global_data(id_=inter.guild_id, data=self.global_data, db_name=DBModel.guilds)

        self.mode = "select"
        self.skin_selected = ""
        self.update_components()

        await inter.edit_original_message(view=self, **self.build_embeds())

    async def back(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        self.mode = "select"
        self.skin_selected = ""
        self.message_data = {}
        self.update_components()
        await self.update_message(inter)

    async def update_message(self, inter: disnake.MessageInteraction):
        self.ctx = inter
        try:
            if isinstance(self.ctx, CustomContext):
                await inter.response.edit_message(view=self, **self.build_embeds())
            elif not inter.response.is_done():
                await inter.response.edit_message(view=self, **self.build_embeds())
            else:
                await inter.edit_original_message(view=self, **self.build_embeds())
        except Exception as e:
            code = log_unexpected_error(logger, e, "editor de skin: atualização da mensagem")
            await inter.send("**Ocorreu um erro ao processar a mensagem.**" + error_code_text(code), ephemeral=True)

    async def modal_handler(self, inter: disnake.ModalInteraction):
        if inter.custom_id == "skin_editor_message_content":
            self.ctx = inter
            self.message_data["content"] = inter.text_values["message_content"]

        elif inter.custom_id == "skin_editor_add_embed":
            self.ctx = inter

            e = (
                disnake.Embed(
                    title=inter.text_values["skin_embed_title"],
                    description=inter.text_values["skin_embed_description"],
                )
                .set_image(url=inter.text_values["image_url"])
                .set_thumbnail(inter.text_values["thumbnail_url"])
                .to_dict()
            )

            e["color"] = inter.text_values["skin_embed_color"].strip("#")

            self.message_data["embeds"].append(e)
            self.embed_index = len(self.message_data["embeds"]) - 1

        elif inter.custom_id == "skin_editor_edit_embed":
            self.ctx = inter

            self.message_data["embeds"][self.embed_index]["title"] = inter.text_values["skin_embed_title"]
            self.message_data["embeds"][self.embed_index]["description"] = inter.text_values["skin_embed_description"]

            if not inter.text_values["image_url"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["image"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["image"] = {"url": inter.text_values["image_url"]}

            if not inter.text_values["thumbnail_url"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["thumbnail"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["thumbnail"] = {"url": inter.text_values["thumbnail_url"]}

            self.message_data["embeds"][self.embed_index]["color"] = inter.text_values["skin_embed_color"].strip("#")

        elif inter.custom_id == "skin_editor_add_field":
            self.ctx = inter

            if not self.message_data["embeds"][self.embed_index].get("fields"):
                self.message_data["embeds"][self.embed_index]["fields"] = [
                    {"name": inter.text_values["add_field_name"], "value": inter.text_values["add_field_value"]}
                ]
            else:
                self.message_data["embeds"][self.embed_index]["fields"].append(
                    {"name": inter.text_values["add_field_name"], "value": inter.text_values["add_field_value"]}
                )

            self.embed_field_index = len(self.message_data["embeds"][self.embed_index]["fields"]) - 1

        elif inter.custom_id == "skin_editor_edit_field":
            self.ctx = inter
            self.message_data["embeds"][self.embed_index]["fields"][self.embed_field_index] = {
                "name": inter.text_values["edit_field_name"],
                "value": inter.text_values["edit_field_value"],
            }

        elif inter.custom_id == "skin_editor_set_authorfooter":
            self.ctx = inter

            if not inter.text_values["footer_text"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["footer"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["footer"] = {
                    "text": inter.text_values["footer_text"],
                    "icon_url": inter.text_values["footer_icon_url"],
                }

            if not inter.text_values["set_author_name"]:
                try:
                    del self.message_data["embeds"][self.embed_index]["author"]
                except KeyError:
                    pass
            else:
                self.message_data["embeds"][self.embed_index]["author"] = {
                    "name": inter.text_values["set_author_name"],
                    "url": inter.text_values["set_author_url"],
                    "icon_url": inter.text_values["set_author_icon"],
                }

        elif inter.custom_id == "skin_editor_setup_queue":
            self.ctx = inter
            self.message_data["queue_format"] = inter.text_values["queue_format"]
            try:
                self.message_data["queue_max_entries"] = int(inter.text_values["queue_max_entries"])
            except TypeError:
                pass

        elif inter.custom_id == "skin_editor_import_skin":
            self.ctx = inter

            try:
                info = json.loads(inter.text_values["skin"])
            except (ValueError, RecursionError):
                logger.exception("Editor de skin: JSON inválido na importação")
                await inter.send(
                    "**Ocorreu um erro ao processar sua skin: confira se o conteúdo é um JSON válido.**",
                    ephemeral=True,
                )
                return

            try:
                if len(str(info["queue_max_entries"])) > 2:
                    info["queue_max_entries"] = 7
            except Exception:
                pass

            try:
                if not isinstance(info["queue_format"], str):
                    info["queue_format"] = self.message_data["queue_format"]
            except KeyError:
                pass

            try:
                self.message_data["embeds"] = info["embeds"]
            except KeyError:
                pass
            try:
                self.message_data["content"] = info["content"]
            except KeyError:
                pass
            try:
                self.message_data["queue_format"] = info["queue_format"]
            except KeyError:
                pass
            try:
                self.message_data["queue_max_entries"] = info["queue_max_entries"]
            except KeyError:
                pass

            self.embed_index = 0
            self.embed_field_index = 0

        elif inter.custom_id == "skin_editor_save":
            view = SkinSettingsButton(self.ctx.author, timeout=30)
            view.controller_enabled = self.message_data.get("controller_enabled", True)
            await inter.send("**Selecione o modo de player que será aplicado na skin.**", view=view, ephemeral=True)
            await view.wait()

            if view.mode is None:
                await inter.edit_original_message("Tempo esgotado!", components=[])
                return

            self.message_data["controller_enabled"] = view.controller_enabled

            if view.inter:
                await view.inter.response.defer(ephemeral=True)

            self.global_data = await self.bot.get_global_data(self.ctx.guild_id, db_name=DBModel.guilds)

            skin_name = self.skin_selected.replace("> css: ", "", 1).replace("> cs: ", "", 1)

            try:
                modal_skin_name = validate_skin_name(inter.text_values["skin_name"])
            except SchemaError as error:
                await self._refuse_skin(view.inter or inter, inter.guild_id, error, SKIN_NAME_REFUSED)
                return

            try:
                new_skin = validate_skin(self.message_data)
            except SchemaError as error:
                await self._refuse_skin(view.inter or inter, inter.guild_id, error, SKIN_REFUSED)
                return

            names = set(self.global_data[view.mode])
            if modal_skin_name != skin_name:
                names.discard(skin_name)
            names.add(modal_skin_name)
            if len(names) > MAX_SKINS_PER_MODE:
                await self._refuse_skin(
                    view.inter or inter, inter.guild_id, SchemaError("", "length"), SKIN_LIMIT_REFUSED
                )
                return

            await load_custom_skins(self.bot, inter.guild_id, self.global_data)  # migra as legadas antes de gravar

            if modal_skin_name != skin_name:
                self.global_data[view.mode].pop(skin_name, None)

            self.global_data[view.mode][modal_skin_name] = new_skin

            await self.bot.update_global_data(id_=inter.guild_id, data=self.global_data, db_name=DBModel.guilds)

            for bot in self.bot.pool.get_guild_bots(inter.guild_id):
                try:
                    player = bot.music.players[inter.guild_id]
                except KeyError:
                    continue

                skins = await load_custom_skins(self.bot, inter.guild_id, self.global_data)

                player.custom_skin_data = skins.normal
                player.custom_skin_static_data = skins.static
                player.setup_features()
                player.setup_hints()
                player.process_hint()

            try:
                cmd = (
                    f"</change_skin:"
                    + str(
                        self.bot.get_global_command_named(
                            "change_skin", cmd_type=disnake.ApplicationCommandType.chat_input
                        ).id
                    )
                    + ">"
                )
            except AttributeError:
                cmd = "/change_skin"

            try:
                guild_prefix = self.bot.pool.guild_prefix_cache[self.ctx.guild_id]
            except KeyError:
                guild_prefix = self.global_data.get("prefix")

            if not guild_prefix:
                guild_prefix = self.bot.config.get("DEFAULT_PREFIX") or "!!"

            if not view.inter:
                view.inter = inter

            await view.inter.edit_original_message(
                "**A skin foi salva/editada com sucesso!**\n"
                f"Você pode aplicá-la usando o comando {cmd} ou {guild_prefix}skin",
                view=None,
            )

            self.skin_selected = ("> cs: " if view.mode == "custom_skins" else "> css: ") + modal_skin_name

            self.update_components()

            if isinstance(self.ctx, CustomContext):
                await self.message.edit(view=self, **self.build_embeds())
            else:
                await self.ctx.edit_original_message(view=self, **self.build_embeds())
            return

        self.update_components()
        await self.update_message(inter)

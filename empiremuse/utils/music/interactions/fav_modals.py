# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Optional

import disnake

from empiremuse.rules.entries import merge_import, save_entry
from empiremuse.rules.errors import (
    AVATAR_INVALID,
    QUOTA_FULL,
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
from empiremuse.utils.music.converters import fix_characters
from empiremuse.utils.music.errors import GenericError, error_code_text, log_unexpected_error
from empiremuse.utils.music.user_limits import quota_for
from empiremuse.utils.others import (
    CustomContext,
)

from empiremuse.utils.music.interactions.common import (
    ViewMode,
    logger,
    process_idle_embed,
    soundcloud_regex,
    youtube_regex,
)
from empiremuse.utils.music.interactions.favorites_texts import (
    _NO_ROOM_INTEGRATION_TEXT,
    _echo,
    _guild_link_error_text,
    _import_quota_text,
    _invalid_link_text,
    _invalid_name_text,
    _name_error_text,
    _profile_saved,
    _profile_source,
    _retry_text,
    _save_error_text,
    _spotify_profile,
    _url_error_text,
    _wait_text,
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
        except ValueError, RecursionError:
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
        except disnake.HTTPException, disnake.InteractionResponded:
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

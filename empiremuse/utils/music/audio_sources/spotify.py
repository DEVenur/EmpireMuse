# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING, Union
from urllib.parse import quote

from aiohttp import ClientSession
from rapidfuzz import fuzz

from empiremuse import paths
from empiremuse.rules.ratelimit import retry_after_seconds
from empiremuse.rules.title_match import title_matches
from empiremuse.utils.music.converters import fix_characters, URL_REG
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.models import LavalinkTrack, LavalinkPlaylist
from empiremuse.utils.music.track_encoder import encode_track

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore

spotify_regex = re.compile("https://open.spotify.com?.+(album|playlist|artist|track)/([a-zA-Z0-9]+)")
spotify_link_regex = re.compile(r"(?i)https?:\/\/spotify\.link\/?(?P<id>[a-zA-Z0-9]+)")
spotify_regex_w_user = re.compile("https://open.spotify.com?.+(album|playlist|artist|track|user)/([a-zA-Z0-9]+)")
_NEXT_DATA_REGEX = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)
_PLAYLIST_ID_REGEX = re.compile(r"^[A-Za-z0-9]+$")

SPOTIFY_CACHE_FILENAME = ".spotify_cache.json"
SPOTIFY_CACHE_MODE = 0o600

logger = logging.getLogger(__name__)

PLAYLIST_PAGE_SIZE = 100


def spotify_cache_path() -> Path:
    """Caminho do cache do token, resolvido a cada uso a partir do RUNTIME_DIR (EMPIREMUSE_HOME)."""
    return paths.get_runtime_dir() / SPOTIFY_CACHE_FILENAME


def _read_cache_file(path: Path) -> dict:
    """Lê o cache do token; arquivo ausente, ilegível ou corrompido resulta em cache vazio."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Spotify: cache do token ignorado (%s).", type(e).__name__)
        return {}

    return data if isinstance(data, dict) else {}


def _write_cache_file(path: Path, content: str) -> None:
    """Grava o cache com permissão 0600 num temporário do mesmo diretório e troca de forma atômica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):
                os.fchmod(f.fileno(), SPOTIFY_CACHE_MODE)
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


class SpotifyClient:
    def __init__(
        self, client_id: Optional[str] = None, client_secret: Optional[str] = None, playlist_extra_page_limit: int = 0
    ):
        if not client_id:
            raise Exception("CLIENT_ID do spotify não informado.")

        if not client_secret:
            raise Exception("CLIENT_SECRET do spotify não informado.")

        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://api.spotify.com/v1"
        self.spotify_cache = {}
        self.clock: Callable[[], float] = time.monotonic  # injetável nos testes
        self._paused_until = 0.0
        self.type = "api"
        self.token_refresh = False
        self.playlist_extra_page_limit = playlist_extra_page_limit

        self.spotify_cache = _read_cache_file(spotify_cache_path())

    @property
    def disabled(self) -> bool:
        """Em pausa por limite de requisições (429)? A pausa acaba sozinha; falta de credencial é outro caso (sem cliente)."""
        return self.clock() < self._paused_until

    def _paused_error(self) -> GenericError:
        remaining = max(1, math.ceil(self._paused_until - self.clock()))
        return GenericError(
            "**O Spotify limitou as requisições do bot: o suporte interno ao Spotify está em pausa e volta sozinho "
            f"em cerca de {remaining} s.**"
        )

    def _pause(self, retry_after: Optional[str]) -> None:
        """Pausa as requisições pelo ``Retry-After`` (1 s a 1 h; 60 s sem valor válido); uma pausa nunca encurta outra."""
        seconds = retry_after_seconds(retry_after)
        self._paused_until = max(self._paused_until, self.clock() + seconds)
        logger.warning("Spotify: limite de requisições (429); suporte interno em pausa por %s s.", seconds)

    async def request(self, path: str, params: dict = None, _renovado: bool = False):
        if self.disabled:
            raise self._paused_error()

        headers = {"Authorization": f"Bearer {await self.get_valid_access_token()}"}

        async with ClientSession() as session:
            async with session.get(f"{self.base_url}/{path}", headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    if _renovado:
                        raise GenericError(
                            "**Não foi possível autenticar no Spotify: o acesso foi recusado mesmo após renovar o "
                            "token (confira SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET).**"
                        )
                    await self.get_access_token()
                    return await self.request(path=path, params=params, _renovado=True)
                elif response.status == 403:
                    raise GenericError(
                        "**O Spotify não permitiu o acesso a este conteúdo (ele pode ser privado, restrito ou "
                        "indisponível para bots).**"
                    )
                elif response.status == 404:
                    raise GenericError(
                        "**Não houve resultado para o link informado (confira se o link está correto ou se o "
                        "conteúdo dele está privado ou se foi deletado).**"
                    )
                elif response.status == 429:
                    self._pause(response.headers.get("Retry-After"))
                    raise self._paused_error()
                else:
                    response.raise_for_status()

    async def get_track_info(self, track_id: str):
        return await self.request(path=f"tracks/{track_id}")

    async def get_album_info(self, album_id: str):
        return await self.request(path=f"albums/{album_id}")

    async def get_artist_top(self, artist_id: str):
        return await self.request(path=f"artists/{artist_id}/top-tracks")

    async def _fetch_playlist_embed(self, playlist_id: str) -> Optional[dict]:
        """Fallback via página de embed pública do Spotify quando a Web API omite 'tracks' ou retorna 403/404."""
        if not _PLAYLIST_ID_REGEX.match(playlist_id):
            return None

        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        try:
            async with ClientSession() as session:
                async with session.get(embed_url) as response:
                    if response.status != 200:
                        return None
                    html = await response.text()
        except Exception as e:
            logger.warning("Spotify: falha ao consultar embed da playlist (%s).", type(e).__name__)
            return None

        match = _NEXT_DATA_REGEX.search(html)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
        except ValueError:
            return None

        entity = (((data.get("props") or {}).get("pageProps") or {}).get("state") or {}).get("data", {}).get("entity")
        if not isinstance(entity, dict) or not isinstance(entity.get("trackList"), list):
            return None

        cover_sources = (entity.get("coverArt") or {}).get("sources") or []
        images = [{"url": s["url"]} for s in cover_sources if isinstance(s, dict) and s.get("url")]

        items = []
        for item in entity["trackList"]:
            if not isinstance(item, dict):
                continue
            uri = item.get("uri") or ""
            track_id = uri.split(":")[-1] if ":" in uri else (item.get("uid") or "")
            track_url = f"https://open.spotify.com/track/{track_id}" if track_id else ""
            raw_subtitle = (item.get("subtitle") or "").replace("\xa0", " ").strip()
            artist_names = [a.strip() for a in raw_subtitle.split(",") if a.strip()] or ["Unknown Artist"]
            artists = [
                {"name": name, "external_urls": {"spotify": track_url} if track_url else {}} for name in artist_names
            ]
            items.append(
                {
                    "track": {
                        "id": track_id,
                        "name": item.get("title") or "",
                        "duration_ms": int(item.get("duration") or 0),
                        "artists": artists,
                        "external_urls": {"spotify": track_url} if track_url else {},
                        "album": {"name": "", "total_tracks": 1, "images": images, "external_urls": {}},
                    }
                }
            )

        if not items:
            return None

        return {
            "name": entity.get("name") or entity.get("title") or "Playlist",
            "images": images,
            "tracks": {"items": items, "total": len(items)},
        }

    async def get_playlist_info(self, playlist_id: str):
        try:
            result = await self.request(path=f"playlists/{playlist_id}")
        except GenericError:
            embed_result = await self._fetch_playlist_embed(playlist_id)
            if embed_result is not None:
                return embed_result
            raise

        tracks_obj = result.get("tracks") if isinstance(result, dict) else None
        if not isinstance(tracks_obj, dict) or "items" not in tracks_obj:
            embed_result = await self._fetch_playlist_embed(playlist_id)
            if embed_result is not None:
                result["tracks"] = embed_result["tracks"]
                if not result.get("name"):
                    result["name"] = embed_result["name"]
                if not result.get("images"):
                    result["images"] = embed_result["images"]
                elif embed_result["tracks"]["items"]:
                    for item in result["tracks"]["items"]:
                        if item.get("track") and not item["track"].get("album", {}).get("images"):
                            item["track"].setdefault("album", {})["images"] = result["images"]
                return result
            raise GenericError(
                "**O Spotify não retornou as faixas desta playlist (ela pode ser privada ou indisponível para bots).**"
            )

        if len(result["tracks"]["items"]) == PLAYLIST_PAGE_SIZE and self.playlist_extra_page_limit > 0:
            offset = PLAYLIST_PAGE_SIZE

            for _ in range(self.playlist_extra_page_limit):
                try:
                    result_extra = await self.request(
                        path=f"playlists/{playlist_id}/tracks?offset={offset}&limit={PLAYLIST_PAGE_SIZE}"
                    )
                except Exception as e:
                    logger.warning("Spotify: falha ao carregar página extra da playlist (%s).", type(e).__name__)
                    break

                result["tracks"]["items"].extend(result_extra["items"])
                if not result_extra["next"]:
                    break
                offset += PLAYLIST_PAGE_SIZE

        return result

    async def get_user_info(self, user_id: str):
        return await self.request(path=f"users/{user_id}")

    async def get_user_playlists(self, user_id: str):
        return await self.request(path=f"users/{user_id}/playlists")

    async def get_recommendations(self, seed_tracks: Union[list, str], limit=10):
        if isinstance(seed_tracks, str):
            track_ids = seed_tracks
        else:
            track_ids = ",".join(seed_tracks)

        return await self.request(path="recommendations", params={"seed_tracks": track_ids, "limit": limit})

    async def track_search(self, query: str, limit: int = 10):
        clamped_limit = max(1, min(10, int(limit)))
        return await self.request(path="search", params={"q": query, "type": "track", "limit": clamped_limit})

    async def get_access_token(self):
        if self.token_refresh:
            while self.token_refresh:
                await asyncio.sleep(1)
            return

        self.token_refresh = True

        try:
            token_url = "https://accounts.spotify.com/api/token"

            headers = {
                "Authorization": "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            }

            data = {"grant_type": "client_credentials"}

            async with ClientSession() as session:
                async with session.post(token_url, headers=headers, data=data) as response:
                    data = await response.json()

                if data.get("error"):
                    motivo = data.get("error_description") or data["error"]
                    logger.warning("Spotify: o servidor recusou as credenciais ao obter o token (%s).", motivo)
                    raise GenericError(
                        "**Não foi possível autenticar no Spotify no momento. Avise o responsável pelo bot.**"
                    )

                self.spotify_cache = data

                self.type = "api"

                self.spotify_cache["type"] = "api"

                self.spotify_cache["expires_at"] = time.time() + self.spotify_cache["expires_in"]

                print("🎶 - Access token do spotify obtido com sucesso via API Oficial.")

        finally:
            self.token_refresh = False

        try:
            await asyncio.to_thread(_write_cache_file, spotify_cache_path(), json.dumps(self.spotify_cache))
        except OSError as e:
            logger.warning("Spotify: não foi possível gravar o cache do token (%s).", type(e).__name__)

    async def get_valid_access_token(self):
        if time.time() >= self.spotify_cache.get("expires_at", 0):
            await self.get_access_token()

        try:
            return self.spotify_cache["access_token"]
        except KeyError:
            raise GenericError(
                "**Não foi possível obter o token de acesso do Spotify (confira SPOTIFY_CLIENT_ID e "
                "SPOTIFY_CLIENT_SECRET).**"
            ) from None

    async def get_tracks(
        self, bot: BotCore, requester: int, query: str, search: bool = True, check_title: float = None
    ):
        if spotify_link_regex.match(query):
            async with bot.session.get(query, allow_redirects=False) as r:
                if "location" not in r.headers:
                    raise GenericError("**Falha ao obter resultado para o link informado...**")
                query = str(r.headers["location"])

        if not (matches := spotify_regex.match(query)) and not self.disabled:
            if URL_REG.match(query) or not search:
                return

            r = await self.track_search(query=query)

            tracks = []

            try:
                tracks_result = r["tracks"]["items"]
            except KeyError:
                pass
            else:
                for result in tracks_result:
                    trackinfo = {
                        "title": result["name"],
                        "author": result["artists"][0]["name"] or "Unknown Artist",
                        "length": result["duration_ms"],
                        "identifier": result["id"],
                        "isStream": False,
                        "uri": result["external_urls"]["spotify"],
                        "sourceName": "spotify",
                        "position": 0,
                        "artworkUrl": result["album"]["images"][0]["url"],
                    }

                    try:
                        trackinfo["isrc"] = result["external_ids"]["isrc"]
                    except KeyError:
                        pass

                    t = LavalinkTrack(id_=encode_track(trackinfo)[1], info=trackinfo, requester=requester)

                    t.info["extra"]["authors"] = [
                        fix_characters(i["name"])
                        for i in result["artists"]
                        if f"feat. {i['name'].lower()}" not in result["name"].lower()
                    ]

                    if check_title and not title_matches(
                        fuzz.token_set_ratio,
                        f"{t.authors_string} - {t.single_title}".lower(),
                        query.lower(),
                        t.single_title.lower(),
                        query.lower(),
                        check_title,
                    ):
                        continue

                    try:
                        t.info["isrc"] = result["external_ids"]["isrc"]
                    except KeyError:
                        pass

                    t.info["extra"]["authors_md"] = ", ".join(
                        f"[`{fix_characters(a['name'])}`]({a['external_urls']['spotify']})" for a in result["artists"]
                    )

                    try:
                        if result["album"]["name"] != result["name"]:
                            t.info["extra"]["album"] = {
                                "name": result["album"]["name"],
                                "url": result["album"]["external_urls"]["spotify"],
                            }
                    except AttributeError, KeyError:
                        pass

                    tracks.append(t)

                return tracks

            return

        if self.disabled:
            if [n for n in bot.music.nodes.values() if "spotify" in n.info.get("sourceManagers", [])]:
                return

            raise GenericError("**O suporte a links do spotify está temporariamente desativado.**")

        url_type, url_id = matches.groups()

        if url_type == "track":
            result = await self.get_track_info(url_id)

            trackinfo = {
                "title": result["name"],
                "author": result["artists"][0]["name"] or "Unknown Artist",
                "length": result["duration_ms"],
                "identifier": result["id"],
                "isStream": False,
                "uri": result["external_urls"]["spotify"],
                "sourceName": "spotify",
                "position": 0,
                "artworkUrl": result["album"]["images"][0]["url"],
            }

            try:
                trackinfo["isrc"] = result["external_ids"]["isrc"]
            except KeyError:
                pass

            t = LavalinkTrack(id_=encode_track(trackinfo)[1], info=trackinfo, requester=requester)

            t.info["extra"]["authors"] = [
                fix_characters(i["name"])
                for i in result["artists"]
                if f"feat. {i['name'].lower()}" not in result["name"].lower()
            ]

            t.info["extra"]["authors_md"] = ", ".join(
                f"[`{fix_characters(a['name'])}`]({a['external_urls']['spotify']})" for a in result["artists"]
            )

            try:
                if result["album"]["name"] != result["name"] or result["album"]["total_tracks"] > 1:
                    t.info["extra"]["album"] = {
                        "name": result["album"]["name"],
                        "url": result["album"]["external_urls"]["spotify"],
                    }
            except AttributeError, KeyError:
                pass

            return [t]

        data = {
            "loadType": "PLAYLIST_LOADED",
            "playlistInfo": {"name": ""},
            "sourceName": "spotify",
            "tracks_data": [],
            "is_album": False,
            "thumb": "",
        }

        if url_type == "album":
            cache_key = f"partial:spotify:{url_type}:{url_id}"

            if not (result := bot.pool.playlist_cache.get(cache_key)):
                result = await self.get_album_info(url_id)
                bot.pool.playlist_cache[cache_key] = result

            try:
                thumb = result["tracks"][0]["album"]["images"][0]["url"]
            except KeyError, IndexError, TypeError:
                thumb = ""

            if result["tracks"] is None:
                raise GenericError("**Não houve resultados para o link do álbum informado...**")

            if len(result["tracks"]) < 2:
                track = result["tracks"][0]

                trackinfo = {
                    "title": track["name"],
                    "author": track["artists"][0]["name"] or "Unknown Artist",
                    "length": track["duration_ms"],
                    "identifier": track["id"],
                    "isStream": False,
                    "uri": track["external_urls"]["spotify"],
                    "sourceName": "spotify",
                    "position": 0,
                    "artworkUrl": track["album"]["images"][0]["url"],
                }

                try:
                    trackinfo["isrc"] = track["external_ids"]["isrc"]
                except KeyError:
                    pass

                t = LavalinkTrack(id_=encode_track(trackinfo)[1], info=trackinfo, requester=requester)

                t.info["extra"]["authors"] = [
                    fix_characters(i["name"])
                    for i in track["artists"]
                    if f"feat. {i['name'].lower()}" not in track["name"].lower()
                ]

                t.info["extra"]["authors_md"] = ", ".join(
                    f"[`{fix_characters(a['name'])}`]({a['external_urls']['spotify']})" for a in track["artists"]
                )

                try:
                    if result["name"] != track["name"] or result["total_tracks"] > 1:
                        t.info["extra"]["album"] = {"name": result["name"], "url": result["external_urls"]["spotify"]}
                except AttributeError, KeyError:
                    pass

                return [t]

            data["playlistInfo"]["name"] = result["name"]
            data["playlistInfo"]["is_album"] = True

            for t in result["tracks"]["items"]:
                t["album"] = result

            tracks_data = result["tracks"]["items"]

        elif url_type == "artist":
            cache_key = f"partial:spotify:{url_type}:{url_id}"

            if not (result := bot.pool.playlist_cache.get(cache_key)):
                result = await self.get_artist_top(url_id)
                bot.pool.playlist_cache[cache_key] = result

            try:
                data["playlistInfo"]["name"] = (
                    "As mais tocadas de: " + [a["name"] for a in result["tracks"][0]["artists"] if a["id"] == url_id][0]
                )
            except IndexError:
                data["playlistInfo"]["name"] = "As mais tocadas de: " + result["tracks"][0]["artists"][0]["name"]
            tracks_data = result["tracks"]

        elif url_type == "playlist":
            cache_key = f"partial:spotify:{url_type}:{url_id}"

            if not (result := bot.pool.playlist_cache.get(cache_key)):
                result = await self.get_playlist_info(url_id)
                bot.pool.playlist_cache[cache_key] = result

            data["playlistInfo"]["name"] = result["name"]
            data["playlistInfo"]["thumb"] = result["images"][0]["url"] if result.get("images") else ""

            if result["tracks"]["items"] is None:
                raise GenericError("**Não houve resultados para o link da playlist informada...**")

            tracks_data = [t["track"] for t in result["tracks"]["items"]]

        else:
            raise GenericError(f"**Link do spotify não reconhecido/suportado:**\n{query}")

        if not tracks_data:
            raise GenericError("**Não houve resultados para o link do spotify informado...**")

        data["playlistInfo"]["selectedTrack"] = -1
        data["playlistInfo"]["type"] = url_type

        playlist = LavalinkPlaylist(data, url=query)

        playlist_info = playlist if url_type != "album" else None

        for t in tracks_data:
            if not t:
                continue

            try:
                thumb = t["album"]["images"][0]["url"]
            except IndexError, KeyError:
                thumb = ""

            trackinfo = {
                "title": t["name"],
                "author": t["artists"][0]["name"] or "Unknown Artist",
                "length": t["duration_ms"],
                "identifier": t["id"],
                "isStream": False,
                "uri": t["external_urls"].get(
                    "spotify", f"https://www.youtube.com/results?search_query={quote(t['name'])}"
                ),
                "sourceName": "spotify",
                "position": 0,
                "artworkUrl": thumb,
            }

            try:
                trackinfo["isrc"] = t["external_ids"]["isrc"]
            except KeyError:
                pass

            track = LavalinkTrack(
                id_=encode_track(trackinfo)[1], info=trackinfo, requester=requester, playlist=playlist_info
            )

            try:
                if t["album"]["name"] != t["name"] or t["album"]["total_tracks"] > 1:
                    track.info["extra"]["album"] = {
                        "name": t["album"]["name"],
                        "url": t["album"]["external_urls"]["spotify"],
                    }
            except AttributeError, KeyError:
                pass

            if t["artists"][0]["name"]:
                track.info["extra"]["authors"] = [
                    fix_characters(i["name"])
                    for i in t["artists"]
                    if f"feat. {i['name'].lower()}" not in t["name"].lower()
                ]
                track.info["extra"]["authors_md"] = ", ".join(
                    f"[`{fix_characters(a['name'])}`](<"
                    + a["external_urls"].get(
                        "spotify", f"https://www.youtube.com/results?search_query={quote(t['name'])}"
                    )
                    + ">)"
                    for a in t["artists"]
                )
            else:
                track.info["extra"]["authors"] = ["Unknown Artist"]
                track.info["extra"]["authors_md"] = "`Unknown Artist`"

            playlist.tracks.append(track)

        return playlist

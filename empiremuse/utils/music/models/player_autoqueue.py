# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

import disnake

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.converters import fix_characters
from empiremuse.utils.music.errors import (
    code_suffix,
    error_code_text,
    log_unexpected_error,
)
from empiremuse.utils.music.lastfm_tools import LastFmException

if TYPE_CHECKING:
    pass

from empiremuse.utils.music.models.tracks import (
    LavalinkPlaylist,
    LavalinkTrack,
    PartialTrack,
)
from empiremuse.utils.music.models.helpers import (
    exclude_tags,
    exclude_tags_2,
    lavalink_text,
    log_lavalink_failure,
    logger,
    native_sources,
    providers_dict,
)
from empiremuse.utils.music.models.autoqueue_steps import (
    _aq_source_tracks,
    _aq_lastfm_tracks,
    _aq_report_failure,
    _aq_queue_results,
)
from empiremuse.utils.music.models.step_state import AutoqueueState


class PlayerAutoqueueMixin:
    async def get_autoqueue_tracks(self):
        req = AutoqueueState()
        try:
            return self.queue_autoplay.popleft()
        except Exception:
            pass

        if self.locked:
            return

        req.tracks_search = []

        for req.t in reversed(self.failed_tracks + self.played):
            if len(req.tracks_search) > 4:
                break

            req.tracks_search.insert(0, req.t)

        if current_track := self.current or self.last_track:
            req.tracks_search.insert(0, current_track)

        req.track = None
        req.tracks = []
        req.tracks_ytsearch = []

        req.exception = None

        if req.tracks_search:
            self.locked = True

            for req.track_data in req.tracks_search:
                await _aq_source_tracks(self, req)

                await _aq_lastfm_tracks(self, req)

                req.track = req.track_data

            if not req.tracks:
                try:
                    req.tracks_ytsearch = req.tracks_ytsearch.tracks
                except AttributeError:
                    pass
                req.tracks = req.tracks_ytsearch
                req.tracks.reverse()

            if not req.tracks:
                if await _aq_report_failure(self, req):
                    return

        _aq_queue_results(self, req)

        self.locked = False

        try:
            return self.queue_autoplay.popleft()
        except Exception:
            try:
                return self.played.popleft()
            except Exception:
                return None

    async def resolve_track(self, track: PartialTrack, force=False):
        if track.id:
            return

        check_duration = bool(track.duration)

        try:
            exceptions = []
            selected_track = None
            tracks = []

            if track.info["sourceName"] == "http":
                search_queries = [track.uri or track.search_uri]
            elif (
                track.info["sourceName"] == "youtube"
                and not force
                and (not self.native_yt or not self.node.prefer_youtube_native_playback)
            ):
                return
            else:
                search_queries = []

            if not search_queries:
                if (
                    not force
                    and track.info["sourceName"] in self.node.info.get("sourceManagers", [])
                    and (not self.node.only_use_native_search_providers or track.info["sourceName"] in native_sources)
                ):
                    search_queries = [track.uri]
                else:
                    search_queries = []
                    for sp in self.node.partial_providers:
                        if (
                            track.info["sourceName"] == "youtube"
                            and sp.startswith(("ytsearch:", "ytmsearch:"))
                            and not self.native_yt
                        ):
                            continue

                        if "{isrc}" in sp:
                            if isrc := track.info.get("isrc"):
                                search_queries.append(sp.replace("{isrc}", isrc))
                            continue
                        search_queries.append(
                            sp.replace("{title}", track.single_title).replace("{author}", ", ".join(track.authors))
                        )

            for query in search_queries:
                if not (
                    result := self.bot.pool.partial_track_cache.get(
                        f"{track.info['sourceName']}:{track.author}-{track.single_title}"
                    )
                ):
                    try:
                        result = await self.node.get_tracks(
                            query,
                            track_cls=LavalinkTrack,
                            playlist_cls=LavalinkPlaylist,
                            check_title=60 if query.startswith(("ytmsearch", "ytsearch", "scsearch")) else 75,
                        )
                    except Exception as e:
                        if track.info["sourceName"] == "youtube" and any(
                            e in str(e)
                            for e in (
                                "This video is not available",
                                "YouTube WebM streams are currently not supported.",
                                "Video returned by YouTube isn't what was requested",
                                "The video returned is not what was requested.",
                            )
                        ):
                            cog = self.bot.get_cog("Music")
                            cog.remove_provider(self.node.search_providers, ["ytsearch", "ytmsearch"])
                            cog.remove_provider(
                                self.node.partial_providers,
                                [
                                    'ytsearch:"{isrc}"',
                                    'ytsearch:"{title} - {author}"',
                                    'ytmsearch:"{isrc}"',
                                    'ytmsearch:"{title} - {author}"',
                                ],
                            )
                            self.native_yt = False
                            await self.resolve_track(track)
                            return
                        exceptions.append(e)
                        continue

                    try:
                        result = result.tracks
                    except AttributeError:
                        pass

                    self.bot.pool.partial_track_cache[
                        f"{track.info['sourceName']}:{track.author}-{track.single_title}"
                    ] = tracks

                try:
                    if result[0].info["sourceName"] == "bandcamp":
                        check_duration = False
                except Exception:
                    pass

                has_exclude_tags = any(tag for tag in exclude_tags if tag.lower() in track.title.lower())

                tracks.extend(result)

                for t in result:
                    if t.is_stream:
                        continue

                    if not has_exclude_tags and any(tag for tag in exclude_tags if tag.lower() in t.title.lower()):
                        continue

                    if check_duration and not ((t.duration - 10000) < track.duration < (t.duration + 10000)):
                        continue

                    selected_track = t
                    break

                if selected_track:
                    break

            if not selected_track:
                try:
                    selected_track = tracks[0]
                except Exception:
                    if exceptions:
                        print("Falha ao resolver PartialTrack:\n" + "\n".join(repr(e) for e in exceptions))
                    return

            track.id = selected_track.id
            track.info["id"] = selected_track.id
            track.info["length"] = selected_track.duration
            if track.info["sourceName"] == "last.fm":
                track.info["pluginInfo"] = selected_track.info.get("pluginInfo", {})
                track.info["author"] = selected_track.author
                track.info["title"] = selected_track.title
                track.info["sourceName"] = selected_track.info["sourceName"]
                track.info["uri"] = selected_track.info["uri"]
            else:
                track.info["sourceNameOrig"] = selected_track.info["sourceName"]
                if not track.info["author"]:
                    track.info["author"] = selected_track.author
            if not track.duration:
                track.info["duration"] = selected_track.duration
            if not track.thumb:
                track.info["artworkUrl"] = selected_track.thumb

        except Exception as e:
            error_code = log_unexpected_error(
                logger, e, f"obtenção de informação da PartialTrack {track.uri or track.search_uri}"
            )
            embed = disnake.Embed(
                description=f"**Falha ao obter informação de PartialTrack:\n[{track.title}]({track.uri or track.search_uri})**"
                f"{error_code_text(error_code)}\n"
                f"**Servidor de música:** `{self.node.identifier}`",
                color=disnake.Colour.red(),
            )
            await self.report_error(embed, track)

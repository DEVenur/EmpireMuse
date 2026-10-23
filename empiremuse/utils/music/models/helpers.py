# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import logging
import re
from typing import TYPE_CHECKING

import disnake
from yt_dlp import YoutubeDL

import empiremuse.wavelink as wavelink
from empiremuse.rules.error_code import safe_error_code
from empiremuse.rules.text import plain_snippet

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore


exclude_tags = ["remix", "edit", "extend", "compilation", "mashup", "mixed"]
exclude_tags_2 = ["extend", "compilation", "mashup", "nightcore", "8d", "mixed"]

# Similaridade mínima (token_set_ratio, 0-100) entre o título da candidata e o da faixa original.
TITLE_MATCH_THRESHOLD = 75

emoji_pattern = re.compile(r"<a?:.+?:\d+?>")

# O logger leva o nome do pacote (e não o de helpers.py), como quando tudo morava em models.py.
logger = logging.getLogger(__package__)

# A mensagem do Lavalink (por exemplo, "This video is unavailable") pode ser mostrada a quem usa o bot; a causa e a pilha não.
LAVALINK_MESSAGE_LIMIT = 200
LAVALINK_LOG_LIMIT = 1000


def lavalink_text(message) -> str:
    """Mensagem de falha do Lavalink para mostrar: uma linha, truncada e dentro de um code span.

    O nó pode ser de terceiros: no code span a URL solta não vira link e ``<@id>``/``<#id>``/``@everyone`` não são
    renderizados. ``plain_snippet`` já troca a crase por apóstrofo, então o texto não fecha o span. Vazio não gera span.
    """
    text = plain_snippet(message, LAVALINK_MESSAGE_LIMIT)
    return f"`{text}`" if text else ""


def log_lavalink_failure(what: str, *, message, cause, severity, node) -> str:
    """Registra a falha do Lavalink com a causa (só no log do servidor) e devolve o código curto dela."""
    code = safe_error_code()
    logger.warning(
        "%s%s: servidor=%s, severidade=%s, mensagem=%s, causa=%s",
        what,
        f" [{code}]" if code else "",
        node,
        severity,
        plain_snippet(message, LAVALINK_LOG_LIMIT),
        plain_snippet(cause, LAVALINK_LOG_LIMIT),
    )
    return code


thread_archive_time = {
    60: 30,
    24: 720,
    2880: 720,
    10080: 2880,
}

providers_dict = {
    "youtube": "ytmsearch",
    "soundcloud": "scsearch",
    "applemusic": "amsearch",
    "deezer": "dzsearch",
    "spotify": "spsearch",
    "tidal": "tdsearch",
}

native_sources = {
    "http",
    "youtube",
    "soundcloud",
    "tts",
    "reddit",
    "ocremix",
    "tiktok",
    "mixcloud",
    "soundgasm",
    "flowerytts",
    "vimeo",
    "twitch",
    "bandcamp",
    "local",
}


def get_start_pos(player, track, extra_milliseconds=0):
    if not track.is_stream:
        difference = (
            (disnake.utils.utcnow() + datetime.timedelta(milliseconds=int(extra_milliseconds))).timestamp() * 1000
        ) - player.last_update
        position = player.last_position + difference
        if 0 < position < track.duration:
            return min(position, track.duration)
    return 0


class CustomYTDL(YoutubeDL):
    def save_cookies(self):
        pass


def music_mode(bot: BotCore):
    return wavelink.Client(bot=bot)

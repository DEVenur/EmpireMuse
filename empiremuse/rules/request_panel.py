"""Regras puras do canal de pedidos único e do painel multi-player (item 11, P4).

O canal de pedidos é um por servidor, para todo o pool. Quem envia, edita e trata as mensagens dele é UM bot, o do painel: o principal se
está no servidor, senão a primeira reserva presente. O painel mostra um bloco por player ativo; a call que ``@everyone`` não enxerga nunca
mostra faixa nem quem pediu (S-V7). Aqui só há decisões e dados; os bots, o banco e o Discord são do ``utils``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from empiremuse.rules.bot_roles import identifier_sort_key
from empiremuse.rules.servers import is_main_identifier
from empiremuse.rules.usage import clean_text

PANEL_REFRESH_MS = 3000  # no máximo uma edição do painel por servidor a cada 3 s
NAME_LIMIT = 40
TITLE_LIMIT = 100
URL_LIMIT = 250

PLAYING = "playing"
PAUSED = "paused"


class PanelPeer(NamedTuple):
    """Um bot que está no servidor, visto pela eleição: ``exclusive`` = bot exclusivo de servidor (só entra se não há mais ninguém)."""

    identifier: str
    bot_id: int
    exclusive: bool = False


class PanelEntry(NamedTuple):
    """Um player no painel. Com ``private`` não há faixa nem link (S-V7); os textos já vêm limpos e curtos."""

    bot_name: str
    bot_id: int
    voice_name: str
    private: bool
    title: str | None
    url: str | None
    state: str
    queue: int
    requester: str | None = None


def elect_panel_bot(peers: Iterable[PanelPeer]) -> int | None:
    """Id do bot do painel: o principal se está no servidor; senão a 1ª reserva (ordem natural do ``identifier``); por último um exclusivo."""
    ordered = sorted(
        peers, key=lambda p: (p.exclusive, not is_main_identifier(p.identifier), identifier_sort_key(p.identifier))
    )
    return ordered[0].bot_id if ordered else None


def make_entry(
    *,
    bot_name: object,
    bot_id: int,
    voice_name: object,
    private: bool,
    title: object,
    url: object,
    paused: bool,
    queue: int,
    requester: object = None,
) -> PanelEntry:
    """A entrada do painel. Call privada: sem faixa, sem link e sem quem pediu, aconteça o que acontecer com o que veio de fora."""
    return PanelEntry(
        bot_name=clean_text(bot_name, NAME_LIMIT) or "bot",
        bot_id=bot_id,
        voice_name=clean_text(voice_name, NAME_LIMIT) or "call",
        private=bool(private),
        title=None if private else (clean_text(title, TITLE_LIMIT) or None),
        url=None if private else (clean_text(url, URL_LIMIT) or None),
        state=PAUSED if paused else PLAYING,
        queue=max(0, int(queue)),
        requester=None if private else (clean_text(requester, NAME_LIMIT) or None),
    )


def choose_player(candidates: Sequence[tuple[int, int | None]], member_voice_id: int | None) -> int | None:
    """Id do bot cujo player está na call de quem apertou, ou ``None``.

    ``candidates``: ``(id do bot, id da call onde o player está)`` na ordem de prioridade. Quem não está em call, ou está numa call sem
    player, não tem player (nunca cai no de outra call).
    """
    if member_voice_id is None:
        return None
    return next((bot_id for bot_id, voice_id in candidates if voice_id == member_voice_id), None)


def refresh_wait_ms(last_ms: int | None, now_ms: int) -> int:
    """Quanto falta (em ms) para a próxima edição do painel poder sair; 0 = já pode."""
    if last_ms is None or now_ms < last_ms:
        return 0
    return max(0, PANEL_REFRESH_MS - (now_ms - last_ms))

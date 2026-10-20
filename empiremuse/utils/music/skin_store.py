"""Leitura única das skins personalizadas do servidor (``custom_skins`` e ``custom_skins_static`` do documento global).

``load_custom_skins`` é a ÚNICA porta de leitura da skin: converte o texto legado (``base64`` de ``pickle``) com
``load_legacy(texto, "skin")`` (allowlist vazia), valida tudo com ``validate_skin`` (também o dicionário já gravado: é
defesa contra dicionário plantado no banco), troca o texto por dicionário NO documento e grava o documento inteiro UMA vez,
só se algo mudou. O que for recusado continua como está no documento (o texto legado não se perde), não chega ao player (que
usa a skin padrão) e deixa um aviso só com o servidor e o código da falha. ``""``, ``{}`` e ``None`` valem como sem skin.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import NamedTuple, Union

from empiremuse.serialization.legacy_pickle import load_legacy
from empiremuse.serialization.schema import SchemaError
from empiremuse.serialization.skins import MAX_QUEUE_ENTRIES, validate_skin
from empiremuse.utils.db import DBModel

logger = logging.getLogger(__name__)

MODES = ("custom_skins", "custom_skins_static")
LEGACY_QUEUE_ENTRIES_LIMIT = 99  # o ``skin_converter`` antigo aceitava até 2 dígitos


class LoadedSkins(NamedTuple):
    normal: dict
    static: dict
    rejected: int  # skins com conteúdo que não chegam ao player (texto ilegível ou fora do esquema)


def _clamp_legacy_queue_entries(skin: object) -> object:
    """No texto legado, ``queue_max_entries`` de 26 a 99 vale 25: a skin antiga não fica indisponível por isso."""
    if type(skin) is dict:
        value = skin.get("queue_max_entries")
        if type(value) is int and MAX_QUEUE_ENTRIES < value <= LEGACY_QUEUE_ENTRIES_LIMIT:
            skin["queue_max_entries"] = MAX_QUEUE_ENTRIES
    return skin


async def load_custom_skins(bot, guild_id: Union[int, str], global_data: dict) -> LoadedSkins:
    """As skins válidas do servidor (``normal`` e ``static``: ``{nome: dicionário limpo}``) e quantas foram recusadas."""

    def read_skin_entries(entries: list) -> tuple[list, list]:
        """``(trocas, lidas)`` para cada ``(modo, nome, valor)``; roda fora do laço de eventos."""
        swaps, results = [], []
        for mode, name, value in entries:
            try:
                if isinstance(value, str):
                    skin = validate_skin(_clamp_legacy_queue_entries(load_legacy(value, "skin")))
                    swaps.append((mode, name, skin))
                    skin = copy.deepcopy(skin)  # o documento e quem lê não dividem o mesmo objeto
                else:
                    skin = validate_skin(value)
            except SchemaError as error:  # inclui LegacyFormatError
                logger.warning(
                    "Skin personalizada ignorada (formato incompatível): servidor %s, motivo %s", guild_id, error.code
                )
                skin = None
            results.append((mode, name, skin))
        return swaps, results

    entries = [(mode, name, value) for mode in MODES for name, value in global_data[mode].items() if value]
    swaps, results = await asyncio.get_running_loop().run_in_executor(None, read_skin_entries, entries)

    for mode, name, skin in swaps:
        global_data[mode][name] = skin
    if swaps:
        try:
            await bot.update_global_data(guild_id, global_data, db_name=DBModel.guilds)
        except Exception as error:  # a leitura segue com o que está na memória; o banco recebe na próxima vez
            logger.warning("Skins migradas, mas o documento não foi gravado: %s", type(error).__name__)

    loaded: dict[str, dict] = {mode: {} for mode in MODES}
    rejected = 0
    for mode, name, skin in results:
        if skin is None:
            rejected += 1
        else:
            loaded[mode][name] = skin
    return LoadedSkins(loaded["custom_skins"], loaded["custom_skins_static"], rejected)

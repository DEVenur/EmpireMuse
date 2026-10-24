"""Leitura única das skins personalizadas do servidor (``custom_skins`` e ``custom_skins_static`` do documento global).

``load_custom_skins`` é a ÚNICA porta de leitura da skin: valida cada dicionário do documento com ``validate_skin`` (defesa
contra dicionário plantado no banco). A skin gravada como texto (formato antigo) não é lida: fica como está no documento, não
chega ao player (que usa a skin padrão) e deixa um aviso só com o servidor. Qualquer outra recusa também fica no documento e
deixa um aviso só com o servidor e o código da falha. ``""``, ``{}`` e ``None`` valem como sem skin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple, Union

from empiremuse.serialization.schema import SchemaError
from empiremuse.serialization.skins import validate_skin

logger = logging.getLogger(__name__)

MODES = ("custom_skins", "custom_skins_static")


class LoadedSkins(NamedTuple):
    normal: dict
    static: dict
    rejected: int  # skins com conteúdo que não chegam ao player (texto do formato antigo ou fora do esquema)


async def load_custom_skins(bot, guild_id: Union[int, str], global_data: dict) -> LoadedSkins:
    """As skins válidas do servidor (``normal`` e ``static``: ``{nome: dicionário limpo}``) e quantas foram recusadas."""

    def read_skin_entries(entries: list) -> list:
        """``(modo, nome, skin ou None)`` para cada ``(modo, nome, valor)``; roda fora do laço de eventos."""
        results = []
        for mode, name, value in entries:
            skin = None
            if isinstance(value, str):
                logger.warning("Skin personalizada ignorada (formato antigo, não suportado): servidor %s", guild_id)
            else:
                try:
                    skin = validate_skin(value)
                except SchemaError as error:
                    logger.warning(
                        "Skin personalizada ignorada (formato incompatível): servidor %s, motivo %s",
                        guild_id,
                        error.code,
                    )
            results.append((mode, name, skin))
        return results

    entries = [(mode, name, value) for mode in MODES for name, value in global_data[mode].items() if value]
    results = await asyncio.get_running_loop().run_in_executor(None, read_skin_entries, entries)

    loaded: dict[str, dict] = {mode: {} for mode in MODES}
    rejected = 0
    for mode, name, skin in results:
        if skin is None:
            rejected += 1
        else:
            loaded[mode][name] = skin
    return LoadedSkins(loaded["custom_skins"], loaded["custom_skins_static"], rejected)

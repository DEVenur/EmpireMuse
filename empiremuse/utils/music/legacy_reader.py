"""Leitura dos dados antigos (sessões, filas salvas e skins em ``pickle``) e descarte dos caches antigos.

Etapa 2b da F3-6b ("chave de corte"): nenhum ponto do produto lê ``pickle`` sozinho; tudo passa por
``empiremuse.serialization.legacy_pickle.load_legacy``, que recusa o que não for um dado legado bem formado. A recusa é
sempre tratada aqui (aviso no log só com o servidor e o motivo, nunca o conteúdo) e o dado recusado fica onde está.
Sai junto com as etapas 3 a 5, quando os formatos passam a ser JSON.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, Union

from empiremuse.serialization.legacy_pickle import LegacyFormatError, load_legacy

logger = logging.getLogger(__name__)


async def read_legacy_session(raw: Union[bytes, str], guild_id: Union[int, str]) -> Optional[dict]:
    """A sessão do player (``raw`` = bytes do arquivo ou texto base64 do Mongo), ou ``None`` se foi recusada."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: load_legacy(raw, "session"))
    except LegacyFormatError as error:
        logger.warning("Sessão do player ignorada (formato incompatível): servidor %s, motivo %s", guild_id, error.code)
        return None


def discard_legacy_cache(path: Path) -> None:
    """Apaga um cache antigo SEM abri-lo (cache não é dado do usuário: recomeça vazio). Falhar não derruba a subida."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        logger.warning("Não foi possível apagar o cache antigo %s: %s", path.name, type(error).__name__)
        return
    logger.info("Cache antigo descartado: %s", path.name)

"""Descarte dos caches antigos em ``pickle`` (playlist e Last.fm).

Cache não é dado do usuário: o arquivo antigo é apagado sem ser aberto e o cache recomeça vazio em JSON. A leitura das sessões,
filas salvas e skins antigas fica com a migração de cada formato (``session_store``, ``saved_queue`` e ``skin_store``).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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

"""Arquivos de cache em JSON (playlist e Last.fm): gravação atômica 0600 e leitura que nunca derruba a inicialização."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from empiremuse.serialization.cache import decode_cache, encode_cache
from empiremuse.serialization.files import write_private_atomic
from empiremuse.serialization.schema import SchemaError

logger = logging.getLogger(__name__)


def save_json_cache(
    path: Path, items: Iterable[tuple[Any, Any]], *, max_bytes: int, saved_at: float | None = None
) -> None:
    """Grava os ``items`` em ``path`` (itens inválidos ficam de fora); falha de disco levanta ``OSError``."""
    write_private_atomic(path, encode_cache(items, max_bytes=max_bytes, saved_at=saved_at))


def load_json_cache(path: Path, *, max_bytes: int, max_age: float) -> dict:
    """``{chave: valor}`` do cache em ``path`` ainda dentro do prazo, ou ``{}`` (arquivo ausente, grande, velho ou ruim).

    O arquivo ruim é mantido (o próximo ``save_json_cache`` o substitui) e o aviso não leva o conteúdo.
    """
    try:
        with open(path, "rb") as file:
            raw = file.read(max_bytes + 1)
    except FileNotFoundError:
        return {}
    except OSError as error:
        logger.warning("Cache %s não pôde ser lido: %s", path.name, type(error).__name__)
        return {}
    try:
        return decode_cache(raw, max_bytes=max_bytes, max_age=max_age)
    except SchemaError as error:
        logger.warning("Cache %s ignorado (formato incompatível): %s", path.name, error.code)
        return {}

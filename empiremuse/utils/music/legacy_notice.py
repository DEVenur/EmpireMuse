"""Aviso, na subida, dos dados do formato antigo (``.pkl``) que o bot não lê mais.

Só lista nomes e conta arquivos: nada é aberto, lido nem apagado. Quem quiser recuperar algo deve usar uma versão anterior do
bot; o que não for mais necessário pode ser apagado à mão.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from empiremuse import paths

logger = logging.getLogger(__name__)

# pastas de ``local_database/`` do formato antigo (sessões do player e filas salvas) e as extensões que o bot gravava nelas
LEGACY_FOLDERS = {"player_sessions": (".pkl", ".bak"), "saved_queues_v1": (".pkl",)}
# caches que o formato antigo gravava: a pasta ``local_database/`` e a raiz de execução
LEGACY_CACHE_FILES = ("playlist_cache.pkl", "partial_track_cache.pkl", ".lyric_cache_data")
LEGACY_ROOT_CACHE_FILES = (".lastfm_cache",)


def _count_files(folder: Path, extensions: tuple[str, ...]) -> int:
    """Arquivos com uma das extensões em ``folder`` e subpastas, só pelo nome (``os.walk`` não segue link simbólico)."""
    return sum(1 for _, _, names in os.walk(folder) for name in names if name.endswith(extensions))


def log_ignored_legacy_data() -> None:
    """Um aviso por pasta e um para os caches do formato antigo que ainda existem; sem nada antigo, não loga."""
    database = paths.RUNTIME_DIR / "local_database"
    for name, extensions in LEGACY_FOLDERS.items():
        count = _count_files(database / name, extensions)
        if count:
            logger.warning(
                "Dados do formato antigo ignorados (nunca são lidos): %s arquivo(s) em local_database/%s. "
                "Podem ser apagados; refaça o que for preciso (ex.: salvar a fila de novo).",
                count,
                name,
            )
    caches = [database / name for name in LEGACY_CACHE_FILES] + [
        paths.RUNTIME_DIR / name for name in LEGACY_ROOT_CACHE_FILES
    ]
    present = [path.name for path in caches if path.is_file()]
    if present:
        logger.info("Caches do formato antigo ignorados (podem ser apagados): %s", ", ".join(present))

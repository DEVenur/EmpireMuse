"""Saúde do container por heartbeat: o bot grava um carimbo de tempo e o ``HEALTHCHECK`` confere a idade dele.

Só stdlib e nenhum import do bot: ``python -m empiremuse.health`` roda no ``HEALTHCHECK`` sem carregar disnake, aiohttp
nem tornado. O bot só renova o arquivo enquanto ``is_healthy`` for verdadeiro; um bot travado, sem Lavalink ou fora do
ar para de renová-lo e o arquivo envelhece até o container ficar ``unhealthy``.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

HEALTH_FILE_ENV = "EMPIREMUSE_HEALTH_FILE"
MAX_AGE_SECONDS = 60
HEARTBEAT_INTERVAL = 15
_MAX_FILE_BYTES = 64


def is_healthy(bots_ready: Sequence[bool], nodes_expected: bool, nodes_available: int) -> bool:
    """Há ao menos um bot, todos prontos e, se havia nós a conectar, ao menos um nó disponível."""
    if not bots_ready or not all(bots_ready):
        return False
    return nodes_available >= 1 or not nodes_expected


def write_heartbeat(path: str | os.PathLike[str], now: float) -> None:
    """Grava ``now`` de forma atômica: temporário no mesmo diretório e ``os.replace`` (nunca um arquivo parcial)."""
    target = os.fspath(path)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(target) or ".", prefix=".health-")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(f"{now!r}\n")
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def clear_heartbeat(path: str | os.PathLike[str]) -> None:
    """Apaga o heartbeat que sobrou de uma execução anterior (um restart do mesmo container não pode herdá-lo)."""
    Path(path).unlink(missing_ok=True)


def is_fresh(path: str | os.PathLike[str], now: float, max_age: float = MAX_AGE_SECONDS) -> bool:
    """O arquivo existe, traz um carimbo legível e ele está a no máximo ``max_age`` segundos de ``now``."""
    try:
        with open(path, encoding="ascii") as file:
            stamp = float(file.read(_MAX_FILE_BYTES))
    except OSError, ValueError:
        return False
    return abs(now - stamp) <= max_age


def main() -> int:
    """0 se o heartbeat está fresco; 1 se está velho, ausente ou se ``EMPIREMUSE_HEALTH_FILE`` não foi definida."""
    path = os.environ.get(HEALTH_FILE_ENV)
    if not path:
        return 1
    return 0 if is_fresh(path, time.time()) else 1


if __name__ == "__main__":
    sys.exit(main())

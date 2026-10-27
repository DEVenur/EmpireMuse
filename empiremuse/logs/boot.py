"""Relatório de subida (item 7, P2): as etapas da subida como linhas do logger ``empiremuse.boot``, e o aviso de versão nova."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Literal

import aiohttp

from empiremuse.rules.release import Version, pick_target
from empiremuse.updater import releases
from empiremuse.version import image_version

Status = Literal["ok", "warn", "fail"]

BOOT_LOGGER = "empiremuse.boot"
STATUS_LEVELS: dict[str, int] = {"ok": logging.INFO, "warn": logging.WARNING, "fail": logging.ERROR}
VERSION_CHECK_TIMEOUT = 10.0

logger = logging.getLogger(__name__)


class BootReport:
    """Uma linha por etapa da subida, no nível do resultado: ok → INFO, warn → WARNING, fail → ERROR.

    O redator e o agregador do pacote ``logs`` valem sozinhos: o ``detail`` pode citar o que for útil sem mascarar nada à mão, mas
    nunca deve receber URI de banco, host ou senha de nó (o contrato manda só latência, tipo do erro e identificador).
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(BOOT_LOGGER)
        self._deferred: list[tuple[str, Status, str]] = []
        self._lock = threading.Lock()

    def step(self, name: str, status: Status, detail: str = "", *, elapsed: float | None = None) -> None:
        """Emite a etapa agora."""
        detail_part = f": {detail}" if detail else ""
        elapsed_part = f" ({elapsed * 1000:.0f} ms)" if elapsed is not None else ""
        self._logger.log(STATUS_LEVELS[status], "%s%s%s", name, detail_part, elapsed_part)

    def defer(self, name: str, status: Status, detail: str = "") -> None:
        """Guarda uma etapa que acontece antes do ``configure_logging``; ``flush_deferred`` a emite, na ordem."""
        with self._lock:
            self._deferred.append((name, status, detail))

    def flush_deferred(self) -> None:
        """Emite as etapas guardadas (uma vez só) e esvazia a fila."""
        with self._lock:
            pending, self._deferred = self._deferred, []
        for name, status, detail in pending:
            self.step(name, status, detail)


async def check_new_version(
    *,
    list_releases: Callable[[aiohttp.ClientSession], Awaitable[list[releases.Release]]] = releases.list_releases,
    current: Callable[[], Version | None] = image_version,
    timeout: float = VERSION_CHECK_TIMEOUT,
) -> None:
    """Avisa (INFO) quando há uma release maior que a instalada; roda em tarefa de fundo e nunca atrapalha a subida.

    Sem versão instalada conhecida (checkout git, ``dev``) não há o que comparar. Erro ou tempo esgotado viram uma linha DEBUG.
    """
    try:
        installed = current()
        if installed is None:
            return
        async with asyncio.timeout(timeout), aiohttp.ClientSession() as session:
            found = await list_releases(session)
        target = pick_target(installed, (release.version for release in found))
    except TimeoutError:
        logger.debug("Consulta de versão nova: tempo esgotado.")
    except Exception as error:
        logger.debug("Consulta de versão nova falhou (%s).", type(error).__name__)
    else:
        if target is not None:
            BootReport().step("Atualização", "ok", f"Versão {target} disponível (instalada {installed})")

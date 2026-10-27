"""Guarda de boot do fluxo git: se o código novo não chega a ficar pronto em poucas subidas, volta ao commit anterior.

Roda em ``__main__.main()`` ANTES de importar o ``BotPool`` (um erro de import no código novo derrubaria o bot antes de
qualquer outra proteção). Só stdlib no import. Só age quando existe um pendente do fluxo git: cada subida soma um ``boots``;
o pendente é apagado pelo aviso pós-boot quando o bot fica pronto, então só quem nunca fica pronto chega ao limite. O fluxo
Docker não é tocado (quem desfaz é o auxiliar, com ``--wait``).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
from pathlib import Path

from empiremuse.updater.git_flow import EXIT_RESTART, Runner, UpdateError, restore_checkout, run_exec
from empiremuse.updater.state import read_pending, write_pending

logger = logging.getLogger(__name__)

MAX_BOOTS_WITHOUT_READY = 2


def run(
    runtime_dir: Path, repo_dir: Path, now: float, *, python: str = sys.executable, runner: Runner = run_exec
) -> None:
    """Conta a subida e, no terceiro boot sem o bot ficar pronto, reverte o código e sai com ``EXIT_RESTART`` (75)."""
    pending = read_pending(runtime_dir, now)
    if pending is None or pending.flow != "git" or pending.status != "pending":
        return
    boots = pending.boots + 1
    if boots <= MAX_BOOTS_WITHOUT_READY:
        write_pending(runtime_dir, dataclasses.replace(pending, boots=boots))
        return
    # Marca antes de reverter: se a reversão falhar, as próximas subidas não repetem a tentativa em laço.
    write_pending(runtime_dir, dataclasses.replace(pending, boots=boots, status="rolled_back"))
    logger.error("O código novo não ficou pronto em %d subidas; voltando ao commit anterior.", MAX_BOOTS_WITHOUT_READY)
    try:
        if pending.prev_sha is None:
            raise UpdateError("sem commit anterior")
        asyncio.run(restore_checkout(Path(repo_dir), pending.prev_sha, python=python, runner=runner))
    except UpdateError:
        logger.error("A reversão automática para o commit anterior falhou; confira o servidor.")
    raise SystemExit(EXIT_RESTART)

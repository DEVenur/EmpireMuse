"""Como esta instalação se atualiza: ``panel`` (imagem Docker gerenciada), ``git`` (clone) ou ``manual`` (código solto)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from empiremuse.version import running_from_image

MODE_DOCKER = "docker"
MODE_PANEL = "panel"
MODE_GIT = "git"
MODE_MANUAL = "manual"


def update_mode(config: Mapping[str, Any], environ: Mapping[str, str], project_dir: Path) -> str:
    """``panel`` se roda numa imagem (``EMPIREMUSE_VERSION``), ``git`` se ``<projeto>/.git`` é um diretório, senão ``manual``.

    ``docker`` vem antes de todos: com o proxy de atualização configurado (``UPDATE_PROXY_SOCKET``) o bot se atualiza
    sozinho pelo auxiliar, esteja ou não numa imagem.
    """
    if config.get("UPDATE_PROXY_SOCKET"):
        return MODE_DOCKER
    if running_from_image(environ):
        return MODE_PANEL
    if (Path(project_dir) / ".git").is_dir():
        return MODE_GIT
    return MODE_MANUAL

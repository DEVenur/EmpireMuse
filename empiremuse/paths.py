"""Ponto central de resolução de diretórios e caminhos do EmpireMuse."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


DEV_RUNTIME_NAME = ".runtime"


def dev_runtime_dir() -> Path | None:
    """Pasta de execução de desenvolvimento (`PROJECT_DIR/.runtime`), ou `None` quando ela não vale.

    Só vale sem `EMPIREMUSE_HOME` e com a `.runtime` existindo como diretório. Em produção (Docker, Pterodactyl,
    Discloud) ela não existe ou é ignorada, e o comportamento continua o de antes.
    """
    if os.environ.get("EMPIREMUSE_HOME"):
        return None
    candidate = PROJECT_DIR / DEV_RUNTIME_NAME
    return candidate.resolve() if candidate.is_dir() else None


def get_runtime_dir() -> Path:
    env_val = os.environ.get("EMPIREMUSE_HOME")
    if env_val:
        return Path(env_val).resolve()
    return dev_runtime_dir() or Path.cwd().resolve()


def __getattr__(name: str):
    if name == "RUNTIME_DIR":
        return get_runtime_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

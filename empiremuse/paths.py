"""Ponto central de resolução de diretórios e caminhos do EmpireMuse."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def get_runtime_dir() -> Path:
    env_val = os.environ.get("EMPIREMUSE_HOME")
    if env_val:
        return Path(env_val).resolve()
    return Path.cwd().resolve()


def __getattr__(name: str):
    if name == "RUNTIME_DIR":
        return get_runtime_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

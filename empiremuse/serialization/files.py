"""Gravação de arquivos de dados: atômica (temporário no mesmo diretório + ``os.replace``) e só para o dono (0600)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

PRIVATE_MODE = 0o600


def write_private_atomic(path: Path, data: bytes) -> None:
    """Grava ``data`` em ``path`` sem nunca deixar o arquivo pela metade: ou fica o antigo, ou fica o novo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as file:
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), PRIVATE_MODE)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise

"""Gravação de arquivos de dados: atômica (temporário no mesmo diretório + ``os.replace``) e só para o dono (0600)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .schema import TOO_BIG, SchemaError

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


def read_capped(path: Path, limit: int) -> bytes:
    """O conteúdo do arquivo, se couber em ``limit`` bytes; maior que isso é ``SchemaError`` (``too_big``), sem ler o arquivo todo.

    Regra para toda leitura de arquivo de dados: conferir o tamanho (``lstat``) ANTES de ler e nunca pedir mais que
    ``limit + 1`` bytes. O ``open`` segue link simbólico; quem fecha o caso é o teto no ``read`` (o arquivo pode crescer depois da
    conferência). Arquivo ausente ou pasta continuam sendo ``OSError``.
    """
    if path.lstat().st_size > limit:
        raise SchemaError("", TOO_BIG)
    with open(path, "rb") as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise SchemaError("", TOO_BIG)
    return raw

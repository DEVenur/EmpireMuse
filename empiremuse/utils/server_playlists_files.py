# -*- coding: utf-8 -*-
"""Arquivos de playlists que acompanham o bot (``data/playlists/*.json``), importáveis por admins de qualquer servidor (D8).

Só nomes que existem na pasta, só arquivo regular (nem link simbólico) e só com o pai resolvido igual à pasta: o valor vindo do
Discord nunca vira caminho. As funções fazem E/S de arquivo (pequena); quem chama de dentro do laço usa ``asyncio.to_thread``.
"""

from __future__ import annotations

import re
from pathlib import Path

from empiremuse import paths
from empiremuse.rules.errors import FILE_FORMAT, FILE_TOO_LARGE, RuleError
from empiremuse.rules.limits import PLAYLIST_FILE_MAX_BYTES
from empiremuse.rules.playlists import check_import_filename

IMPORT_DIR = paths.PROJECT_DIR / "data" / "playlists"
_NAME = re.compile(r"[a-z0-9-]{1,64}\.json")


def _is_plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def list_import_files(folder: Path = IMPORT_DIR) -> tuple[str, ...]:
    """Os nomes importáveis (``[a-z0-9-]{1,64}.json``, arquivo regular, não link), em ordem alfabética."""
    try:
        return tuple(
            sorted(item.name for item in folder.iterdir() if _NAME.fullmatch(item.name) and _is_plain_file(item))
        )
    except OSError:
        return ()


def read_import_file(folder: Path, name: object) -> bytes | RuleError:
    """O conteúdo do arquivo ``name`` da pasta, ou ``RuleError`` (nome fora da lista, link, fora da pasta, grande demais)."""
    checked = check_import_filename(name, list_import_files(folder))
    if isinstance(checked, RuleError):
        return checked
    path = folder / checked
    try:
        if not _is_plain_file(path) or path.resolve().parent != folder.resolve():
            return RuleError(FILE_FORMAT)
        with open(path, "rb") as handle:
            data = handle.read(PLAYLIST_FILE_MAX_BYTES + 1)  # lê um byte além do teto: nunca o arquivo inteiro
    except OSError:
        return RuleError(FILE_FORMAT)
    return RuleError(FILE_TOO_LARGE, limit=PLAYLIST_FILE_MAX_BYTES) if len(data) > PLAYLIST_FILE_MAX_BYTES else data

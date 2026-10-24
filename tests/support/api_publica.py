"""Leitura do código-fonte de cada "família" de módulos (``music``, ``models`` e ``interactions``).

Cada família é o arquivo original MAIS o que ele virou na divisão (``cogs/music.py`` + ``music_cog/``; ``models.py`` ou
``models/``; ``interactions.py`` ou ``interactions/``). Os testes que leem o código-fonte para provar uma ausência (por
exemplo, "não há ``repr(e)``") precisam ler a família inteira, não só o ``__init__`` fino.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.support.raiz import RAIZ

PACOTE = RAIZ / "empiremuse"

# Família -> (módulo importável, arquivos que formam o código dela, relativos a ``empiremuse/``).
FAMILIAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "music": ("empiremuse.cogs.music", ("cogs/music.py", "music_cog")),
    "models": ("empiremuse.utils.music.models", ("utils/music/models.py", "utils/music/models")),
    "interactions": (
        "empiremuse.utils.music.interactions",
        ("utils/music/interactions.py", "utils/music/interactions"),
    ),
}


def arquivos_da_familia(familia: str) -> list[Path]:
    """Os ``.py`` da família que existem hoje (o arquivo único ou a pasta do pacote), em ordem estável."""
    achados: list[Path] = []
    for relativo in FAMILIAS[familia][1]:
        caminho = PACOTE / relativo
        if caminho.is_file():
            achados.append(caminho)
        elif caminho.is_dir():
            achados.extend(p for p in caminho.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(achados)


def fonte_da_familia(familia: str) -> str:
    """O texto de TODOS os arquivos da família, concatenado.

    Os testes que leem o código-fonte (``Path(modulo.__file__).read_text()``) passam a ler só o ``__init__`` fino depois
    da divisão: uma asserção negativa ("não há ``repr(e)``") passaria no vazio. Eles devem ler a família inteira.
    """
    return "\n".join(arquivo.read_text(encoding="utf-8") for arquivo in arquivos_da_familia(familia))


def arvore_da_familia(familia: str) -> ast.Module:
    """Um ``ast.Module`` com o corpo de todos os arquivos da família (para ``ast.walk`` sobre a família toda)."""
    corpo: list[ast.stmt] = []
    for arquivo in arquivos_da_familia(familia):
        corpo.extend(ast.parse(arquivo.read_text(encoding="utf-8")).body)
    return ast.Module(body=corpo, type_ignores=[])

"""Leitura do código-fonte de cada "família" de módulos (``music``, ``models`` e ``interactions``).

Cada família é o arquivo original MAIS o que ele virou na divisão (``cogs/music.py`` + ``music_cog/``; ``models.py`` ou
``models/``; ``interactions.py`` ou ``interactions/``). Os testes que leem o código-fonte para provar uma ausência (por
exemplo, "não há ``repr(e)``") precisam ler a família inteira, não só o ``__init__`` fino.
"""

from __future__ import annotations


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

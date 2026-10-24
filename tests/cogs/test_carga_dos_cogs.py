"""KI-29 — guarda do carregador de extensões e da importabilidade dos módulos de música.

``BotCore.load_modules`` faz ``os.walk`` em ``empiremuse/cogs/`` e carrega como extensão TODO ``.py`` que não comece
com ``__``. Um arquivo novo ali sem ``setup(bot)`` derruba a subida (``NoEntryPointError``). Por isso o código que sai
de ``cogs/music.py`` na divisão do KI-29 mora fora de ``cogs/`` (``empiremuse/music_cog/``).
"""

import importlib
import os

import pytest

from tests.support.api_publica import PACOTE

COGS = PACOTE / "cogs"


def arquivos_de_cog() -> list:
    """Exatamente os arquivos que o ``load_modules`` tenta carregar (mesma regra de ``os.walk`` e de nome)."""
    achados = []
    for pasta, _, arquivos in os.walk(COGS):
        for nome in arquivos:
            if nome.endswith(".py") and not nome.startswith("__"):
                achados.append(os.path.join(pasta, nome))
    return sorted(achados)


@pytest.mark.smoke
@pytest.mark.parametrize("caminho", arquivos_de_cog(), ids=lambda c: os.path.relpath(c, COGS))
def test_cada_cog_importa(caminho):
    modulo = importlib.import_module("empiremuse.cogs." + os.path.splitext(os.path.basename(caminho))[0])
    assert callable(modulo.setup)

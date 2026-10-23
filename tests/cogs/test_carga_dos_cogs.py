"""KI-29 — guarda do carregador de extensões e da importabilidade dos módulos de música.

``BotCore.load_modules`` faz ``os.walk`` em ``empiremuse/cogs/`` e carrega como extensão TODO ``.py`` que não comece
com ``__``. Um arquivo novo ali sem ``setup(bot)`` derruba a subida (``NoEntryPointError``). Por isso o código que sai
de ``cogs/music.py`` na divisão do KI-29 mora fora de ``cogs/`` (``empiremuse/music_cog/``).
"""

import ast
import importlib
import os
import pkgutil

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


def tem_setup(caminho: str) -> bool:
    arvore = ast.parse(open(caminho, encoding="utf-8").read())
    return any(isinstance(no, ast.FunctionDef) and no.name == "setup" for no in arvore.body)


@pytest.mark.parametrize("caminho", arquivos_de_cog(), ids=lambda c: os.path.relpath(c, COGS))
def test_todo_arquivo_que_o_load_modules_carrega_tem_setup(caminho):
    assert tem_setup(caminho), f"{caminho}: sem setup(bot), o load_modules o carrega como extensão e falha"


def test_o_load_modules_enxerga_os_cogs_conhecidos():
    nomes = {os.path.basename(c) for c in arquivos_de_cog()}
    assert {"music.py", "music_settings.py", "player_resume.py", "legacy_cmds.py", "lastfm.py"} <= nomes


def test_os_cogs_ficam_na_raiz_de_cogs():
    """O ``load_modules`` monta ``empiremuse.cogs.<arquivo>`` sem a subpasta: um cog numa subpasta não carregaria."""
    fora_da_raiz = [c for c in arquivos_de_cog() if os.path.dirname(c) != str(COGS)]
    assert not fora_da_raiz, fora_da_raiz


@pytest.mark.parametrize("caminho", arquivos_de_cog(), ids=lambda c: os.path.relpath(c, COGS))
def test_cada_cog_importa(caminho):
    modulo = importlib.import_module("empiremuse.cogs." + os.path.splitext(os.path.basename(caminho))[0])
    assert callable(modulo.setup)


def modulos_de_musica() -> list[str]:
    pacote = importlib.import_module("empiremuse.utils.music")
    return sorted(m.name for m in pkgutil.walk_packages(pacote.__path__, pacote.__name__ + "."))


@pytest.mark.parametrize("nome", modulos_de_musica())
def test_cada_modulo_de_utils_music_importa(nome):
    importlib.import_module(nome)


def test_a_lista_de_modulos_de_musica_inclui_os_tres_arquivos_grandes():
    nomes = set(modulos_de_musica())
    assert {"empiremuse.utils.music.models", "empiremuse.utils.music.interactions"} <= nomes

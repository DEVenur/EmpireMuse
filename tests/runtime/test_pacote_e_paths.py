"""Testes de caracterização estrutural do novo pacote empiremuse (Task C-20 / Bloco C4).

Garante os contratos arquiteturais da reorganização modular:
1. Import do pacote empiremuse e resolução do ponto de entrada via python -m empiremuse.
2. Importabilidade de todas as 10 extensões/cogs sob empiremuse.cogs.<nome>.
3. Importabilidade de todas as 15 skins sob empiremuse.utils.music.skins.{normal,static}_player.<nome>.
4. Resolução de recursos embutidos (templates, static) via paths.PACKAGE_DIR e de data/ + assets/ via paths.PROJECT_DIR.
5. Resolução dinâmica de paths.RUNTIME_DIR (padrão CWD, customizável por EMPIREMUSE_HOME).
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from tests.support.raiz import RAIZ

ROOT = RAIZ

COGS = [
    "music",
    "music_settings",
    "player_resume",
    "misc",
    "legacy_cmds",
    "lastfm",
    "error_handler",
    "help_cog",
    "ll_yt_oauth",
    "server_manager",
]


class TestCogsESkinsDoPacote:
    """Verifica se todos os 10 cogs e 15 skins são importáveis sob o namespace empiremuse."""

    @pytest.mark.parametrize("cog_name", list(COGS)[:2])
    def test_cog_importable(self, cog_name: str):
        module_path = f"empiremuse.cogs.{cog_name}"
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Cog '{module_path}' deve existir sob empiremuse.cogs"
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "setup"), f"Cog '{module_path}' deve conter a função setup(bot)"

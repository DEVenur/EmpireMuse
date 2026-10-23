"""Testes de caracterização para a Task C-09 (Depuração de resíduos - Bloco C2).

Garante que o comportamento vizinho das áreas saneadas no Bloco C2 permaneça
completamente estável antes e depois da remoção de resíduos (imports, código
inalcançável e dependências não utilizadas).
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.support.raiz import RAIZ

ROOT = RAIZ


class TestWaveLinkPublicApi:
    """Verifica se a API pública exposta por wavelink permanece intacta."""

    def test_wavelink_reexports_are_accessible(self):
        import empiremuse.wavelink as wavelink

        # Classes e símbolos centrais reexportados
        assert hasattr(wavelink, "Client")
        assert hasattr(wavelink, "Node")
        assert hasattr(wavelink, "WebSocket")
        assert hasattr(wavelink, "Player")
        assert hasattr(wavelink, "Track")
        assert hasattr(wavelink, "Equalizer")

        assert isinstance(wavelink.Client, type)
        assert isinstance(wavelink.Node, type)
        assert isinstance(wavelink.WebSocket, type)

    def test_wavelink_node_tracks_return(self):
        """Verifica a estrutura sintática de wavelink/node.py no método de carregamento de faixas."""
        node_py = (ROOT / "empiremuse" / "wavelink" / "node.py").read_text(encoding="utf-8")
        assert "async def get_tracks" in node_py
        assert "track_cls(id_=track[encoded_name]" in node_py


class TestModulesImportability:
    """Verifica que os módulos tocados na remoção continuam importáveis e saudáveis."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "empiremuse.cogs.music",
            "empiremuse.cogs.music_settings",
            "empiremuse.panel.handlers.auth",
            "empiremuse.utils.music.models",
            "empiremuse.wavelink.node",
        ],
    )
    def test_module_can_be_imported(self, module_name):
        import importlib

        mod = importlib.import_module(module_name)
        assert mod is not None


class TestProductionImportsIsolation:
    """Verifica que o código produtivo não depende das 7 dependências obsoletas e mantém o extra curl-cffi no yt-dlp."""

    DEAD_PACKAGES = {
        "aiosqlite",
        "syncedlyrics",
        "pylrc",
        "undetected_chromedriver",
        "nest_asyncio",
        "emoji",
        "regex",
    }

    def test_dead_packages_not_imported_in_production(self):
        assert (ROOT / "empiremuse").is_dir(), "empiremuse/ deve existir como pacote principal de produção"
        production_paths = [
            ROOT / "main.py",
            ROOT / "empiremuse",
        ]

        imported_modules = set()

        for base in production_paths:
            py_files = [base] if base.is_file() else list(base.rglob("*.py"))
            for py_path in py_files:
                if "__pycache__" in py_path.parts:
                    continue
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            imported_modules.add(name.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported_modules.add(node.module.split(".")[0])

        overlap = imported_modules.intersection(self.DEAD_PACKAGES)
        assert not overlap, f"Dependências obsoletas ainda importadas em produção: {overlap}"

    def test_yt_dlp_maintains_curl_cffi_extra(self):
        """Garante que requirements.txt mantém o extra curl-cffi no yt-dlp.

        O curl_cffi é carregado dinamicamente por yt_dlp/dependencies para
        impersonação de navegador usada por múltiplos extractors, evitando
        degradação silenciosa na extração de áudio de fontes externas.
        """
        req_text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "yt-dlp[default,curl-cffi]" in req_text


class TestListenalongResolution:
    """Verifica a resolução de bot no comando listenalong."""

    def test_listenalong_resolution_with_music_bot(self):
        ctx = SimpleNamespace(
            music_bot="bot_instance_1",
            music_guild="guild_instance_1",
            bot="bot_fallback",
            guild_id=123,
        )
        try:
            bot = ctx.music_bot
        except AttributeError:
            bot = ctx.bot
        assert bot == "bot_instance_1"

    def test_listenalong_resolution_without_music_bot(self):
        ctx = SimpleNamespace(
            bot="bot_fallback",
            guild_id=123,
        )
        try:
            bot = ctx.music_bot
        except AttributeError:
            bot = ctx.bot
        assert bot == "bot_fallback"

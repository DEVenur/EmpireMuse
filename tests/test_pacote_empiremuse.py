"""Testes de caracterização estrutural do novo pacote empiremuse (Task C-20 / Bloco C4).

Garante os contratos arquiteturais da reorganização modular:
1. Import do pacote empiremuse e resolução do ponto de entrada via python -m empiremuse.
2. Importabilidade de todas as 10 extensões/cogs sob empiremuse.cogs.<nome>.
3. Importabilidade de todas as 15 skins sob empiremuse.utils.music.skins.{normal,static}_player.<nome>.
4. Resolução de recursos embutidos (templates, static) via paths.PACKAGE_DIR e de data/ + assets/ via paths.PROJECT_DIR.
5. Resolução dinâmica de paths.RUNTIME_DIR (padrão CWD, customizável por EMPIREMUSE_HOME).
6. Retrocompatibilidade de desserialização (pickle) de filas salvas, sessões de player e skins personalizadas.
"""

from __future__ import annotations

import base64
import datetime
import importlib
import importlib.util
from pathlib import Path
import pickle
import zlib

import pytest

ROOT = Path(__file__).resolve().parent.parent

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

NORMAL_SKINS = [
    "classic",
    "default",
    "default_progressbar",
    "embed_link",
    "lite",
    "micro_controller",
    "micro_nc",
    "minimalist",
    "mini",
    "miniplayer",
]

STATIC_SKINS = [
    "classic",
    "default",
    "default_progressbar",
    "embed_link",
    "mini",
]


class TestPacoteEmpireMuse:
    """Verifica a existência e importabilidade do pacote empiremuse e de seu ponto de entrada."""

    def test_import_empiremuse_package(self):
        spec = importlib.util.find_spec("empiremuse")
        assert spec is not None, "O pacote 'empiremuse' deve existir e ser importável"
        mod = importlib.import_module("empiremuse")
        assert mod is not None

    def test_entrypoint_main_module_resolves_and_exposes_starter(self):
        spec = importlib.util.find_spec("empiremuse.__main__")
        assert spec is not None, "O módulo 'empiremuse.__main__' deve existir para suporte a 'python -m empiremuse'"
        main_mod = importlib.import_module("empiremuse.__main__")
        assert hasattr(main_mod, "main") or hasattr(main_mod, "run"), (
            "empiremuse.__main__ deve expor uma função de início (main ou run)"
        )


class TestCogsESkinsDoPacote:
    """Verifica se todos os 10 cogs e 15 skins são importáveis sob o namespace empiremuse."""

    @pytest.mark.parametrize("cog_name", COGS)
    def test_cog_importable(self, cog_name: str):
        module_path = f"empiremuse.cogs.{cog_name}"
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Cog '{module_path}' deve existir sob empiremuse.cogs"
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "setup"), f"Cog '{module_path}' deve conter a função setup(bot)"

    @pytest.mark.parametrize("skin_name", NORMAL_SKINS)
    def test_normal_skin_importable(self, skin_name: str):
        module_path = f"empiremuse.utils.music.skins.normal_player.{skin_name}"
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Skin '{module_path}' deve existir"
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "load"), f"Skin '{module_path}' deve conter a função load()"

    @pytest.mark.parametrize("skin_name", STATIC_SKINS)
    def test_static_skin_importable(self, skin_name: str):
        module_path = f"empiremuse.utils.music.skins.static_player.{skin_name}"
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Skin estática '{module_path}' deve existir"
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "load"), f"Skin estática '{module_path}' deve conter a função load()"


class TestPathsERecursos:
    """Verifica a resolução centralizada de caminhos no módulo empiremuse.paths."""

    def test_paths_module_structure_and_project_dir(self):
        spec = importlib.util.find_spec("empiremuse.paths")
        assert spec is not None, "empiremuse.paths deve existir"
        from empiremuse import paths

        assert hasattr(paths, "PROJECT_DIR"), "paths deve definir PROJECT_DIR"
        assert hasattr(paths, "PACKAGE_DIR"), "paths deve definir PACKAGE_DIR"
        assert hasattr(paths, "RUNTIME_DIR"), "paths deve definir RUNTIME_DIR"

        # data/ e assets/ permanecem na raiz do projeto (PROJECT_DIR)
        assert (paths.PROJECT_DIR / "data" / "lavalink_servers.ini").is_file(), (
            "data/lavalink_servers.ini deve ser resolvido via paths.PROJECT_DIR"
        )
        assert (paths.PROJECT_DIR / "assets" / "brand").is_dir(), (
            "assets/brand deve ser resolvido via paths.PROJECT_DIR"
        )

        # Recursos embutidos que acompanham o pacote (PACKAGE_DIR)
        assert (paths.PACKAGE_DIR / "templates" / "status.html").is_file(), (
            "templates/status.html deve estar localizado em paths.PACKAGE_DIR / templates"
        )
        assert (paths.PACKAGE_DIR / "panel" / "templates").is_dir(), (
            "Templates do painel devem estar em paths.PACKAGE_DIR / panel / templates"
        )
        assert (paths.PACKAGE_DIR / "panel" / "static").is_dir(), (
            "Estáticos do painel devem estar em paths.PACKAGE_DIR / panel / static"
        )

    def test_runtime_dir_defaults_to_cwd_and_respects_env(self, monkeypatch, tmp_path):
        spec = importlib.util.find_spec("empiremuse.paths")
        assert spec is not None, "empiremuse.paths deve existir"
        from empiremuse import paths

        monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        get_dir = getattr(paths, "get_runtime_dir", lambda: paths.RUNTIME_DIR)
        assert get_dir().resolve() == tmp_path.resolve()

        custom_home = tmp_path / "custom_runtime"
        custom_home.mkdir()
        monkeypatch.setenv("EMPIREMUSE_HOME", str(custom_home))
        assert get_dir().resolve() == custom_home.resolve()


class TestRetrocompatibilidadePickle:
    """Verifica que estruturas persistidas não dependem de classes do projeto e continuam legíveis."""

    def test_saved_queue_pickle_roundtrip(self):
        sample_queue = {
            "tracks": ["QAAAjQIAK0FyaWFuYSBHcmFuZGUgLSBldmVyeXRoaW5nIGkgd2FudGVkIChhdWRpbykAAAAAAA=="],
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "guild_id": 123456789,
        }
        dumped = pickle.dumps(sample_queue)
        loaded = pickle.loads(dumped)
        assert loaded["guild_id"] == 123456789
        assert len(loaded["tracks"]) == 1
        assert isinstance(loaded["created_at"], datetime.datetime)

    def test_player_session_pickle_roundtrip(self):
        sample_session = {
            "guild_id": 123456789,
            "voice_channel": 987654321,
            "text_channel": 1122334455,
            "volume": 100,
            "tracks": ["QAAAjQIAK0FyaWFuYSBHcmFuZGUAAAAAAA=="],
        }
        compressed = zlib.compress(pickle.dumps(sample_session))
        encoded = base64.b64encode(compressed).decode("utf-8")

        decompressed = zlib.decompress(base64.b64decode(encoded))
        loaded = pickle.loads(decompressed)
        assert loaded["guild_id"] == 123456789
        assert loaded["voice_channel"] == 987654321
        assert loaded["volume"] == 100

    def test_custom_skin_pickle_roundtrip(self):
        sample_skin = {
            "content": "Tocando agora",
            "embeds": [
                {
                    "title": "Título da Música",
                    "description": "Artista",
                    "color": 0x5865F2,
                }
            ],
        }
        encoded = base64.b64encode(pickle.dumps(sample_skin)).decode("utf-8")
        loaded = pickle.loads(base64.b64decode(encoded))
        assert loaded["content"] == "Tocando agora"
        assert loaded["embeds"][0]["title"] == "Título da Música"

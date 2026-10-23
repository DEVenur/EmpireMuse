"""Testes de caracterização estrutural do novo pacote empiremuse (Task C-20 / Bloco C4).

Garante os contratos arquiteturais da reorganização modular:
1. Import do pacote empiremuse e resolução do ponto de entrada via python -m empiremuse.
2. Importabilidade de todas as 10 extensões/cogs sob empiremuse.cogs.<nome>.
3. Importabilidade de todas as 15 skins sob empiremuse.utils.music.skins.{normal,static}_player.<nome>.
4. Resolução de recursos embutidos (templates, static) via paths.PACKAGE_DIR e de data/ + assets/ via paths.PROJECT_DIR.
5. Resolução dinâmica de paths.RUNTIME_DIR (padrão CWD, customizável por EMPIREMUSE_HOME).
6. Retrocompatibilidade de leitura dos formatos legados de filas salvas, sessões de player e skins personalizadas
   (pelos leitores reais do projeto, não pelo formato em si).
"""

from __future__ import annotations

import datetime
import importlib
import importlib.util
from pathlib import Path
import pickle
from types import SimpleNamespace
import zlib

import pytest


from tests.support.formatos_reais import BOT_ID, SERVIDOR, cog_de_sessoes
from tests.persistence.test_formato_fila_salva import caminho_da_fila, ler as ler_fila, tres_faixas
from tests.persistence.test_formato_sessao import gravar as gravar_sessao, jogador_completo
from tests.persistence.test_formato_skin import (
    dados_globais,
    editor_sem_tela as _editor_sem_tela,
    skin_realista,
    texto_legado,
)
from tests.support.raiz import RAIZ

editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py

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


class TestRetrocompatibilidadeDoLegado:
    """Os leitores REAIS continuam lendo o que versões antigas gravaram, sem depender de classes do projeto."""

    @pytest.mark.asyncio
    async def test_sessao_de_player_legada_e_lida_pelo_leitor_de_sessoes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        sessao = await gravar_sessao(cog_de_sessoes(), jogador_completo())
        pasta = tmp_path / "local_database" / "player_sessions" / str(BOT_ID)
        pasta.mkdir(parents=True)
        (pasta / f"{SERVIDOR}.pkl").write_bytes(zlib.compress(pickle.dumps(sessao)))
        from empiremuse.serialization import session  # sob demanda: o módulo nasce na etapa 5

        cog = cog_de_sessoes()
        await cog.migrate_legacy_sessions()  # o pickle antigo é lido por load_legacy e vira JSON
        assert await cog.get_player_sessions_local() == [session.validate_session(sessao)]

    @pytest.mark.asyncio
    async def test_fila_salva_legada_volta_como_faixas(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        faixas = tres_faixas()
        for faixa in faixas:
            faixa.info["id"] = faixa.id
        conteudo = {
            "tracks": [dict(faixa.info) for faixa in faixas],
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "guild_id": SERVIDOR,
        }
        caminho = caminho_da_fila(tmp_path)
        caminho.parent.mkdir(parents=True)
        caminho.write_bytes(zlib.compress(pickle.dumps(conteudo)))
        lidas = await ler_fila(monkeypatch)
        assert [faixa.info["title"] for faixa in lidas] == [faixa.info["title"] for faixa in faixas]

    @pytest.mark.asyncio
    async def test_skin_personalizada_legada_e_lida_pelo_editor(self, editor_sem_tela):
        skin = skin_realista()
        menu, _, _ = editor_sem_tela(dados_globais(normais={"Minha": texto_legado(skin)}))
        await menu.load_skin(SimpleNamespace(values=["> cs: Minha"]))
        assert menu.message_data == skin

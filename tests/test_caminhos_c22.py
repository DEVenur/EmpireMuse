"""Testes da Task C-22: roteamento de caminhos por empiremuse.paths, subprocess Popen cwd, e guardas de cache."""

from __future__ import annotations

import base64
import subprocess
import zlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from empiremuse import paths
from empiremuse.panel.handlers import brand
from empiremuse.utils import branding
from empiremuse.utils.client import BotPool
from empiremuse.utils.db import LocalDatabase
from empiremuse.utils.music import lavalink_server_list, local_lavalink as ll
from tests.helpers_f3_6b import BOT_ID, MongoEmMemoria, cog_de_sessoes
from tests.test_f3_6b_formato_caches import gravar_o_cache_de_playlist, pool_vazio as pool_de_caches
from tests.test_f3_6b_formato_fila_salva import salvar as salvar_fila, tres_faixas
from tests.test_f3_6b_formato_sessao import jogador_completo
from tests.test_f3_6b_formato_skin import editor_sem_tela as _editor_sem_tela
from tests.test_f3_6b_formato_skin import BotaoDeModo, InteracaoDoEditor, dados_globais, skin_realista


editor_sem_tela = _editor_sem_tela  # a fixture do editor de skin, reaproveitada de tests/test_f3_6b_formato_skin.py


class TestCwdDoPopenLavalink:
    """(a) Teste que Popen do Lavalink recebe cwd=RUNTIME_DIR."""

    def test_popen_receives_cwd_runtime_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        popen_calls = []

        mock_proc = MagicMock()
        mock_proc.__enter__.return_value = mock_proc
        mock_proc.communicate.return_value = (b"", b"")

        monkeypatch.setattr(
            ll.subprocess,
            "Popen",
            lambda args, **kwargs: popen_calls.append((args, kwargs)) or mock_proc,
        )
        monkeypatch.setattr(ll.platform, "architecture", lambda: ("64bit", "ELF"))
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
        monkeypatch.setattr(ll, "prepare_lavalink_files", lambda *a, **k: None)

        ll.run_lavalink()

        assert len(popen_calls) >= 1
        # O último ou o do Lavalink é o que inicia o jar
        lavalink_call = [c for c in popen_calls if any("Lavalink.jar" in str(arg) for arg in c[0])][0]
        _, kwargs = lavalink_call
        assert "cwd" in kwargs, "Popen do Lavalink deve receber o argumento 'cwd'"
        assert kwargs["cwd"] == str(tmp_path.resolve())


class TestGuardasDeCache:
    """(b) Cache ilegível (de qualquer formato, inclusive o de uma versão antiga) é descartado sem travar a inicialização."""

    @pytest.mark.parametrize(
        "filename,attr_name",
        [
            ("playlist_cache.pkl", "playlist_cache"),
            ("partial_track_cache.pkl", "partial_track_cache"),
            (".lyric_cache_data", "lyric_data_cache"),
        ],
    )
    @pytest.mark.parametrize(
        "conteudo",
        [
            b"cnonexistent_module_xyz\nFakeClass\n)\x81}.",  # classe de um módulo que não existe (de uma versão antiga)
            b"INVALID_CACHE_BYTES",
            b"",
        ],
        ids=["classe-inexistente", "bytes-invalidos", "vazio"],
    )
    def test_cache_ilegivel_e_descartado_sem_travar(self, monkeypatch, tmp_path, filename, attr_name, conteudo):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db_dir = tmp_path / "local_database"
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / filename).write_bytes(conteudo)

        pool = BotPool.__new__(BotPool)
        pool.playlist_cache = {}
        pool.partial_track_cache = {}
        pool.lyric_data_cache = {}

        pool.load_cache()

        assert getattr(pool, attr_name) == {}
        assert all(
            getattr(pool, outro) == {} for outro in ("playlist_cache", "partial_track_cache", "lyric_data_cache")
        )


def conteudo_legivel(gravado: bytes | str) -> bytes:
    """O que o artefato guarda por dentro, seja qual for o envelope (``base64`` e ``zlib`` são desfeitos se houver)."""
    dados = gravado.encode() if isinstance(gravado, str) else gravado
    try:
        dados = base64.b64decode(dados, validate=True)
    except ValueError:
        pass
    try:
        dados = zlib.decompress(dados)
    except zlib.error:
        pass
    return dados


MODULOS_DO_PROJETO = (b"empiremuse", b"utils.", b"modules.")


class TestArtefatosSemModulosDoProjeto:
    """(c) O que o código REAL grava (sessão, fila salva, skin, cache de playlist) não referencia módulos do projeto.

    Formato-neutro: lê os bytes que os gravadores de verdade deixaram no disco ou no banco, desfaz o envelope e confere.
    """

    @staticmethod
    def sem_modulos_do_projeto(artefato: bytes | str, rotulo: str) -> None:
        dados = conteudo_legivel(artefato)
        assert dados, f"{rotulo}: o gravador não deixou nada"
        for modulo in MODULOS_DO_PROJETO:
            assert modulo not in dados, f"{rotulo} não pode referenciar {modulo.decode()}"

    @pytest.mark.asyncio
    async def test_sessao_do_player_no_disco_e_no_mongo(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        await cog_de_sessoes().save_info(jogador_completo())
        arquivos = list((tmp_path / "local_database" / "player_sessions").rglob("*.*"))
        assert arquivos, "a sessão não foi gravada no disco"
        for arquivo in arquivos:
            self.sem_modulos_do_projeto(arquivo.read_bytes(), f"sessão no disco ({arquivo.name})")

        mongo = MongoEmMemoria()
        await cog_de_sessoes(mongo=mongo).save_info(jogador_completo())
        (documento,) = mongo.colecao(BOT_ID, "player_sessions").values()
        self.sem_modulos_do_projeto(documento["data"], "sessão no Mongo")

    @pytest.mark.asyncio
    async def test_fila_salva(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        faixas = tres_faixas()
        await salvar_fila(faixas[1:], atual=faixas[0])
        arquivos = list((tmp_path / "local_database" / "saved_queues_json" / "users").iterdir())
        assert len(arquivos) == 1
        self.sem_modulos_do_projeto(arquivos[0].read_bytes(), "fila salva")

    @pytest.mark.asyncio
    async def test_skin_personalizada(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Minha"))
        self.sem_modulos_do_projeto(bot.salvos[0]["custom_skins"]["Minha"], "skin personalizada")

    @pytest.mark.asyncio
    async def test_cache_de_playlist_so_referencia_bibliotecas_de_terceiros(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        pool = pool_de_caches()
        pool.playlist_cache["https://exemplo.invalid/playlist/1"] = {"loadType": "EMPTY", "tracks": []}
        await gravar_o_cache_de_playlist(pool)
        self.sem_modulos_do_projeto(
            (tmp_path / "local_database" / "playlist_cache.json").read_bytes(), "cache de playlist"
        )


class TestRoteamentoDeCaminhosDeDados:
    """Verifica roteamento de data/, assets/ e local_database."""

    def test_data_e_assets_roteados_por_project_dir(self):
        assert lavalink_server_list.BUNDLED_SERVER_LIST_PATH == paths.PROJECT_DIR / "data" / "lavalink_servers.ini"
        assert branding._ASSETS_DIR == paths.PROJECT_DIR / "assets"
        assert brand.BRAND_DIR == paths.PROJECT_DIR / "assets" / "brand"

    def test_local_database_respects_runtime_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db = LocalDatabase()
        assert db.dir == str(tmp_path / "local_database")

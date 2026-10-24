"""Testes da Task C-22: roteamento de caminhos por empiremuse.paths, subprocess Popen cwd, e guardas de cache."""

from __future__ import annotations

import json
import base64
import zlib

import pytest
from cachetools import TTLCache

from empiremuse import paths
from empiremuse.panel.handlers import brand
from empiremuse.utils import branding
from empiremuse.utils.client import BotPool
from empiremuse.utils.music import lavalink_server_list
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela
from tests.persistence.test_formato_skin import BotaoDeModo, InteracaoDoEditor, dados_globais, skin_realista


editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py


class TestGuardasDeCache:
    """(b) Cache ilegível (de qualquer formato, inclusive o de uma versão antiga) é descartado sem travar a inicialização."""

    @pytest.mark.parametrize(
        "filename,attr_name",
        [
            ("playlist_cache.pkl", "playlist_cache"),
            (".lyric_cache_data", "lyric_data_cache"),
        ],
    )
    @pytest.mark.parametrize(
        "conteudo",
        [
            b"cnonexistent_module_xyz\nFakeClass\n)\x81}.",  # classe de um módulo que não existe (de uma versão antiga)
            b"",
        ],
        ids=["classe-inexistente", "vazio"],
    )
    def test_cache_ilegivel_e_descartado_sem_travar(self, monkeypatch, tmp_path, filename, attr_name, conteudo):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db_dir = tmp_path / "local_database"
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / filename).write_bytes(conteudo)

        pool = BotPool.__new__(BotPool)
        pool.playlist_cache = TTLCache(maxsize=10, ttl=1800)  # o ``load_cache`` lê o TTL do cache de playlist
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
    async def test_skin_personalizada(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Minha"))
        gravada = bot.salvos[-1]["custom_skins"]["Minha"]
        # a skin é dicionário (JSON) desde a etapa 3; o texto ``base64`` de ``pickle`` era o formato antigo
        artefato = json.dumps(gravada, ensure_ascii=False) if isinstance(gravada, dict) else gravada
        self.sem_modulos_do_projeto(artefato, "skin personalizada")


class TestRoteamentoDeCaminhosDeDados:
    """Verifica roteamento de data/, assets/ e local_database."""

    def test_data_e_assets_roteados_por_project_dir(self):
        assert lavalink_server_list.BUNDLED_SERVER_LIST_PATH == paths.PROJECT_DIR / "data" / "lavalink_servers.ini"
        assert branding._ASSETS_DIR == paths.PROJECT_DIR / "assets"
        assert brand.BRAND_DIR == paths.PROJECT_DIR / "assets" / "brand"

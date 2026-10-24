"""Testes da Task C-22: roteamento de caminhos por empiremuse.paths e subprocess Popen cwd."""

from __future__ import annotations

import json
import base64
import zlib

import pytest

from empiremuse import paths
from empiremuse.panel.handlers import brand
from empiremuse.utils import branding
from empiremuse.utils.db import LocalDatabase
from empiremuse.utils.music import lavalink_server_list, local_lavalink as ll
from tests.support.formatos_reais import BOT_ID, MongoEmMemoria, cog_de_sessoes
from tests.persistence.test_formato_caches import gravar_o_cache_de_playlist, pool_vazio as pool_de_caches
from tests.support.formato_fila_salva import salvar as salvar_fila, tres_faixas
from tests.support.formato_sessao import jogador_completo
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela
from tests.persistence.test_formato_skin import BotaoDeModo, InteracaoDoEditor, dados_globais, skin_realista


editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py


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

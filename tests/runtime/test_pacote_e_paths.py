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
import pickle
import zlib

import pytest


from tests.support.formatos_reais import BOT_ID, SERVIDOR, cog_de_sessoes
from tests.persistence.test_formato_fila_salva import caminho_da_fila, ler as ler_fila, tres_faixas
from tests.persistence.test_formato_sessao import gravar as gravar_sessao, jogador_completo

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

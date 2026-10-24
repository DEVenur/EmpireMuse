"""F3-5b, endurecimento do PR 2 — testes que fecham os sobreviventes da mutação de 2816fc6a, 513de49f e 9d96ebd4.

Cada teste mata um mutante que passava nos testes de ``test_f3_5b_endurecimento``: o contrato já valia, só não estava
fixado. Os comentários dizem o que o mutante fazia. Referência: KI-42 (docs/known-issues.md).
"""

import pytest

from tests.support.modais import adicionar_integracao, trocar_process_idle_embed
from tests.cogs.test_endurecimento_modais import PERFIL_SPOTIFY, BotEspiao


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


# ============================================================================ I-3 e I-6 — dados externos


class TestConsultasExternas:
    @pytest.mark.asyncio
    async def test_spotify_indisponivel_recusa_sem_consultar(self):
        bot = BotEspiao()
        bot.spotify = None
        inter = await adicionar_integracao(bot, url=PERFIL_SPOTIFY)
        assert "suporte ao spotify" in inter.texto and bot.salvos_usuario == [] and bot.consultas == []

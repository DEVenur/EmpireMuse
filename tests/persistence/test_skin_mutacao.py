"""F3-6b, etapa 3 — complemento do QA depois da mutação do código REAL (``skins.py``, ``skin_store.py``, editor e leitores).

Sobreviventes que não eram equivalentes: o teto de 100 KiB (EXATO: 102 400 bytes passam e 102 401 não) e a falha de gravação do
documento durante a migração (a leitura segue com o que está na memória, sem derrubar o comando e sem vazar o erro).
"""

import copy

import pytest

from tests.support.formatos_reais import SERVIDOR
from tests.support.skins import carregar_helper
from tests.persistence.test_skin_leitura import documento
from tests.persistence.test_formato_skin import BotDeSkins, skin_realista, texto_legado


class TestFalhaDeGravacaoNaMigracao:
    @pytest.mark.asyncio
    async def test_a_proxima_leitura_com_o_mesmo_documento_nao_tenta_de_novo_na_memoria(self):
        dados = documento(normais={"A": texto_legado(skin_realista())})
        bot = BotDeSkins(dados)
        chamadas = []

        async def quebrar(*args, **kwargs):
            chamadas.append(1)
            raise ConnectionError("banco fora")

        bot.update_global_data = quebrar
        helper = carregar_helper()
        await helper(bot, SERVIDOR, dados)
        await helper(bot, SERVIDOR, dados)
        assert chamadas == [1] and copy.deepcopy(dados["custom_skins"]["A"]) == skin_realista()

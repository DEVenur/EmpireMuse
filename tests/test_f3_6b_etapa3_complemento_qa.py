"""F3-6b, etapa 3 — complemento do QA depois da mutação do código REAL (``skins.py``, ``skin_store.py``, editor e leitores).

Sobreviventes que não eram equivalentes: o teto de 100 KiB (EXATO: 102 400 bytes passam e 102 401 não) e a falha de gravação do
documento durante a migração (a leitura segue com o que está na memória, sem derrubar o comando e sem vazar o erro).
"""

import copy
import logging

import pytest

from empiremuse.serialization.skins import validate_skin
from tests.helpers_f3_6b import SERVIDOR
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import TOO_BIG, falha
from tests.helpers_f3_6b_skins import LIMITES, carregar_helper, tamanho_em_bytes
from tests.test_f3_6b_etapa3_leitura import documento
from tests.test_f3_6b_formato_skin import BotDeSkins, skin_realista, texto_legado

CAMPO = {"name": "n" * 256, "value": "v" * 1024}


def skin_de_tamanho_exato(alvo: int) -> dict:
    """Uma skin válida em cada campo cujo JSON compacto tem EXATAMENTE ``alvo`` bytes (embeds e campos cheios, um campo sob medida)."""
    embeds = []
    while len(embeds) < LIMITES.embeds:
        cheio = {"fields": [dict(CAMPO) for _ in range(LIMITES.fields)]}
        if tamanho_em_bytes({"embeds": embeds + [cheio]}) > alvo:
            break
        embeds.append(cheio)
    campos = []
    while len(campos) < LIMITES.fields:
        tentativa = {"embeds": embeds + [{"fields": campos + [dict(CAMPO)]}]}
        if tamanho_em_bytes(tentativa) > alvo:
            break
        campos.append(dict(CAMPO))
    base = tamanho_em_bytes({"embeds": embeds + [{"fields": campos + [{"name": "n", "value": ""}]}]})
    falta = alvo - base
    assert 0 <= falta <= 1024, f"o construtor do teste não fechou o tamanho ({falta})"
    skin = {"embeds": embeds + [{"fields": campos + [{"name": "n", "value": "v" * falta}]}]}
    assert tamanho_em_bytes(skin) == alvo
    return skin


class TestTetoExatoDe100KiB:
    def test_102400_bytes_passam(self):
        skin = skin_de_tamanho_exato(LIMITES.skin_bytes)
        assert validate_skin(skin) == skin

    def test_102401_bytes_sao_recusados(self):
        assert falha(validate_skin, skin_de_tamanho_exato(LIMITES.skin_bytes + 1)).code == TOO_BIG


class TestFalhaDeGravacaoNaMigracao:
    @pytest.mark.asyncio
    async def test_a_leitura_segue_e_o_erro_nao_vaza(self, caplog):
        dados = documento(normais={"A": texto_legado(skin_realista(content="a"))})
        bot = BotDeSkins(dados)

        async def quebrar(*args, **kwargs):
            raise ConnectionError(f"banco fora {SEGREDO}")

        bot.update_global_data = quebrar
        with caplog.at_level(logging.DEBUG):
            await carregar_helper()(bot, SERVIDOR, dados)  # nenhuma exceção
        assert dados["custom_skins"]["A"] == skin_realista(content="a")
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

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

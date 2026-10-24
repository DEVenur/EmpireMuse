"""A skin já gravada como dicionário também é validada na leitura por ``load_custom_skins`` (defesa contra dicionário plantado
no banco): o inválido não chega ao player nem ao ``skin_converter`` (a skin padrão assume), o documento fica intacto (nem
reescrito) e sai um WARNING só com ``guild_id`` e ``code``. No ``load_skin`` ele não abre no editor.
"""

import copy
import logging

import pytest

from tests.support.serializacao_nucleo import SEGREDO
from tests.support.serializacao_nucleo import aninhado
from tests.support.skins import carregar_helper
from tests.persistence.test_skin_leitura import documento, rodar
from tests.persistence.test_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    skin_realista,
)
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela

editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py


@pytest.fixture
def helper():
    return carregar_helper()


# ============================================================================ o dicionário gravado é validado na leitura

INVALIDOS = [
    ("descricao-longa", {"embeds": [{"description": SEGREDO + "d" * 5000}]}, "length"),
    ("embeds-texto", {"embeds": SEGREDO}, "type"),
    ("fila-fora-da-faixa", {"queue_max_entries": 40, "content": SEGREDO}, "range"),
    ("controle", {"content": SEGREDO + "\x00"}, "control"),
    ("campo-sem-valor", {"embeds": [{"fields": [{"name": SEGREDO}]}]}, "missing"),
    ("lista", [SEGREDO], "type"),
    ("numero", 5, "type"),
]


def com_invalido(invalido) -> dict:
    return documento(
        normais={"Boa": skin_realista(content="boa"), "Ruim": copy.deepcopy(invalido)},
        estaticas={"FixaBoa": skin_realista(content="fixa"), "FixaRuim": copy.deepcopy(invalido)},
    )


@pytest.mark.parametrize(("invalido", "codigo"), [i[1:] for i in INVALIDOS], ids=[i[0] for i in INVALIDOS])
class TestDicionarioInvalidoNaLeitura:
    @pytest.mark.asyncio
    async def test_o_editor_ao_salvar_nao_entrega_o_invalido_ao_player(self, editor_sem_tela, caplog, invalido, codigo):
        jogador = Jogador()
        dados = com_invalido(invalido)
        menu, bot, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        with caplog.at_level(logging.DEBUG):
            await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert set(jogador.custom_skin_data) == {"Boa", "Nova"} and set(jogador.custom_skin_static_data) == {"FixaBoa"}
        assert (
            bot.banco["custom_skins"]["Ruim"] == invalido and bot.banco["custom_skins_static"]["FixaRuim"] == invalido
        )


class TestDicionarioHostilNaLeitura:
    @pytest.mark.asyncio
    async def test_chave_desconhecida_enorme_nao_invalida_a_skin(self, helper, caplog):
        dados = documento(normais={"Boa": {**skin_realista(), "lixo": aninhado(200_000)}})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_vazias_nao_sao_validadas_nem_avisam(self, helper, caplog):
        dados = documento(normais={"A": {}, "B": None, "C": ""})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]

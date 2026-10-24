"""F3-6b, etapa 3 (RED, complemento) — duas decisões do MAESTRO sobre ``load_custom_skins``.

1. ``queue_max_entries`` de 26 a 99 num texto LEGADO é ajustado para 25 ANTES de validar (o ``skin_converter`` de hoje aceita
   até 2 dígitos); o esquema continua 0..25 (o editor recusa 26 ao salvar) e o ajuste vale só na migração do texto: um valor
   fora da faixa que não seja inteiro exato de 26 a 99 continua recusado, e um dicionário já gravado não é ajustado.
2. O dicionário JÁ gravado também é validado na leitura pelo mesmo ``validate_skin`` (defesa contra dicionário plantado no
   banco): o inválido não chega ao player nem ao ``skin_converter`` (a skin padrão assume), o documento fica intacto (nem
   reescrito) e sai um WARNING só com ``guild_id`` e ``code``. No ``load_skin`` ele não abre no editor, como o texto recusado.
"""

import copy
import logging

import pytest

from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import aninhado
from tests.support.skins import carregar_helper
from tests.persistence.test_skin_leitura import documento, rodar
from tests.persistence.test_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    chamar_create_player,
    skin_realista,
    texto_legado,
)
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela

editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py


@pytest.fixture
def helper():
    return carregar_helper()


# ============================================================================ 1) 26..99 vira 25 na migração do texto


class TestFilaAcimaDoTetoNaMigracao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [0, 25])
    async def test_valor_dentro_da_faixa_nao_muda(self, helper, valor):
        dados = documento(normais={"A": texto_legado({"queue_max_entries": valor})})
        await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == {"queue_max_entries": valor}

    @pytest.mark.asyncio
    async def test_o_player_do_create_player_recebe_a_skin_ajustada(self):
        dados = documento(normais={"A": texto_legado({"queue_max_entries": 40, "content": "c"})})
        recebidos = await chamar_create_player(dados, [])
        assert recebidos["custom_skin_data"] == {"A": {"queue_max_entries": 25, "content": "c"}}


# ============================================================================ 2) o dicionário gravado também é validado

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
    async def test_a_migracao_de_um_texto_grava_o_invalido_intacto(self, helper, invalido, codigo):
        dados = com_invalido(invalido)
        dados["custom_skins"]["Velha"] = texto_legado(skin_realista(content="velha"))
        bot = await rodar(helper, dados)
        assert len(bot.escritas) == 1 and bot.banco["custom_skins"]["Velha"] == skin_realista(content="velha")
        assert (
            bot.banco["custom_skins"]["Ruim"] == invalido and bot.banco["custom_skins_static"]["FixaRuim"] == invalido
        )

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

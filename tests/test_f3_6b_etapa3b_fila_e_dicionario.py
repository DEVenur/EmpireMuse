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
from types import SimpleNamespace

import pytest

from tests.helpers_f3_6b import SERVIDOR
from tests.helpers_f3_6b_corte import log_sem_o_conteudo, registrou
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import aninhado
from tests.helpers_f3_6b_skins import carregar_helper
from tests.test_f3_6b_etapa3_leitura import documento, rodar
from tests.test_f3_6b_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    chamar_change_skin,
    chamar_create_player,
    skin_realista,
    texto_legado,
)
from tests.test_f3_6b_formato_skin import editor_sem_tela as _editor_sem_tela

editor_sem_tela = _editor_sem_tela  # a fixture do editor de skin, reaproveitada de tests/test_f3_6b_formato_skin.py


@pytest.fixture
def helper():
    return carregar_helper()


# ============================================================================ 1) 26..99 vira 25 na migração do texto


class TestFilaAcimaDoTetoNaMigracao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [26, 30, 50, 99])
    @pytest.mark.parametrize("modo", ["custom_skins", "custom_skins_static"])
    async def test_de_26_a_99_vira_25_e_a_skin_migra(self, helper, valor, modo):
        skin = {"queue_max_entries": valor, "content": "c", "embeds": [{"description": "d"}]}
        dados = documento(**{("normais" if modo == "custom_skins" else "estaticas"): {"A": texto_legado(skin)}})
        bot = await rodar(helper, dados)
        assert dados[modo]["A"] == {**skin, "queue_max_entries": 25}
        assert len(bot.escritas) == 1 and bot.banco[modo]["A"]["queue_max_entries"] == 25

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [0, 7, 25])
    async def test_valor_dentro_da_faixa_nao_muda(self, helper, valor):
        dados = documento(normais={"A": texto_legado({"queue_max_entries": valor})})
        await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == {"queue_max_entries": valor}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "valor", [100, 1000, -1, True, "30", 30.0], ids=["100", "1000", "negativo", "bool", "texto", "float"]
    )
    async def test_o_ajuste_vale_so_de_26_a_99_inteiro(self, helper, caplog, valor):
        texto = texto_legado({"queue_max_entries": valor, "content": "c"})
        dados = documento(normais={"A": texto, "Boa": texto_legado(skin_realista())})
        with caplog.at_level(logging.DEBUG):
            await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == texto and dados["custom_skins"]["Boa"] == skin_realista()
        assert registrou(caplog, SERVIDOR, ("range", "type"))

    @pytest.mark.asyncio
    async def test_o_dicionario_ja_gravado_com_fila_acima_do_teto_nao_e_ajustado(self, helper, caplog):
        """O ajuste é da MIGRAÇÃO do texto; o dicionário gravado passa pela regra 2 (inválido fica intacto e é ignorado)."""
        gravado = {"queue_max_entries": 40, "content": "c"}
        dados = documento(normais={"A": copy.deepcopy(gravado)})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == gravado and bot.escritas == []
        assert registrou(caplog, SERVIDOR, "range")

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
    async def test_o_helper_nao_mexe_no_documento_nem_grava(self, helper, caplog, capsys, invalido, codigo):
        dados = com_invalido(invalido)
        antes = copy.deepcopy(dados)
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert dados == antes and bot.escritas == []
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

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
    async def test_create_player_nao_entrega_o_invalido(self, caplog, capsys, invalido, codigo):
        with caplog.at_level(logging.DEBUG):
            recebidos = await chamar_create_player(com_invalido(invalido), [])
        assert set(recebidos["custom_skin_data"]) == {"Boa"} and set(recebidos["custom_skin_static_data"]) == {
            "FixaBoa"
        }
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_change_skin_nao_entrega_o_invalido(self, monkeypatch, caplog, capsys, invalido, codigo):
        with caplog.at_level(logging.DEBUG):
            jogador = await chamar_change_skin(monkeypatch, com_invalido(invalido), nova_skin="> custom_skin: Boa")
        assert set(jogador.custom_skin_data) == {"Boa"} and set(jogador.custom_skin_static_data) == {"FixaBoa"}
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

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

    @pytest.mark.asyncio
    async def test_load_skin_nao_abre_o_invalido_no_editor(self, editor_sem_tela, invalido, codigo):
        menu, _, _ = editor_sem_tela(com_invalido(invalido))
        menu.mode = "select"
        antes = copy.deepcopy(menu.message_data)
        enviados = []

        async def enviar(conteudo=None, **kwargs):
            enviados.append(str(conteudo))

        interacao = SimpleNamespace(values=["> cs: Ruim"], send=enviar)
        await menu.load_skin(interacao)
        assert menu.mode == "select" and menu.message_data == antes and any(enviados)


class TestDicionarioHostilNaLeitura:
    @pytest.mark.asyncio
    async def test_aninhamento_enorme_num_campo_conhecido_e_recusado_sem_recursao(self, helper, caplog):
        dados = documento(normais={"Boa": skin_realista(), "Fundo": {"embeds": aninhado(200_000)}})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and registrou(caplog, SERVIDOR, "type")

    @pytest.mark.asyncio
    async def test_chave_desconhecida_enorme_nao_invalida_a_skin(self, helper, caplog):
        dados = documento(normais={"Boa": {**skin_realista(), "lixo": aninhado(200_000)}})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_dicionario_valido_nao_gera_aviso_nem_gravacao(self, helper, caplog):
        dados = documento(normais={"Boa": skin_realista()}, estaticas={"Fixa": skin_realista(content="f")})
        antes = copy.deepcopy(dados)
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert dados == antes and bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_vazias_nao_sao_validadas_nem_avisam(self, helper, caplog):
        dados = documento(normais={"A": {}, "B": None, "C": ""})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ============================================================================ o aviso do change_skin com um modo só recusado


class TestChangeSkinAvisaComUmModoSo:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", ["custom_skins", "custom_skins_static"])
    async def test_avisa_o_dono_quando_so_um_dos_modos_tem_skin_recusada(self, monkeypatch, modo):
        from tests.test_f3_6b_etapa2b_pontos import dados_com_skin_ruim, texto_hostil
        from tests.helpers_f3_6b_corte import criar_armadilhas

        armadilhas = criar_armadilhas(__import__("pathlib").Path("/tmp"), monkeypatch)
        texto, _ = texto_hostil(armadilhas, "protocolo-3")
        dados = dados_com_skin_ruim(texto)
        outro = "custom_skins_static" if modo == "custom_skins" else "custom_skins"
        dados[outro] = {k: v for k, v in dados[outro].items() if "Ruim" not in k}
        jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: Boa")
        assert "incompatível" in " ".join(jogador.mensagens)

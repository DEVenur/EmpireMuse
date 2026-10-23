"""F3-6b, etapa 3 (RED) — a leitura da skin: o helper único ``load_custom_skins`` e os 4 pontos que o usam.

Migração no primeiro acesso (plano 3.2): o texto legado (``base64`` de ``pickle``) é lido por ``load_legacy(texto, "skin")``,
validado por ``validate_skin`` e trocado por dicionário NO documento, que é gravado inteiro UMA vez. O que for recusado (pickle
hostil ou skin fora do esquema) continua como texto, com um aviso só com ``guild_id`` e ``code``. Depois da migração nada
mais é lido nem gravado (idempotente). As decisões estão em ``tests/helpers_f3_6b_skins.py``.

Os 4 pontos: ``Music.create_player``, ``MusicSettings.change_skin``, ``SkinEditorMenu.load_skin`` e o laço do player em
``SkinEditorMenu.modal_handler`` (depois de salvar).
"""

import copy
import logging
from types import SimpleNamespace

import pytest

from empiremuse.utils.db import DBModel
from tests.support.formatos_reais import SERVIDOR
from tests.support.chave_de_corte import criar_armadilhas, espionar_load_legacy, log_sem_o_conteudo, registrou
from tests.support.leitor_legado import SEGREDO
from tests.support.skins import carregar_helper, tipos_do_documento
from tests.persistence.test_chave_de_corte_load_legacy import HOSTIS_DE_SKIN, texto_hostil
from tests.persistence.test_formato_skin import (
    BotaoDeModo,
    BotDeSkins,
    InteracaoDoEditor,
    Jogador,
    chamar_change_skin,
    chamar_create_player,
    dados_globais,
    skin_realista,
    texto_legado,
)
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela

editor_sem_tela = _editor_sem_tela  # a fixture do editor de skin, reaproveitada de tests/test_f3_6b_formato_skin.py


def documento(normais=None, estaticas=None, **extra) -> dict:
    """O documento global do servidor com tudo que os 4 pontos leem."""
    base = {
        **dados_globais(normais, estaticas),
        "prefix": "!",
        "global_skin": False,
        "listen_along_invites": {},
        "voice_channel_status": "",
        "player_skin": "",
        "player_skin_static": "",
    }
    return base | extra


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


@pytest.fixture
def armadilhas(tmp_path, monkeypatch):
    return criar_armadilhas(tmp_path, monkeypatch)


@pytest.fixture
def helper():
    return carregar_helper()


async def rodar(helper, dados, jogadores=()):
    bot = BotDeSkins(dados, jogadores)
    await helper(bot, SERVIDOR, dados)
    return bot


# ============================================================================ o helper


class TestHelper:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_troca_o_texto_legado_por_dicionario_no_documento(self, helper, protocolo):
        normal, fixa = skin_realista(content="normal"), skin_realista(content="fixa")
        dados = documento(
            normais={"N": texto_legado(normal, protocolo)}, estaticas={"F": texto_legado(fixa, protocolo)}
        )
        bot = await rodar(helper, dados)
        assert dados["custom_skins"] == {"N": normal} and dados["custom_skins_static"] == {"F": fixa}
        assert bot.banco["custom_skins"] == {"N": normal} and bot.banco["custom_skins_static"] == {"F": fixa}

    @pytest.mark.asyncio
    async def test_grava_o_documento_inteiro_uma_so_vez(self, helper):
        dados = documento(
            normais={"A": texto_legado(skin_realista()), "B": texto_legado(skin_realista(content="b"))},
            estaticas={"F": texto_legado(skin_realista(content="f"))},
            prefix="?",
            outro={"mantido": [1, 2, 3]},
        )
        bot = await rodar(helper, dados)
        assert bot.escritas == [(SERVIDOR, DBModel.guilds)]
        assert len(bot.salvos) == 1 and bot.banco["prefix"] == "?" and bot.banco["outro"] == {"mantido": [1, 2, 3]}
        assert bot.banco == dados

    @pytest.mark.asyncio
    async def test_nao_mexe_no_resto_do_documento(self, helper):
        dados = documento(normais={"A": texto_legado(skin_realista())}, outro={"lista": [1, {"a": 2}]})
        antes = copy.deepcopy({k: v for k, v in dados.items() if k not in {"custom_skins", "custom_skins_static"}})
        await rodar(helper, dados)
        assert {k: v for k, v in dados.items() if k not in {"custom_skins", "custom_skins_static"}} == antes

    @pytest.mark.asyncio
    async def test_a_segunda_chamada_nao_le_nem_grava(self, helper, monkeypatch):
        dados = documento(normais={"A": texto_legado(skin_realista())}, estaticas={"F": texto_legado(skin_realista())})
        await rodar(helper, dados)
        chamadas = espionar_load_legacy(monkeypatch)
        bot = await rodar(helper, dados)
        assert chamadas == [] and bot.escritas == []

    @pytest.mark.asyncio
    async def test_documento_ja_em_dicionario_nao_le_nem_grava(self, helper, monkeypatch):
        dados = documento(
            normais={"A": skin_realista(), "Vazia": {}, "Nenhuma": None}, estaticas={"F": skin_realista(content="f")}
        )
        antes = copy.deepcopy(dados)
        chamadas = espionar_load_legacy(monkeypatch)
        bot = await rodar(helper, dados)
        assert chamadas == [] and bot.escritas == [] and dados == antes

    @pytest.mark.asyncio
    async def test_texto_vazio_vale_como_sem_skin_e_nao_e_mexido(self, helper, caplog):
        dados = documento(normais={"Vazia": ""}, estaticas={"FixaVazia": ""})
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert dados["custom_skins"] == {"Vazia": ""} and dados["custom_skins_static"] == {"FixaVazia": ""}
        assert bot.escritas == [] and not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_dois_modos_e_varias_skins_saem_numa_gravacao_so(self, helper):
        dados = documento(
            normais={f"n{i}": texto_legado(skin_realista(content=f"n{i}")) for i in range(5)},
            estaticas={f"f{i}": texto_legado(skin_realista(content=f"f{i}")) for i in range(5)},
        )
        bot = await rodar(helper, dados)
        assert len(bot.escritas) == 1 and set(tipos_do_documento(bot.banco)["custom_skins"].values()) == {"dict"}
        assert set(tipos_do_documento(bot.banco)["custom_skins_static"].values()) == {"dict"}

    @pytest.mark.asyncio
    async def test_nome_antigo_estranho_continua_com_o_mesmo_nome(self, helper):
        """Os nomes só são conferidos ao SALVAR; a migração não renomeia nem recusa pelo nome."""
        nome = "v1.2 $teste"
        dados = documento(normais={nome: texto_legado(skin_realista())})
        await rodar(helper, dados)
        assert dados["custom_skins"] == {nome: skin_realista()}

    @pytest.mark.asyncio
    async def test_chave_desconhecida_sai_na_migracao_e_o_v_nunca_entra(self, helper):
        dados = documento(
            normais={"A": texto_legado({"embeds": [{"description": "d", "video": {"url": "u"}}], "foo": 1})}
        )
        await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == {"embeds": [{"description": "d"}]}

    @pytest.mark.asyncio
    async def test_a_skin_migrada_nao_ganha_chave_nova(self, helper):
        dados = documento(normais={"A": texto_legado({"embeds": [{"description": "d"}]})})
        await rodar(helper, dados)
        assert dados["custom_skins"]["A"] == {"embeds": [{"description": "d"}]}


class TestRecusadasFicamComoTexto:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", HOSTIS_DE_SKIN)
    async def test_pickle_hostil_fica_como_texto_e_as_boas_migram(self, helper, armadilhas, caplog, capsys, nome):
        texto, codigo = texto_hostil(armadilhas, nome)
        bom = skin_realista(content="boa")
        dados = documento(
            normais={"Boa": texto_legado(bom), "Ruim": texto},
            estaticas={"FixaBoa": texto_legado(bom), "FixaRuim": texto},
        )
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert dados["custom_skins"] == {"Boa": bom, "Ruim": texto}
        assert dados["custom_skins_static"] == {"FixaBoa": bom, "FixaRuim": texto}
        assert len(bot.escritas) == 1 and bot.banco == dados
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_so_recusadas_nao_grava_nada(self, helper, armadilhas):
        texto, _ = texto_hostil(armadilhas, "execucao")
        dados = documento(normais={"Ruim": texto}, estaticas={"FixaRuim": texto})
        bot = await rodar(helper, dados)
        assert bot.escritas == [] and dados["custom_skins"] == {"Ruim": texto}
        assert armadilhas.intacto()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("skin", "codigo"),
        [
            ({"embeds": [{"description": SEGREDO + "d" * 5000}]}, "length"),
            ({"embeds": SEGREDO}, "type"),
            ({"queue_max_entries": 100, "content": SEGREDO}, "range"),
            ({"controller_enabled": "sim", "content": SEGREDO}, "type"),
            ({"embeds": [{"fields": [{"value": SEGREDO}]}]}, "missing"),
            ({"embeds": [{"title": SEGREDO + "\x00"}]}, "control"),
        ],
        ids=[
            "descricao-longa",
            "embeds-texto",
            "fila-fora-da-faixa",
            "controle-texto",
            "campo-sem-nome",
            "titulo-com-nul",
        ],
    )
    async def test_pickle_valido_fora_do_esquema_fica_como_texto(self, helper, caplog, capsys, skin, codigo):
        """O pickle é bem-comportado, mas a skin não passa no esquema: continua legível no documento, e só o tipo da falha sai no log."""
        texto = texto_legado(skin)
        dados = documento(normais={"Fora": texto, "Boa": texto_legado(skin_realista())})
        with caplog.at_level(logging.DEBUG):
            await rodar(helper, dados)
        assert dados["custom_skins"]["Fora"] == texto and dados["custom_skins"]["Boa"] == skin_realista()
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)


# ============================================================================ os 4 pontos


class Acesso(SimpleNamespace):
    """O que um ponto de leitura deixou: ``escritas`` (``(id_, db_name)``) e ``banco`` (o documento persistido)."""


async def por_create_player(dados, monkeypatch, editor):
    escritas = []
    await chamar_create_player(dados, escritas)
    return Acesso(escritas=[(i, d) for i, _, d in escritas], banco=escritas[-1][1] if escritas else None, doc=dados)


async def por_change_skin(dados, monkeypatch, editor):
    jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: Minha")
    return Acesso(escritas=jogador.bot.escritas, banco=jogador.bot.banco, doc=jogador.bot.global_data)


async def por_load_skin(dados, monkeypatch, editor):
    menu, bot, _ = editor(dados)
    await menu.load_skin(SimpleNamespace(values=["> cs: Minha"]))
    return Acesso(escritas=bot.escritas, banco=bot.banco, doc=bot.global_data)


async def por_editor_salvando(dados, monkeypatch, editor):
    menu, bot, _ = editor(dados, [Jogador()])
    menu.message_data = skin_realista(content="outra")
    BotaoDeModo.modo = "custom_skins"
    await menu.modal_handler(InteracaoDoEditor(skin_name="Outra"))
    return Acesso(escritas=bot.escritas, banco=bot.banco, doc=bot.global_data)


# (função, gravações esperadas quando o documento JÁ está em dicionário): o editor grava a skin que acabou de salvar
PONTOS = {
    "create_player": (por_create_player, 0),
    "change_skin": (por_change_skin, 0),
    "load_skin": (por_load_skin, 0),
    "modal_handler": (por_editor_salvando, 1),
}
PONTOS_SO_DE_LEITURA = ["create_player", "change_skin", "load_skin"]


class TestPontosMigramNoPrimeiroAcesso:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("ponto", sorted(PONTOS))
    async def test_o_texto_legado_vira_dicionario_no_documento_gravado(self, ponto, monkeypatch, editor_sem_tela):
        funcao, _ = PONTOS[ponto]
        normal, fixa = skin_realista(content="normal"), skin_realista(content="fixa")
        dados = documento(normais={"Minha": texto_legado(normal)}, estaticas={"Fixa": texto_legado(fixa)})
        acesso = await funcao(dados, monkeypatch, editor_sem_tela)
        assert acesso.banco["custom_skins"]["Minha"] == normal and acesso.banco["custom_skins_static"]["Fixa"] == fixa
        assert {t for modo in tipos_do_documento(acesso.banco).values() for t in modo.values()} == {"dict"}
        assert set(acesso.escritas) == {(SERVIDOR, DBModel.guilds)} and 1 <= len(acesso.escritas) <= 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ponto", PONTOS_SO_DE_LEITURA)
    async def test_ponto_de_leitura_grava_uma_vez_so(self, ponto, monkeypatch, editor_sem_tela):
        funcao, _ = PONTOS[ponto]
        dados = documento(normais={"Minha": texto_legado(skin_realista())})
        acesso = await funcao(dados, monkeypatch, editor_sem_tela)
        assert len(acesso.escritas) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ponto", sorted(PONTOS))
    async def test_documento_em_dicionario_nao_le_texto_e_so_o_editor_grava(self, ponto, monkeypatch, editor_sem_tela):
        funcao, gravacoes = PONTOS[ponto]
        dados = documento(normais={"Minha": skin_realista()}, estaticas={"Fixa": skin_realista(content="f")})
        chamadas = espionar_load_legacy(monkeypatch)
        acesso = await funcao(dados, monkeypatch, editor_sem_tela)
        assert chamadas == [] and len(acesso.escritas) == gravacoes

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ponto", PONTOS_SO_DE_LEITURA)
    async def test_o_segundo_acesso_nao_le_nem_grava(self, ponto, monkeypatch, editor_sem_tela):
        funcao, _ = PONTOS[ponto]
        dados = documento(normais={"Minha": texto_legado(skin_realista())})
        primeiro = await funcao(dados, monkeypatch, editor_sem_tela)
        chamadas = espionar_load_legacy(monkeypatch)
        segundo = await funcao(primeiro.doc, monkeypatch, editor_sem_tela)
        assert chamadas == [] and segundo.escritas == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ponto", sorted(PONTOS))
    async def test_a_skin_recusada_continua_texto_no_que_foi_gravado(
        self, ponto, monkeypatch, editor_sem_tela, armadilhas, caplog
    ):
        funcao, _ = PONTOS[ponto]
        texto, codigo = texto_hostil(armadilhas, "execucao")
        dados = documento(normais={"Minha": texto_legado(skin_realista()), "Ruim": texto})
        with caplog.at_level(logging.DEBUG):
            acesso = await funcao(dados, monkeypatch, editor_sem_tela)
        assert (
            acesso.banco["custom_skins"]["Ruim"] == texto and acesso.banco["custom_skins"]["Minha"] == skin_realista()
        )
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo)

    @pytest.mark.asyncio
    async def test_o_player_do_create_player_recebe_so_dicionarios_apos_a_migracao(self):
        dados = documento(normais={"N": texto_legado(skin_realista(content="n"))}, estaticas={"F": ""})
        recebidos = await chamar_create_player(dados, [])
        assert recebidos["custom_skin_data"] == {"N": skin_realista(content="n")}
        assert recebidos["custom_skin_static_data"] == {}  # skin vazia vale como sem skin: o player nem a recebe

    @pytest.mark.asyncio
    async def test_o_editor_ao_salvar_converte_as_legadas_uma_vez_cada(self, editor_sem_tela, monkeypatch):
        dados = documento(
            normais={"A": texto_legado(skin_realista(), 4), "B": texto_legado(skin_realista(), 5)},
            estaticas={"F": texto_legado(skin_realista())},
        )
        menu, _, _ = editor_sem_tela(dados, [Jogador()])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        chamadas = espionar_load_legacy(monkeypatch)
        await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert chamadas == [("skin", "str")] * 3  # A, B e F; a recém-salva já nasce dicionário

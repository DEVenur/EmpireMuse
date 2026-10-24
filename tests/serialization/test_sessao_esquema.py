"""F3-6b, etapa 5 (RED, commit 1 do plano do Backend) — o esquema da sessão: ``empiremuse/serialization/session.py``.

Cobre ``encode_session``, ``decode_session`` e ``validate_session`` (sem tocar no produto): ida e volta com a sessão REAL do
``save_info``, tipos e tetos de cada campo, ``voice_state``/``extra_info`` fora, ``_id`` do conteúdo == o esperado (condição 2 do
5.1), ``time`` (R2: nem imortal nem do futuro) e números/datas extremos, o esquema da skin da sessão (R5) e o vazamento.
As faixas (URLs, R1) estão em ``tests/serialization/test_sessao_faixas.py`` e a redução por tamanho (R6) em ``..._tamanho.py``.
Decisões em ``tests/support/sessoes.py``.
"""

import copy
import json
from datetime import datetime, timedelta

import disnake
import pytest

from tests.support.formatos_reais import DJ_A, DJ_B, INSTANTE, SERVIDOR
from tests.support.serializacao_nucleo import (
    LENGTH,
    MISSING,
    NOT_FINITE,
    NUMBER,
    RANGE,
    SEGREDO,
    TYPE,
    VERSION,
    falha,
    schema,
    vazamentos,
)
from tests.support.sessoes import IDS_OPCIONAIS, LIMITES, bruto, codificar, decodificar, session, sessao_minima

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def uma_de(erro, *codigos) -> bool:
    return erro.code in codigos


# ============================================================================ ida e volta


class TestIdaEVolta:
    def test_os_tipos_que_o_resume_player_consome(self):
        lida = session.decode_session(
            codificar(dj={DJ_B, DJ_A}, command_log_list=[{"text": "t", "emoji": "x", "timestamp": 1.5}])
        )
        assert type(lida["time"]) is datetime and lida["time"] == INSTANTE and lida["time"].utcoffset() == timedelta(0)
        assert type(lida["dj"]) is list and lida["dj"] == sorted([DJ_A, DJ_B])
        assert type(lida["command_log_list"]) is list and lida["command_log_list"][0]["timestamp"] == 1.5
        assert "v" not in lida

    def test_encode_nao_altera_a_entrada(self):
        dados = sessao_minima(dj={DJ_A}, custom_skin_data={"Minha": {"content": "c"}})
        antes = copy.deepcopy(dados)
        session.encode_session(dados)
        assert dados == antes and type(dados["dj"]) is set

    @pytest.mark.smoke
    def test_validate_session_devolve_copia_limpa_no_formato_do_consumidor(self):
        dados = sessao_minima(dj={DJ_A}, voice_state={"x": 1}, extra_info={"a": (1, 2)}, lixo=1)
        limpa = session.validate_session(dados)
        assert limpa is not dados and "voice_state" not in limpa and "extra_info" not in limpa and "lixo" not in limpa
        assert limpa["time"] == INSTANTE and limpa["_id"] == SERVIDOR


# ============================================================================ voice_state, extra_info e o que o esquema não conhece


class TestCamposQueSaem:
    def test_a_sessao_nao_precisa_dos_dois_campos(self):
        assert session.decode_session(codificar())["_id"] == SERVIDOR


# ============================================================================ tipos e tetos de cada campo

RECUSAS = [
    ("_id-bool", "_id", True, "_id", TYPE),
    ("_id-texto", "_id", str(SERVIDOR), "_id", TYPE),
    ("_id-negativo", "_id", -1, "_id", RANGE),
    ("_id-acima-do-snowflake", "_id", 2**63, "_id", RANGE),
    ("_id-float", "_id", 1.5, "_id", TYPE),
    ("voice_channel-none", "voice_channel", None, "voice_channel", TYPE),
    ("voice_channel-texto", "voice_channel", "1", "voice_channel", TYPE),
    ("version-bool", "version", True, "version", TYPE),
    ("version-texto", "version", "1", "version", TYPE),
    ("version-negativa", "version", -1, "version", RANGE),
    ("volume-acima", "volume", 1001, "volume", RANGE),
    ("volume-negativo", "volume", -1, "volume", RANGE),
    ("volume-bool", "volume", True, "volume", TYPE),
    ("volume-texto", "volume", "80", "volume", TYPE),
    ("uptime-negativo", "uptime", -1, "uptime", RANGE),
    ("uptime-texto", "uptime", "x", "uptime", TYPE),
    ("uptime-bool", "uptime", True, "uptime", TYPE),
    ("position-negativa", "position", -1.0, "position", RANGE),
    ("position-texto", "position", "0", "position", TYPE),
    ("position-bool", "position", True, "position", TYPE),
    ("position-acima-do-teto", "position", 10**13, "position", RANGE),
    ("start_timestamp-negativo", "start_timestamp", -1.0, "start_timestamp", RANGE),
    ("start_timestamp-acima-do-teto", "start_timestamp", 10.0**13, "start_timestamp", RANGE),
    ("skin-longa", "skin", "s" * (LIMITES.skin + 1), "skin", LENGTH),
    ("skin_static-longa", "skin_static", "s" * (LIMITES.skin + 1), "skin_static", LENGTH),
    ("skin-numero", "skin", 3, "skin", TYPE),
    ("stage_title_template-longo", "stage_title_template", "t" * (LIMITES.stage_title_template + 1), "stage_title_template", LENGTH),
    ("prefix_info-longo", "prefix_info", "p" * (LIMITES.prefix_info + 1), "prefix_info", LENGTH),
    ("current_encoded-nao-base64", "current_encoded", "isto não é base64!", "current_encoded", "pattern"),
    ("current_encoded-longo", "current_encoded", "A" * (LIMITES.current_encoded + 1), "current_encoded", LENGTH),
    ("dj-texto", "dj", "abc", "dj", TYPE),
    ("dj-bool", "dj", [True], "dj[0]", TYPE),
    ("dj-negativo", "dj", [-1], "dj[0]", RANGE),
    ("dj-texto-no-item", "dj", ["1"], "dj[0]", TYPE),
    ("dj-demais", "dj", list(range(1, LIMITES.dj + 2)), "dj", LENGTH),
    ("lastfm-texto", "lastfm_artists", "x", "lastfm_artists", TYPE),
    ("lastfm-item-numero", "lastfm_artists", [1], "lastfm_artists[0]", TYPE),
    ("lastfm-item-longo", "lastfm_artists", ["a" * 257], "lastfm_artists[0]", LENGTH),
    ("lastfm-demais", "lastfm_artists", ["a"] * (LIMITES.lastfm_artists + 1), "lastfm_artists", LENGTH),
    ("log-dicionario", "command_log_list", {}, "command_log_list", TYPE),
    ("log-demais", "command_log_list", [{"text": "t", "emoji": "e", "timestamp": 1.0}] * (LIMITES.command_log + 1), "command_log_list", LENGTH),
    ("log-texto-longo", "command_log_list", [{"text": "t" * (LIMITES.log_text + 1), "emoji": "e", "timestamp": 1.0}], "command_log_list[0].text", LENGTH),
    ("log-emoji-longo", "command_log_list", [{"text": "t", "emoji": "e" * (LIMITES.log_emoji + 1), "timestamp": 1.0}], "command_log_list[0].emoji", LENGTH),
    ("log-timestamp-texto", "command_log_list", [{"text": "t", "emoji": "e", "timestamp": "x"}], "command_log_list[0].timestamp", TYPE),
    ("log-sem-texto", "command_log_list", [{"emoji": "e", "timestamp": 1.0}], "command_log_list[0].text", MISSING),
    ("queue-dicionario", "queue", {}, "queue", TYPE),
    ("queue-demais", "queue", [{}] * (LIMITES.queue + 1), "queue", LENGTH),
    ("played-demais", "played", [{}] * (LIMITES.played + 1), "played", LENGTH),
    ("queue_autoplay-demais", "queue_autoplay", [{}] * (LIMITES.queue_autoplay + 1), "queue_autoplay", LENGTH),
    ("failed_tracks-demais", "failed_tracks", [{}] * (LIMITES.failed_tracks + 1), "failed_tracks", LENGTH),
    ("played-texto", "played", "x", "played", TYPE),
]  # fmt: skip


class TestTiposETetos:
    @pytest.mark.parametrize(
        ("campo", "valor", "caminho", "codigo"),
        list([r[1:] for r in RECUSAS])[:2],
        ids=list([r[0] for r in RECUSAS])[:2],
    )
    def test_decode_recusa_no_campo_certo(self, campo, valor, caminho, codigo):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert erro.path == caminho and erro.code == codigo

    @pytest.mark.parametrize("campo", list(IDS_OPCIONAIS)[:2])
    def test_ids_opcionais_aceitam_none(self, campo):
        assert decodificar(bruto(**{campo: None}))[campo] is None

    @pytest.mark.parametrize("loop", [False, "queue"])
    def test_loop_do_player_real(self, loop):
        assert decodificar(bruto(loop=loop))["loop"] == loop

    @pytest.mark.parametrize("loop", ["off", {}])
    def test_loop_fora_do_conjunto_fechado(self, loop):
        erro = falha(decodificar, bruto(loop=loop))
        assert erro.path == "loop" and uma_de(erro, TYPE, "pattern", RANGE, "value")

    @pytest.mark.parametrize("versao", [0, None])
    def test_versao_do_documento(self, versao):
        assert falha(decodificar, bruto(v=versao)).code == VERSION

    def test_queue_vazia_e_valida(self):
        assert decodificar(bruto(queue=[]))["queue"] == []


# ============================================================================ _id do conteúdo == o esperado (condição 2 do 5.1)


class TestIdentidade:
    def test_id_diferente_do_esperado_e_recusado(self):
        erro = falha(session.decode_session, codificar(_id=222), expected_id=111)
        assert (erro.path, erro.code) == ("_id", "id_mismatch")

    @pytest.mark.parametrize("esperado", ["111", -1])
    def test_esperado_de_tipo_errado_nao_vira_um_passe_livre(self, esperado):
        with pytest.raises((schema.SchemaError, TypeError, ValueError)):
            session.decode_session(codificar(_id=111), expected_id=esperado)


# ============================================================================ time: nem imortal nem do futuro (R2)


class TestTime:
    @pytest.mark.parametrize("texto", ["1999-12-31T23:59:59+00:00", "1970-01-01T00:00:00+00:00"])
    def test_antes_de_2000_e_recusado(self, texto):
        erro = falha(decodificar, bruto(time=texto))
        assert (erro.path, erro.code) == ("time", RANGE)

    @pytest.mark.parametrize("texto", ["0001-01-01T00:00:00+05:00", "0001-01-01T00:00:00.000001+14:00"])
    def test_data_que_estoura_vira_erro_do_esquema_e_nao_overflow(self, texto):
        assert isinstance(falha(decodificar, bruto(time=texto)), schema.SchemaError)

    @pytest.mark.parametrize("texto", ["2026-10-19T14:03:22", True])
    def test_sem_offset_ou_mal_formada(self, texto):
        erro = falha(decodificar, bruto(time=texto))
        assert erro.path == "time" and uma_de(erro, "pattern", TYPE)

    def test_encode_recusa_datetime_sem_fuso_e_que_nao_seja_datetime(self):
        assert falha(session.encode_session, sessao_minima(time=datetime(2026, 1, 1))).path == "time"


# ============================================================================ números extremos


def com_literal(campo: str, literal: str) -> bytes:
    """O JSON da sessão com o ``literal`` cru (que o ``json.dumps`` não produz) no lugar do valor de ``campo`` da raiz."""
    documento = bruto()
    documento[campo] = "@@LITERAL@@"
    return json.dumps(documento, ensure_ascii=False).replace('"@@LITERAL@@"', literal).encode("utf-8")


class TestNumerosExtremos:
    @pytest.mark.parametrize("campo", ["_id", "message_id"])
    def test_inteiro_de_400_digitos_vira_erro_do_esquema(self, campo):
        erro = falha(session.decode_session, com_literal(campo, "9" * 400))
        assert isinstance(erro, schema.SchemaError) and erro.code in {NUMBER, RANGE, TYPE}

    @pytest.mark.parametrize("campo", ["position", "volume"])
    @pytest.mark.parametrize("literal", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
    def test_nao_finito_e_recusado(self, campo, literal):
        erro = falha(session.decode_session, com_literal(campo, literal))
        assert erro.code in {NOT_FINITE, NUMBER, RANGE, TYPE}

    def test_nenhuma_excecao_que_nao_seja_do_esquema_escapa(self):
        for valor in (10**400, -(10**400), 1e308, -1e308, 5e-324):
            for campo in ("position", "uptime", "volume", "start_timestamp"):
                try:
                    decodificar(bruto(**{campo: valor}))
                except schema.SchemaError:
                    pass


# ============================================================================ a skin da sessão (R5)


class TestSkinNaSessao:
    SKIN = {
        "queue_max_entries": 7,
        "content": "Tocando",
        "embeds": [{"description": "{queue_format}", "color": "{guild.color}"}],
    }

    @pytest.mark.parametrize("campo", ["custom_skin_data", "custom_skin_static_data"])
    def test_uma_skin_valida_passa_como_o_validate_skin_a_devolve(self, campo):
        from empiremuse.serialization.skins import validate_skin

        lida = session.decode_session(codificar(**{campo: {"Minha": copy.deepcopy(self.SKIN)}}))
        assert lida[campo] == {"Minha": validate_skin(self.SKIN)}

    @pytest.mark.parametrize("campo", ["custom_skin_data", "custom_skin_static_data"])
    @pytest.mark.parametrize("valor", [[], [1]])
    def test_o_campo_que_nao_e_dicionario_vira_dicionario_vazio(self, campo, valor):
        assert decodificar(bruto(**{campo: valor}))[campo] == {}

    def test_skin_da_sessao_com_url_invalida_de_embed_e_recusada_como_a_do_editor(self):
        ruim = {"embeds": [{"image": {"url": "javascript:alert(1)"}}]}
        assert session.decode_session(codificar(custom_skin_data={"A": ruim}))["custom_skin_data"] == {}


# ============================================================================ vazamento


class TestSemVazamento:
    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("skin", SEGREDO + "s" * 300),
            ("lastfm_artists", [SEGREDO + "a" * 300]),
        ],
    )
    def test_o_erro_nunca_leva_o_valor(self, campo, valor):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert vazamentos(erro) == []

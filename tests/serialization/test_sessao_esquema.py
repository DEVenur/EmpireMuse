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
from tests.support.serializacao_nucleo import NUMBER, RANGE, SEGREDO, TYPE, VERSION, falha, schema, vazamentos
from tests.support.sessoes import IDS_OPCIONAIS, bruto, codificar, decodificar, session, sessao_minima

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


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


class TestTiposETetos:
    @pytest.mark.parametrize("campo", list(IDS_OPCIONAIS)[:2])
    def test_ids_opcionais_aceitam_none(self, campo):
        assert decodificar(bruto(**{campo: None}))[campo] is None

    @pytest.mark.parametrize("loop", [False, "queue"])
    def test_loop_do_player_real(self, loop):
        assert decodificar(bruto(loop=loop))["loop"] == loop

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

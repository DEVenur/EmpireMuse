"""F3-6b, etapa 5 (RED, commit 1 do plano do Backend) — o esquema da sessão: ``empiremuse/serialization/session.py``.

Cobre ``encode_session``, ``decode_session`` e ``validate_session`` (sem tocar no produto): ida e volta com a sessão REAL do
``save_info``, tipos e tetos de cada campo, ``voice_state``/``extra_info`` fora, ``_id`` do conteúdo == o esperado (condição 2 do
5.1), ``time`` (R2: nem imortal nem do futuro) e números/datas extremos, o esquema da skin da sessão (R5) e o vazamento.
As faixas (URLs, R1) estão em ``tests/serialization/test_sessao_faixas.py`` e a redução por tamanho (R6) em ``..._tamanho.py``.
Decisões em ``tests/support/sessoes.py``.
"""

import copy
import json
import logging
from datetime import datetime, timedelta, timezone

import disnake
import pytest

from tests.support.formatos_reais import (
    CANAL_DE_TEXTO,
    CANAL_DE_VOZ,
    DJ_A,
    DJ_B,
    DONO,
    INSTANTE,
    MENSAGEM,
    SERVIDOR,
    cog_de_sessoes,
)
from tests.support.serializacao_nucleo import (
    CONTROL,
    LENGTH,
    MISSING,
    NOT_FINITE,
    NUMBER,
    RANGE,
    SEGREDO,
    SURROGATE,
    TYPE,
    VERSION,
    falha,
    schema,
    vazamentos,
)
from tests.support.sessoes import (
    BOOLEANOS,
    IDS_OPCIONAIS,
    LIMITES,
    SURROGATE_SOLTO,
    bruto,
    codificar,
    decodificar,
    em_bytes,
    faixa_info,
    session,
    sessao_minima,
)
from tests.persistence.test_formato_sessao import esperado_da_sessao, gravar, jogador_completo

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def uma_de(erro, *codigos) -> bool:
    return erro.code in codigos


# ============================================================================ ida e volta


class TestIdaEVolta:
    @pytest.mark.asyncio
    async def test_a_sessao_real_do_save_info_volta_igual(self):
        jogador = jogador_completo()
        dados = await gravar(cog_de_sessoes(), jogador)
        lida = session.decode_session(session.encode_session(dados), expected_id=SERVIDOR)
        esperado = esperado_da_sessao(jogador)
        esperado["dj"] = sorted(esperado["dj"])
        assert lida == esperado

    def test_os_tipos_que_o_resume_player_consome(self):
        lida = session.decode_session(
            codificar(dj={DJ_B, DJ_A}, command_log_list=[{"text": "t", "emoji": "x", "timestamp": 1.5}])
        )
        assert type(lida["time"]) is datetime and lida["time"] == INSTANTE and lida["time"].utcoffset() == timedelta(0)
        assert type(lida["dj"]) is list and lida["dj"] == sorted([DJ_A, DJ_B])
        assert type(lida["command_log_list"]) is list and lida["command_log_list"][0]["timestamp"] == 1.5
        assert "v" not in lida

    def test_o_json_e_utf8_compacto_com_versao_e_sem_pickle(self):
        bytes_ = codificar()
        documento = json.loads(bytes_)
        assert bytes_[:1] == b"{" and b": " not in bytes_ and documento["v"] == 1
        assert documento["time"] == "2026-10-19T14:03:22.123456+00:00"
        assert "voice_state" not in documento and "extra_info" not in documento

    def test_o_dj_vai_ordenado_e_sem_repeticao_para_o_arquivo_ser_estavel(self):
        assert json.loads(codificar(dj={DJ_B, DJ_A, 5}))["dj"] == sorted([DJ_A, DJ_B, 5])
        assert codificar(dj={DJ_A, DJ_B}) == codificar(dj={DJ_B, DJ_A})

    def test_encode_nao_altera_a_entrada(self):
        dados = sessao_minima(dj={DJ_A}, custom_skin_data={"Minha": {"content": "c"}})
        antes = copy.deepcopy(dados)
        session.encode_session(dados)
        assert dados == antes and type(dados["dj"]) is set

    def test_encode_aceita_deque_de_log_e_set_de_dj(self):
        from collections import deque

        log = deque([{"text": "a", "emoji": "▶️", "timestamp": 1.0}], maxlen=10)
        lida = session.decode_session(codificar(dj={1, 2}, command_log_list=log))
        assert lida["command_log_list"] == [{"text": "a", "emoji": "▶️", "timestamp": 1.0}] and lida["dj"] == [1, 2]

    @pytest.mark.parametrize("versao", [1, 1.1], ids=["inteira", "do-player-real"])
    def test_version_aceita_o_numero_do_player_real(self, versao):
        assert session.decode_session(codificar(version=versao))["version"] == versao

    def test_validate_session_devolve_copia_limpa_no_formato_do_consumidor(self):
        dados = sessao_minima(dj={DJ_A}, voice_state={"x": 1}, extra_info={"a": (1, 2)}, lixo=1)
        limpa = session.validate_session(dados)
        assert limpa is not dados and "voice_state" not in limpa and "extra_info" not in limpa and "lixo" not in limpa
        assert limpa["time"] == INSTANTE and limpa["_id"] == SERVIDOR


# ============================================================================ voice_state, extra_info e o que o esquema não conhece


class TestCamposQueSaem:
    def test_voice_state_e_extra_info_na_entrada_nao_derrubam_nem_vao_para_o_arquivo(self):
        entrada = sessao_minima(
            voice_state={"sessionId": SEGREDO, "event": {"token": SEGREDO, "endpoint": "voz.exemplo.invalid"}},
            extra_info={"guild-yt-oauth": ("token", 1, (2, 3))},
        )
        arquivo = session.encode_session(entrada)
        assert SEGREDO.encode() not in arquivo and b"voice_state" not in arquivo and b"extra_info" not in arquivo
        lida = session.decode_session(arquivo)
        assert "voice_state" not in lida and "extra_info" not in lida

    def test_voice_state_e_extra_info_plantados_no_json_sao_descartados_na_leitura(self):
        documento = bruto(voice_state={"sessionId": SEGREDO}, extra_info={"a": 1}, desconhecido=[1, 2])
        lida = decodificar(documento)
        assert set(lida) == set(decodificar(bruto()))
        assert SEGREDO not in json.dumps(lida, default=str)

    def test_descartar_nao_faz_barulho(self, caplog):
        with caplog.at_level(logging.DEBUG):
            decodificar(bruto(voice_state={"a": SEGREDO}, extra_info={"b": SEGREDO}, desconhecido=SEGREDO))
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

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
        ("campo", "valor", "caminho", "codigo"), [r[1:] for r in RECUSAS], ids=[r[0] for r in RECUSAS]
    )
    def test_decode_recusa_no_campo_certo(self, campo, valor, caminho, codigo):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert erro.path == caminho and erro.code == codigo

    @pytest.mark.parametrize("campo", IDS_OPCIONAIS)
    @pytest.mark.parametrize(("valor", "codigo"), [("1", TYPE), (True, TYPE), (-5, RANGE), (2**63, RANGE), (1.5, TYPE)])
    def test_ids_opcionais(self, campo, valor, codigo):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert (erro.path, erro.code) == (campo, codigo)

    @pytest.mark.parametrize("campo", IDS_OPCIONAIS)
    def test_ids_opcionais_aceitam_none(self, campo):
        assert decodificar(bruto(**{campo: None}))[campo] is None

    @pytest.mark.parametrize("campo", BOOLEANOS)
    @pytest.mark.parametrize("valor", [1, 0, "true", "sim", [True]])
    def test_booleanos_so_aceitam_booleano(self, campo, valor):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert (erro.path, erro.code) == (campo, TYPE)

    @pytest.mark.parametrize("campo", BOOLEANOS)
    def test_booleanos_aceitam_none_porque_o_player_real_grava_none(self, campo):
        assert decodificar(bruto(**{campo: None}))[campo] is None

    @pytest.mark.parametrize("loop", [False, "current", "queue"])
    def test_loop_do_player_real(self, loop):
        assert decodificar(bruto(loop=loop))["loop"] == loop

    @pytest.mark.parametrize("loop", ["off", "all", "", 1, [], {}])
    def test_loop_fora_do_conjunto_fechado(self, loop):
        erro = falha(decodificar, bruto(loop=loop))
        assert erro.path == "loop" and uma_de(erro, TYPE, "pattern", RANGE, "value")

    @pytest.mark.parametrize("campo", ["voice_channel", "_id", "time", "queue", "v"])
    def test_campo_obrigatorio_ausente_recusa_a_sessao(self, campo):
        documento = bruto()
        del documento[campo]
        erro = falha(decodificar, documento)
        assert uma_de(erro, MISSING, VERSION) and (campo == "v" or erro.path == campo)

    @pytest.mark.parametrize("versao", [0, 2, 99, True, "1", None])
    def test_versao_do_documento(self, versao):
        assert falha(decodificar, bruto(v=versao)).code == VERSION

    def test_no_teto_exato_tudo_passa(self):
        documento = bruto(
            volume=LIMITES.volume,
            skin="s" * LIMITES.skin,
            stage_title_template="t" * LIMITES.stage_title_template,
            prefix_info="p" * LIMITES.prefix_info,
            current_encoded="A" * LIMITES.current_encoded,
            dj=list(range(1, LIMITES.dj + 1)),
            lastfm_artists=["a" * 256] * LIMITES.lastfm_artists,
            command_log_list=[{"text": "t" * LIMITES.log_text, "emoji": "e" * LIMITES.log_emoji, "timestamp": 1.0}]
            * LIMITES.command_log,
            position=float(LIMITES.numero_maximo // 10),
            start_timestamp=float(LIMITES.numero_maximo // 10),
        )
        lida = decodificar(documento)
        assert lida["volume"] == 1000 and len(lida["dj"]) == 100 and len(lida["command_log_list"]) == 10

    def test_listas_de_faixas_no_teto_exato_passam(self):
        documento = bruto(
            queue=[faixa_info(0)] * LIMITES.queue,
            played=[faixa_info(1)] * LIMITES.played,
            queue_autoplay=[faixa_info(2)] * LIMITES.queue_autoplay,
            failed_tracks=[faixa_info(3)] * LIMITES.failed_tracks,
        )
        lida = decodificar(documento)
        assert (len(lida["queue"]), len(lida["played"]), len(lida["queue_autoplay"]), len(lida["failed_tracks"])) == (
            LIMITES.queue,
            LIMITES.played,
            LIMITES.queue_autoplay,
            LIMITES.failed_tracks,
        )

    def test_queue_vazia_e_valida(self):
        assert decodificar(bruto(queue=[]))["queue"] == []

    def test_as_chaves_do_log_desconhecidas_saem(self):
        item = {"text": "t", "emoji": "e", "timestamp": 1.0, "extra": SEGREDO}
        assert decodificar(bruto(command_log_list=[item]))["command_log_list"] == [
            {"text": "t", "emoji": "e", "timestamp": 1.0}
        ]

    def test_surrogate_solto_em_qualquer_texto_recusa_a_sessao_inteira(self):
        """A leitura do JSON já recusa o documento com surrogate solto (quebraria o envio ao Discord e a gravação no Mongo)."""
        assert falha(decodificar, bruto(stage_title_template=SURROGATE_SOLTO)).code == SURROGATE

    def test_texto_da_sessao_com_controle_e_recusado_mas_o_do_log_aceita_emoji(self):
        assert falha(decodificar, bruto(prefix_info="a\x00b")).code == CONTROL
        assert decodificar(bruto(command_log_list=[{"text": "ok", "emoji": "👨\u200d👩", "timestamp": 1.0}]))


# ============================================================================ _id do conteúdo == o esperado (condição 2 do 5.1)


class TestIdentidade:
    def test_id_diferente_do_esperado_e_recusado(self):
        erro = falha(session.decode_session, codificar(_id=222), expected_id=111)
        assert (erro.path, erro.code) == ("_id", "id_mismatch")

    def test_id_igual_passa(self):
        assert session.decode_session(codificar(_id=SERVIDOR), expected_id=SERVIDOR)["_id"] == SERVIDOR

    def test_sem_esperado_nao_confere(self):
        assert session.decode_session(codificar(_id=222))["_id"] == 222

    @pytest.mark.parametrize("esperado", ["111", True, 1.5, -1])
    def test_esperado_de_tipo_errado_nao_vira_um_passe_livre(self, esperado):
        with pytest.raises((schema.SchemaError, TypeError, ValueError)):
            session.decode_session(codificar(_id=111), expected_id=esperado)

    def test_o_erro_de_id_nao_leva_os_numeros(self):
        erro = falha(session.decode_session, codificar(_id=987654321987), expected_id=123456789123)
        assert "987654321987" not in repr(erro.args) + str(erro) and "123456789123" not in repr(erro.args) + str(erro)

    def test_validate_session_tambem_confere(self):
        erro = falha(session.validate_session, sessao_minima(_id=222), expected_id=111)
        assert erro.code == "id_mismatch"


# ============================================================================ time: nem imortal nem do futuro (R2)


class TestTime:
    @pytest.mark.parametrize(
        "texto", ["1999-12-31T23:59:59+00:00", "0001-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00"]
    )
    def test_antes_de_2000_e_recusado(self, texto):
        erro = falha(decodificar, bruto(time=texto))
        assert (erro.path, erro.code) == ("time", RANGE)

    def test_2000_exato_passa(self):
        assert decodificar(bruto(time="2000-01-01T00:00:00+00:00"))["time"] == datetime(2000, 1, 1, tzinfo=UTC)

    @pytest.mark.parametrize(
        "texto", ["2100-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00", "3000-06-01T12:00:00+03:00"]
    )
    def test_futuro_e_recusado_porque_tornaria_a_sessao_imortal(self, texto):
        erro = falha(decodificar, bruto(time=texto))
        assert (erro.path, erro.code) == ("time", RANGE)

    @pytest.mark.parametrize(
        "texto", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00.000001+14:00"]
    )
    def test_data_que_estoura_vira_erro_do_esquema_e_nao_overflow(self, texto):
        assert isinstance(falha(decodificar, bruto(time=texto)), schema.SchemaError)

    @pytest.mark.parametrize(
        "texto", ["2026-10-19T14:03:22", "ontem", "2026-13-45T00:00:00+00:00", "", "2026-10-19", 20261019, None, True]
    )
    def test_sem_offset_ou_mal_formada(self, texto):
        erro = falha(decodificar, bruto(time=texto))
        assert erro.path == "time" and uma_de(erro, "pattern", TYPE)

    def test_outro_fuso_volta_em_utc(self):
        lida = decodificar(bruto(time="2026-10-19T11:03:22.123456-03:00"))["time"]
        assert lida == INSTANTE and lida.utcoffset() == timedelta(0)

    def test_encode_recusa_datetime_sem_fuso_e_que_nao_seja_datetime(self):
        assert falha(session.encode_session, sessao_minima(time=datetime(2026, 1, 1))).path == "time"

    @pytest.mark.parametrize("quando", [datetime(1999, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)])
    def test_encode_recusa_instante_fora_do_intervalo(self, quando):
        erro = falha(session.encode_session, sessao_minima(time=quando))
        assert (erro.path, erro.code) == ("time", RANGE)

    @pytest.mark.parametrize(
        "quando",
        [
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5))),
            datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-5))),
        ],
    )
    def test_encode_recusa_datetime_que_estoura_ao_converter_para_utc(self, quando):
        assert isinstance(falha(session.encode_session, sessao_minima(time=quando)), schema.SchemaError)


# ============================================================================ números extremos


def com_literal(campo: str, literal: str) -> bytes:
    """O JSON da sessão com o ``literal`` cru (que o ``json.dumps`` não produz) no lugar do valor de ``campo`` da raiz."""
    documento = bruto()
    documento[campo] = "@@LITERAL@@"
    return json.dumps(documento, ensure_ascii=False).replace('"@@LITERAL@@"', literal).encode("utf-8")


class TestNumerosExtremos:
    @pytest.mark.parametrize(
        "campo", ["_id", "voice_channel", "volume", "uptime", "position", "start_timestamp", "message_id"]
    )
    def test_inteiro_de_400_digitos_vira_erro_do_esquema(self, campo):
        erro = falha(session.decode_session, com_literal(campo, "9" * 400))
        assert isinstance(erro, schema.SchemaError) and erro.code in {NUMBER, RANGE, TYPE}

    @pytest.mark.parametrize("campo", ["position", "start_timestamp", "uptime", "volume"])
    @pytest.mark.parametrize("literal", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
    def test_nao_finito_e_recusado(self, campo, literal):
        erro = falha(session.decode_session, com_literal(campo, literal))
        assert erro.code in {NOT_FINITE, NUMBER, RANGE, TYPE}

    @pytest.mark.parametrize("campo", ["_id", "voice_channel"])
    def test_snowflake_no_limite(self, campo):
        assert decodificar(bruto(**{campo: 2**63 - 1}))[campo] == 2**63 - 1
        assert falha(decodificar, bruto(**{campo: 2**63})).code == RANGE

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
    def test_skin_invalida_vira_dicionario_vazio_e_a_sessao_segue(self, campo, caplog):
        ruim = {"embeds": [{"description": SEGREDO + "d" * 5000}]}
        with caplog.at_level(logging.DEBUG):
            lida = session.decode_session(codificar(**{campo: {"Minha": ruim}}))
        assert lida[campo] == {} and lida["queue"] and lida["_id"] == SERVIDOR
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    @pytest.mark.parametrize("campo", ["custom_skin_data", "custom_skin_static_data"])
    def test_mais_de_uma_entrada_vira_dicionario_vazio(self, campo):
        lida = session.decode_session(
            codificar(**{campo: {"A": copy.deepcopy(self.SKIN), "B": copy.deepcopy(self.SKIN)}})
        )
        assert lida[campo] == {}

    @pytest.mark.parametrize("campo", ["custom_skin_data", "custom_skin_static_data"])
    @pytest.mark.parametrize("valor", [[], "x", 3, [1]])
    def test_o_campo_que_nao_e_dicionario_vira_dicionario_vazio(self, campo, valor):
        assert decodificar(bruto(**{campo: valor}))[campo] == {}

    def test_o_nome_da_skin_nao_e_mexido_na_leitura(self):
        nome = "v1.2 $teste"
        assert session.decode_session(codificar(custom_skin_data={nome: copy.deepcopy(self.SKIN)}))[
            "custom_skin_data"
        ].keys() == {nome}

    def test_skin_da_sessao_com_url_invalida_de_embed_e_recusada_como_a_do_editor(self):
        ruim = {"embeds": [{"image": {"url": "javascript:alert(1)"}}]}
        assert session.decode_session(codificar(custom_skin_data={"A": ruim}))["custom_skin_data"] == {}


# ============================================================================ vazamento


class TestSemVazamento:
    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("skin", SEGREDO + "s" * 300),
            ("stage_title_template", SEGREDO + SURROGATE_SOLTO),
            ("prefix_info", SEGREDO + "\x00"),
            ("current_encoded", SEGREDO + "!"),
            ("time", SEGREDO),
            ("volume", SEGREDO),
            ("dj", [SEGREDO]),
            ("lastfm_artists", [SEGREDO + "a" * 300]),
        ],
    )
    def test_o_erro_nunca_leva_o_valor(self, campo, valor):
        erro = falha(decodificar, bruto(**{campo: valor}))
        assert vazamentos(erro) == []

    def test_o_log_da_recusa_so_leva_o_servidor_e_o_motivo(self, caplog):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(schema.SchemaError):
                decodificar(bruto(stage_title_template=SEGREDO + "t" * 600))
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

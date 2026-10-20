"""F3-6b, etapa 5 (RED, commit 2) — a MIGRAÇÃO das sessões do MONGO: ``PlayerSession.migrate_legacy_sessions()``.

Por documento da coleção ``player_sessions`` (legado): ``data`` (texto) → ``load_legacy(texto, "session")`` → validação → documento novo
em ``player_sessions_json`` → LEITURA de volta e conferência do ``_id`` → só então ``delete_data`` do legado. Falha de gravação ou
de releitura deixa o legado; documento que não converte ganha ``failed_at`` (epoch, ``$set``, uma vez) e some depois de 48 h.

Decisões finais do MAESTRO (R3, R4): a leitura é por CURSOR (``iter_data``, entregue aos poucos; ``query_data`` ignora o ``limit`` e
traria a coleção inteira para a memória), em lotes de 10 com ``asyncio.sleep(0.5)`` ENTRE lotes e teto de 500 documentos por subida;
``failed_at`` só em ``SchemaError``/``LegacyFormatError`` (erro transitório nunca grava nem apaga).
"""

import asyncio
import base64
import logging
import time
import tracemalloc
import zlib

import disnake
import pytest

from tests.helpers_f3_6b import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.helpers_f3_6b_corte import (
    cargas_hostis,
    criar_armadilhas,
    espionar_load_legacy,
    log_sem_o_conteudo,
    registrou,
)
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_sessao import (
    HORAS,
    MongoDeSessoes,
    envelope_antigo_do_mongo,
    envelope_do_mongo,
    session,
    sessao_legada,
    sessao_minima,
)

NOVA, ANTIGA = "player_sessions_json", "player_sessions"
OUTRO = SERVIDOR + 7
MIB = 1024 * 1024
HOSTIS = ["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"]


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


@pytest.fixture
def armadilhas(tmp_path, monkeypatch):
    return criar_armadilhas(tmp_path, monkeypatch)


@pytest.fixture
def pausas(monkeypatch):
    """Registra os ``asyncio.sleep`` e não espera de verdade."""
    registro = []

    async def falso(segundos, *args, **kwargs):
        registro.append(segundos)

    monkeypatch.setattr(asyncio, "sleep", falso)
    return registro


def cog_com_mongo():
    mongo = MongoDeSessoes()
    return cog_de_sessoes(mongo=mongo), mongo


async def legado(mongo, guild=SERVIDOR, dados=None, *, protocolo=4, **documento):
    conteudo = {"data": envelope_antigo_do_mongo(sessao_legada(_id=guild) if dados is None else dados, protocolo)}
    conteudo.update(documento)
    await mongo.update_data(guild, conteudo, db_name=BOT_ID, collection=ANTIGA)


async def legado_cru(mongo, guild, texto, **documento):
    await mongo.update_data(guild, {"data": texto, **documento}, db_name=BOT_ID, collection=ANTIGA)


def zerar(mongo):
    mongo.eventos.clear()
    mongo.consumidos = 0
    mongo.consumidos_por.clear()


def lido_do_novo(mongo, guild=SERVIDOR) -> dict:
    return session.decode_session(zlib.decompress(base64.b64decode(mongo.doc(NOVA, guild)["data"])), expected_id=guild)


def escritas_no_legado(mongo):
    return [e for e in mongo.eventos if e[0] == "update" and e[1] == ANTIGA]


# ============================================================================ o caminho feliz


class TestConversao:
    @pytest.mark.asyncio
    async def test_documento_valido_vira_o_formato_novo_e_o_legado_sai(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == set() and mongo.ids(NOVA) == {str(SERVIDOR)}
        assert lido_do_novo(mongo) == session.validate_session(sessao_legada())
        assert mongo.doc(NOVA, SERVIDOR)["v"] == 1

    @pytest.mark.asyncio
    async def test_o_novo_nao_leva_voice_state_nem_extra_info(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        await cog.migrate_legacy_sessions()
        bruto = zlib.decompress(base64.b64decode(mongo.doc(NOVA, SERVIDOR)["data"]))
        assert SEGREDO.encode() not in bruto and b"voice_state" not in bruto and b"extra_info" not in bruto

    @pytest.mark.asyncio
    async def test_grava_le_de_volta_e_so_depois_apaga(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        passos = [(acao, colecao) for acao, colecao, id_ in mongo.eventos if id_ in {str(SERVIDOR), "*"}]
        escrita = passos.index(("update", NOVA))
        leitura = next(i for i, p in enumerate(passos) if p == ("leitura", NOVA) and i > escrita)
        exclusao = passos.index(("delete", ANTIGA))
        assert escrita < leitura < exclusao

    @pytest.mark.asyncio
    async def test_a_segunda_rodada_nao_escreve_nem_apaga_nada(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        await cog.migrate_legacy_sessions()
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        assert not [e for e in mongo.eventos if e[0] in {"update", "delete"}]

    @pytest.mark.asyncio
    async def test_instancia_antiga_que_gravou_de_novo_reentra_e_vence(self):
        cog, mongo = cog_com_mongo()
        await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=11))
        await legado(mongo, dados=sessao_legada(volume=77))
        await cog.migrate_legacy_sessions()
        assert lido_do_novo(mongo)["volume"] == 77 and mongo.ids(ANTIGA) == set()

    @pytest.mark.asyncio
    async def test_o_legado_so_e_lido_por_load_legacy_com_o_kind_session(self, monkeypatch):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        chamadas = espionar_load_legacy(monkeypatch)
        await cog.migrate_legacy_sessions()
        assert chamadas == [("session", "str")]

    @pytest.mark.asyncio
    async def test_varios_documentos_cada_um_no_seu_id(self):
        cog, mongo = cog_com_mongo()
        for guild in (SERVIDOR, OUTRO):
            await legado(mongo, guild)
        await cog.migrate_legacy_sessions()
        assert mongo.ids(NOVA) == {str(SERVIDOR), str(OUTRO)} and mongo.ids(ANTIGA) == set()
        assert lido_do_novo(mongo, OUTRO)["_id"] == OUTRO

    @pytest.mark.asyncio
    async def test_sem_mongo_configurado_nao_faz_nada_com_o_mongo(self):
        cog = cog_de_sessoes(MONGO="")
        await cog.migrate_legacy_sessions()

    @pytest.mark.asyncio
    async def test_documento_valido_converte_mesmo_com_failed_at_antigo(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, failed_at=time.time() - 60 * HORAS)
        await cog.migrate_legacy_sessions()
        assert mongo.ids(NOVA) == {str(SERVIDOR)} and mongo.ids(ANTIGA) == set()


# ============================================================================ o que não converte fica, com failed_at


class TestRecusadosFicam:
    async def semear_ruim(self, mongo, nome, armadilhas):
        if nome in HOSTIS:
            carga, codigo = cargas_hostis(armadilhas)[nome]
            await legado_cru(mongo, SERVIDOR, base64.b64encode(zlib.compress(carga)).decode())
            return codigo
        if nome == "protocolo-antigo":
            await legado(mongo, protocolo=3)
            return "protocol"
        if nome == "sem-data":
            await mongo.update_data(SERVIDOR, {"outro": 1}, db_name=BOT_ID, collection=ANTIGA)
            return None
        if nome == "data-numero":
            await mongo.update_data(SERVIDOR, {"data": 123}, db_name=BOT_ID, collection=ANTIGA)
            return None
        if nome == "base64-invalido":
            await legado_cru(mongo, SERVIDOR, SEGREDO + "!!!")
            return "envelope"
        if nome == "id-diferente":
            await legado(mongo, SERVIDOR, sessao_legada(_id=SERVIDOR + 1))
            return "id_mismatch"
        if nome == "time-9999":
            from datetime import datetime, timezone

            await legado(mongo, SERVIDOR, sessao_legada(time=datetime(9999, 12, 31, tzinfo=timezone.utc)))
            return "range"
        raise AssertionError(nome)

    NOMES = [*HOSTIS, "protocolo-antigo", "sem-data", "data-numero", "base64-invalido", "id-diferente", "time-9999"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", NOMES)
    async def test_nao_converte_nao_apaga_e_marca_failed_at(self, nome, armadilhas, caplog, capsys):
        cog, mongo = cog_com_mongo()
        codigo = await self.semear_ruim(mongo, nome, armadilhas)
        antes = mongo.doc(ANTIGA, SERVIDOR).get("data")
        zerar(mongo)
        agora = time.time()
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        documento = mongo.doc(ANTIGA, SERVIDOR)
        assert (
            documento is not None
            and documento.get("data") == antes
            and mongo.ids(NOVA) == set()
            and mongo.apagados == []
        )
        assert type(documento["failed_at"]) in {int, float} and abs(documento["failed_at"] - agora) < 60
        assert armadilhas.intacto() and log_sem_o_conteudo(caplog, capsys)
        if codigo:
            assert registrou(caplog, SERVIDOR, codigo)

    @pytest.mark.asyncio
    async def test_a_unica_escrita_no_legado_e_o_failed_at_com_set(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3)
        antes = dict(mongo.doc(ANTIGA, SERVIDOR))
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        assert len(escritas_no_legado(mongo)) == 1
        depois = dict(mongo.doc(ANTIGA, SERVIDOR))
        assert {k: v for k, v in depois.items() if k != "failed_at"} == antes

    @pytest.mark.asyncio
    async def test_failed_at_existente_nao_e_reescrito(self):
        cog, mongo = cog_com_mongo()
        antigo = time.time() - 5 * HORAS
        await legado(mongo, protocolo=3, failed_at=antigo)
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        assert escritas_no_legado(mongo) == [] and mongo.doc(ANTIGA, SERVIDOR)["failed_at"] == antigo

    @pytest.mark.asyncio
    async def test_com_mais_de_48_horas_de_failed_at_o_documento_e_apagado_com_aviso_de_info(self, caplog):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at=time.time() - 49 * HORAS)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == set() and mongo.ids(NOVA) == set()
        assert [r for r in caplog.records if r.levelno == logging.INFO and str(SERVIDOR) in r.getMessage()]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("horas", [1, 24, 47])
    async def test_com_menos_de_48_horas_fica(self, horas):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at=time.time() - horas * HORAS)
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)}

    @pytest.mark.asyncio
    async def test_failed_at_que_nao_e_numero_conta_como_ausente(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at="ontem")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and type(mongo.doc(ANTIGA, SERVIDOR)["failed_at"]) in {int, float}

    @pytest.mark.asyncio
    async def test_data_acima_de_12_mib_e_recusada_antes_de_decodificar_e_marcada(self):
        cog, mongo = cog_com_mongo()
        await legado_cru(mongo, SERVIDOR, "A" * (12 * MIB + 1))
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            await cog.migrate_legacy_sessions()
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and "failed_at" in mongo.doc(ANTIGA, SERVIDOR)
        assert time.perf_counter() - inicio < 2.0 and pico < 24 * MIB

    @pytest.mark.asyncio
    async def test_um_documento_ruim_nao_impede_os_outros(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, SERVIDOR, protocolo=3)
        await legado(mongo, OUTRO)
        await cog.migrate_legacy_sessions()
        assert mongo.ids(NOVA) == {str(OUTRO)} and mongo.ids(ANTIGA) == {str(SERVIDOR)}


# ============================================================================ erro transitório nunca grava failed_at nem apaga (R4)


class TestErroTransitorio:
    @pytest.mark.asyncio
    async def test_falha_ao_gravar_o_novo_deixa_o_legado_sem_failed_at(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        mongo.falhas[f"update:{NOVA}"] = ConnectionError("Mongo fora")
        zerar(mongo)
        await cog.migrate_legacy_sessions()  # nenhuma exceção
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and "failed_at" not in mongo.doc(ANTIGA, SERVIDOR)
        assert mongo.apagados == []

    @pytest.mark.asyncio
    async def test_falha_ao_reler_o_novo_deixa_o_legado_sem_failed_at(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        mongo.falhas[f"leitura:{NOVA}"] = ConnectionError("Mongo fora")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and "failed_at" not in mongo.doc(ANTIGA, SERVIDOR)

    @pytest.mark.asyncio
    async def test_falha_ao_ler_o_legado_nao_derruba_nem_apaga(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        mongo.falhas[f"leitura:{ANTIGA}"] = ConnectionError("Mongo fora")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and mongo.apagados == []

    @pytest.mark.asyncio
    async def test_falha_ao_apagar_o_legado_mantem_os_dois_e_nao_derruba(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        mongo.falhas[f"delete:{ANTIGA}"] = ConnectionError("Mongo fora")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and mongo.ids(NOVA) == {str(SERVIDOR)}
        assert "failed_at" not in mongo.doc(ANTIGA, SERVIDOR)

    @pytest.mark.asyncio
    async def test_erro_transitorio_nunca_apaga_nem_com_failed_at_antigo(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, failed_at=time.time() - 60 * HORAS)
        mongo.falhas[f"update:{NOVA}"] = ConnectionError("Mongo fora")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)}

    @pytest.mark.asyncio
    async def test_releitura_que_voltou_adulterada_mantem_o_legado(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)

        def adulterar(documento):
            documento["data"] = envelope_do_mongo(session.encode_session(sessao_minima(_id=SERVIDOR + 99)))
            return documento

        mongo.adulterar[NOVA] = adulterar
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)}


# ============================================================================ ritmo: cursor, lotes de 10, pausa de 0,5 s e teto de 500


class TestRitmo:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("quantos", "pausas_esperadas"), [(1, 0), (10, 0), (11, 1), (25, 2), (30, 2), (31, 3)])
    async def test_pausa_de_meio_segundo_entre_os_lotes_de_dez(self, pausas, quantos, pausas_esperadas):
        cog, mongo = cog_com_mongo()
        for n in range(quantos):
            await legado(mongo, SERVIDOR + n)
        await cog.migrate_legacy_sessions()
        assert [p for p in pausas if p > 0] == [0.5] * pausas_esperadas
        assert len(mongo.ids(NOVA)) == quantos

    @pytest.mark.asyncio
    async def test_o_teto_e_de_500_documentos_por_subida_e_o_resto_fica_para_a_proxima(self, pausas, caplog):
        cog, mongo = cog_com_mongo()
        for n in range(520):
            await legado(mongo, SERVIDOR + n)
        zerar(mongo)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert len(mongo.ids(NOVA)) == 500 and len(mongo.ids(ANTIGA)) == 20
        assert [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and ("20" in r.getMessage() or "500" in r.getMessage())
        ]
        await cog.migrate_legacy_sessions()
        assert len(mongo.ids(NOVA)) == 520 and mongo.ids(ANTIGA) == set()

    @pytest.mark.asyncio
    async def test_a_leitura_e_por_cursor_e_para_no_teto_sem_trazer_a_colecao_inteira(self, pausas):
        cog, mongo = cog_com_mongo()
        for n in range(520):
            await legado(mongo, SERVIDOR + n)
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        assert mongo.consumidos_por[ANTIGA] <= 501

    @pytest.mark.asyncio
    async def test_o_que_falha_tambem_conta_para_o_teto(self, pausas):
        cog, mongo = cog_com_mongo()
        for n in range(520):
            await legado(mongo, SERVIDOR + n, protocolo=3)
        await cog.migrate_legacy_sessions()
        marcados = [d for d in mongo.colecao(BOT_ID, ANTIGA).values() if "failed_at" in d]
        assert len(marcados) == 500

    @pytest.mark.asyncio
    async def test_a_migracao_nao_usa_query_data_que_ignora_o_limit(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        colecoes = []
        original = mongo.query_data

        async def espiao(db_name, collection, filter=None, limit=100):
            colecoes.append(collection)
            return await original(db_name, collection, filter, limit)

        mongo.query_data = espiao
        await cog.migrate_legacy_sessions()
        assert ANTIGA not in colecoes

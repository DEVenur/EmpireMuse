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
import zlib

import disnake
import pytest

from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.chave_de_corte import cargas_hostis, criar_armadilhas, espionar_load_legacy
from tests.support.leitor_legado import SEGREDO
from tests.support.sessoes import (
    HORAS,
    MongoDeSessoes,
    envelope_antigo_do_mongo,
    envelope_do_mongo,
    session,
    sessao_legada,
    sessao_minima,
)

pytestmark = pytest.mark.critical

NOVA, ANTIGA = "player_sessions_json", "player_sessions"
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


# ============================================================================ o caminho feliz


class TestConversao:
    @pytest.mark.asyncio
    async def test_o_novo_nao_leva_voice_state_nem_extra_info(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        await cog.migrate_legacy_sessions()
        bruto = zlib.decompress(base64.b64decode(mongo.doc(NOVA, SERVIDOR)["data"]))
        assert SEGREDO.encode() not in bruto and b"voice_state" not in bruto and b"extra_info" not in bruto

    @pytest.mark.asyncio
    async def test_a_segunda_rodada_nao_escreve_nem_apaga_nada(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        await cog.migrate_legacy_sessions()
        zerar(mongo)
        await cog.migrate_legacy_sessions()
        assert not [e for e in mongo.eventos if e[0] in {"update", "delete"}]

    @pytest.mark.asyncio
    async def test_o_legado_so_e_lido_por_load_legacy_com_o_kind_session(self, monkeypatch):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        chamadas = espionar_load_legacy(monkeypatch)
        await cog.migrate_legacy_sessions()
        assert chamadas == [("session", "str")]

    @pytest.mark.asyncio
    async def test_sem_mongo_configurado_nao_faz_nada_com_o_mongo(self):
        cog = cog_de_sessoes(MONGO="")
        await cog.migrate_legacy_sessions()


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
    async def test_com_mais_de_48_horas_de_failed_at_o_documento_e_apagado_com_aviso_de_info(self, caplog):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at=time.time() - 49 * HORAS)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == set() and mongo.ids(NOVA) == set()
        assert [r for r in caplog.records if r.levelno == logging.INFO and str(SERVIDOR) in r.getMessage()]

    @pytest.mark.asyncio
    async def test_failed_at_que_nao_e_numero_conta_como_ausente(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at="ontem")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and type(mongo.doc(ANTIGA, SERVIDOR)["failed_at"]) in {int, float}


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
    async def test_falha_ao_ler_o_legado_nao_derruba_nem_apaga(self):
        cog, mongo = cog_com_mongo()
        await legado(mongo)
        mongo.falhas[f"leitura:{ANTIGA}"] = ConnectionError("Mongo fora")
        await cog.migrate_legacy_sessions()
        assert mongo.ids(ANTIGA) == {str(SERVIDOR)} and mongo.apagados == []

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
    async def test_o_teto_de_documentos_por_subida_deixa_o_resto_para_a_proxima(self, pausas, caplog, monkeypatch):
        monkeypatch.setattr("empiremuse.utils.music.session_store.MIGRATION_CAP", 25)  # em produção são 500
        cog, mongo = cog_com_mongo()
        for n in range(30):
            await legado(mongo, SERVIDOR + n)
        zerar(mongo)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert len(mongo.ids(NOVA)) == 25 and len(mongo.ids(ANTIGA)) == 5
        assert [
            r for r in caplog.records if r.levelno == logging.INFO and ("5" in r.getMessage() or "25" in r.getMessage())
        ]
        await cog.migrate_legacy_sessions()
        assert len(mongo.ids(NOVA)) == 30 and mongo.ids(ANTIGA) == set()

    @pytest.mark.asyncio
    async def test_o_que_falha_tambem_conta_para_o_teto(self, pausas, monkeypatch):
        monkeypatch.setattr("empiremuse.utils.music.session_store.MIGRATION_CAP", 25)  # em produção são 500
        cog, mongo = cog_com_mongo()
        for n in range(30):
            await legado(mongo, SERVIDOR + n, protocolo=3)
        await cog.migrate_legacy_sessions()
        marcados = [d for d in mongo.colecao(BOT_ID, ANTIGA).values() if "failed_at" in d]
        assert len(marcados) == 25

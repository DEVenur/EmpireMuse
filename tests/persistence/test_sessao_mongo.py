"""F3-6b, etapa 5 (RED, commit 2) — as sessões no MONGO: ``save_session_mongo``, ``get_player_sessions_mongo``, ``delete_data_mongo``.

Formato novo: coleção ``player_sessions_json`` (por bot), um documento por servidor ``{_id: str(guild), v: 1, data: base64(zlib(JSON))}``.
O legado (``player_sessions``) NÃO é lido aqui (só pela migração, ``..._migracao_mongo.py``). A leitura confere o tamanho do texto
ANTES de decodificar (12 MiB), o ``_id`` do documento contra o do conteúdo, e nunca apaga nada por causa de um documento ruim.
"""

import base64
import contextlib
import logging
import time
import tracemalloc
import zlib

import disnake
import pytest

from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.chave_de_corte import log_sem_o_conteudo
from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import schema
from tests.support.sessoes import MongoDeSessoes, envelope_do_mongo, session, sessao_minima
from tests.persistence.test_formato_sessao import gravar, jogador_completo

NOVA, ANTIGA = "player_sessions_json", "player_sessions"
OUTRO = SERVIDOR + 7
MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def cog_com_mongo():
    mongo = MongoDeSessoes()
    return cog_de_sessoes(mongo=mongo), mongo


async def semear(mongo, guild, dados=None, **documento):
    """Grava direto no Mongo de mentira, sem passar pelo ``save_session_mongo`` (o que um atacante ou outra instância faria)."""
    conteudo = {"v": 1, "data": envelope_do_mongo(session.encode_session(dados or sessao_minima(_id=guild)))}
    conteudo.update(documento)
    await mongo.update_data(guild, conteudo, db_name=BOT_ID, collection=NOVA)
    mongo.eventos.clear()


# ============================================================================ gravação


class TestGravacao:
    @pytest.mark.asyncio
    async def test_grava_um_documento_por_servidor_so_na_colecao_nova(self):
        cog, mongo = cog_com_mongo()
        await cog.save_info(jogador_completo())
        assert list(mongo.documentos) == [(str(BOT_ID), NOVA)] and mongo.ids(NOVA) == {str(SERVIDOR)}

    @pytest.mark.asyncio
    async def test_o_documento_tem_so_id_versao_e_o_envelope(self):
        cog, mongo = cog_com_mongo()
        dados = await gravar(cog, jogador_completo())
        await cog.save_session_mongo(SERVIDOR, dados)
        documento = mongo.doc(NOVA, SERVIDOR)
        assert set(documento) == {"_id", "v", "data"} and documento["_id"] == str(SERVIDOR) and documento["v"] == 1
        assert zlib.decompress(base64.b64decode(documento["data"])) == session.encode_session(dados)

    @pytest.mark.asyncio
    async def test_regravar_substitui_o_mesmo_documento(self):
        cog, mongo = cog_com_mongo()
        await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=11))
        await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=22))
        assert mongo.ids(NOVA) == {str(SERVIDOR)}
        assert (
            session.decode_session(zlib.decompress(base64.b64decode(mongo.doc(NOVA, SERVIDOR)["data"])))["volume"] == 22
        )

    @pytest.mark.asyncio
    async def test_dados_que_o_esquema_recusa_nao_gravam_nada(self):
        cog, mongo = cog_com_mongo()
        with contextlib.suppress(
            schema.SchemaError
        ):  # recusar com erro ou em silêncio vale; o que importa é não gravar
            await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=5000))
        assert mongo.ids(NOVA) == set()

    @pytest.mark.asyncio
    async def test_o_destino_segue_a_configuracao(self, tmp_path):
        cog, mongo = cog_com_mongo()
        await cog.save_info(jogador_completo())
        assert mongo.ids(NOVA) and not (tmp_path / "local_database").exists()


# ============================================================================ leitura


class TestLeitura:
    @pytest.mark.asyncio
    async def test_ida_e_volta(self):
        cog, mongo = cog_com_mongo()
        dados = await gravar(cog, jogador_completo())
        await cog.save_session_mongo(SERVIDOR, dados)
        (lida,) = await cog.get_player_sessions_mongo()
        assert lida == session.validate_session(dados)

    @pytest.mark.asyncio
    async def test_sem_mongo_configurado_nao_le_nada(self):
        assert await cog_de_sessoes(MONGO="").get_player_sessions_mongo() == []

    @pytest.mark.asyncio
    async def test_mais_de_cem_sessoes_voltam_todas(self):
        cog, mongo = cog_com_mongo()
        for n in range(150):
            await semear(mongo, SERVIDOR + n)
        assert len(await cog.get_player_sessions_mongo()) == 150

    @pytest.mark.asyncio
    async def test_nao_le_a_colecao_do_legado(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        await mongo.update_data(OUTRO, {"data": "x"}, db_name=BOT_ID, collection=ANTIGA)
        mongo.eventos.clear()
        assert [s["_id"] for s in await cog.get_player_sessions_mongo()] == [SERVIDOR]
        assert not [e for e in mongo.eventos if e[1] == ANTIGA]

    @pytest.mark.asyncio
    async def test_a_leitura_nao_apaga_nem_reescreve(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        await mongo.update_data(OUTRO, {"v": 1, "data": "lixo"}, db_name=BOT_ID, collection=NOVA)
        mongo.eventos.clear()
        await cog.get_player_sessions_mongo()
        assert not [e for e in mongo.eventos if e[0] in {"update", "delete"}] and mongo.apagados == []


RUINS = {
    "sem-data": lambda: {"v": 1},
    "data-numero": lambda: {"v": 1, "data": 123},
    "data-lista": lambda: {"v": 1, "data": ["x"]},
    "base64-invalido": lambda: {"v": 1, "data": SEGREDO + "!!!"},
    "zlib-invalido": lambda: {"v": 1, "data": base64.b64encode(b"isto nao e zlib " + SEGREDO.encode()).decode()},
    "json-lixo": lambda: {"v": 1, "data": envelope_do_mongo(b"{lixo " + SEGREDO.encode())},
    "id-do-conteudo-diferente": lambda: {
        "v": 1,
        "data": envelope_do_mongo(session.encode_session(sessao_minima(_id=SERVIDOR + 1))),
    },
    "time-9999": lambda: {"v": 1, "data": envelope_do_mongo(_com_time("9999-12-31T23:59:59+00:00"))},
    "time-1999": lambda: {"v": 1, "data": envelope_do_mongo(_com_time("1999-01-01T00:00:00+00:00"))},
    "versao-futura": lambda: {"v": 2, "data": envelope_do_mongo(session.encode_session(sessao_minima(_id=OUTRO)))},
}


def _com_time(texto: str) -> bytes:
    import json

    documento = json.loads(session.encode_session(sessao_minima(_id=OUTRO)))
    documento["time"] = texto
    return json.dumps(documento).encode()


class TestDocumentoRuim:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", sorted(RUINS))
    async def test_e_pulado_fica_no_banco_e_avisa_so_com_servidor_e_motivo(self, nome, caplog, capsys):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        await mongo.update_data(OUTRO, RUINS[nome](), db_name=BOT_ID, collection=NOVA)
        mongo.eventos.clear()
        with caplog.at_level(logging.DEBUG):
            lidas = await cog.get_player_sessions_mongo()
        assert [s["_id"] for s in lidas] == [SERVIDOR]
        assert str(OUTRO) in mongo.ids(NOVA) and mongo.apagados == []
        avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(OUTRO) in m for m in avisos) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identificador", ["abc", "1" * 21, "-5", "12 3", "١٢٣"])
    async def test_documento_com_id_que_nao_e_de_servidor_e_ignorado(self, identificador):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        await mongo.update_data(
            identificador,
            {"v": 1, "data": envelope_do_mongo(session.encode_session(sessao_minima()))},
            db_name=BOT_ID,
            collection=NOVA,
        )
        assert [s["_id"] for s in await cog.get_player_sessions_mongo()] == [SERVIDOR]
        assert identificador in mongo.ids(NOVA) and mongo.apagados == []

    @pytest.mark.asyncio
    async def test_data_acima_de_12_mib_e_recusada_antes_de_decodificar(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        enorme = "A" * (12 * MIB + 1)
        await mongo.update_data(OUTRO, {"v": 1, "data": enorme}, db_name=BOT_ID, collection=NOVA)
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            lidas = await cog.get_player_sessions_mongo()
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert [s["_id"] for s in lidas] == [SERVIDOR] and str(OUTRO) in mongo.ids(NOVA)
        assert time.perf_counter() - inicio < 2.0 and pico < 24 * MIB

    @pytest.mark.asyncio
    async def test_um_documento_ruim_nao_impede_os_outros(self):
        cog, mongo = cog_com_mongo()
        for guild in (SERVIDOR, SERVIDOR + 1, SERVIDOR + 2):
            await semear(mongo, guild)
        await mongo.update_data(OUTRO, RUINS["json-lixo"](), db_name=BOT_ID, collection=NOVA)
        assert sorted(s["_id"] for s in await cog.get_player_sessions_mongo()) == [SERVIDOR, SERVIDOR + 1, SERVIDOR + 2]


# ============================================================================ remoção


class TestRemocao:
    @pytest.mark.asyncio
    async def test_remove_dos_dois_formatos_so_do_servidor_pedido(self):
        cog, mongo = cog_com_mongo()
        for guild in (SERVIDOR, OUTRO):
            await semear(mongo, guild)
            await mongo.update_data(guild, {"data": "legado"}, db_name=BOT_ID, collection=ANTIGA)
        await cog.delete_data_mongo(SERVIDOR)
        assert mongo.ids(NOVA) == {str(OUTRO)} and mongo.ids(ANTIGA) == {str(OUTRO)}

    @pytest.mark.asyncio
    async def test_delete_data_vai_para_o_mongo_quando_o_destino_e_o_mongo(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        await cog.delete_data(SERVIDOR)
        assert mongo.ids(NOVA) == set()

    @pytest.mark.asyncio
    async def test_remover_o_que_nao_existe_nao_falha(self):
        cog, _ = cog_com_mongo()
        await cog.delete_data_mongo(SERVIDOR)

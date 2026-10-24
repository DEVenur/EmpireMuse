"""F3-6b, etapa 5 (RED, commit 2) — as sessões no MONGO: ``save_session_mongo``, ``get_player_sessions_mongo``, ``delete_data_mongo``.

Formato novo: coleção ``player_sessions_json`` (por bot), um documento por servidor ``{_id: str(guild), v: 1, data: base64(zlib(JSON))}``.
O legado (``player_sessions``) NÃO é lido aqui (só pela migração, ``..._migracao_mongo.py``). A leitura confere o tamanho do texto
ANTES de decodificar (12 MiB), o ``_id`` do documento contra o do conteúdo, e nunca apaga nada por causa de um documento ruim.
"""

import base64
import zlib

import disnake
import pytest

from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.sessoes import MongoDeSessoes, envelope_do_mongo, session, sessao_minima
from tests.support.formato_sessao import jogador_completo

pytestmark = pytest.mark.critical

NOVA, ANTIGA = "player_sessions_json", "player_sessions"
OUTRO = SERVIDOR + 7


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
    async def test_regravar_substitui_o_mesmo_documento(self):
        cog, mongo = cog_com_mongo()
        await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=11))
        await cog.save_session_mongo(SERVIDOR, sessao_minima(volume=22))
        assert mongo.ids(NOVA) == {str(SERVIDOR)}
        assert (
            session.decode_session(zlib.decompress(base64.b64decode(mongo.doc(NOVA, SERVIDOR)["data"])))["volume"] == 22
        )

    @pytest.mark.asyncio
    async def test_o_destino_segue_a_configuracao(self, tmp_path):
        cog, mongo = cog_com_mongo()
        await cog.save_info(jogador_completo())
        assert mongo.ids(NOVA) and not (tmp_path / "local_database").exists()


# ============================================================================ leitura


class TestLeitura:
    @pytest.mark.asyncio
    async def test_sem_mongo_configurado_nao_le_nada(self):
        assert await cog_de_sessoes(MONGO="").get_player_sessions_mongo() == []

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


class TestDocumentoRuim:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("identificador", ["abc", "١٢٣"])
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
    async def test_remover_o_que_nao_existe_nao_falha(self):
        cog, _ = cog_com_mongo()
        await cog.delete_data_mongo(SERVIDOR)

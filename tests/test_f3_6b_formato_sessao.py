"""F3-6b, etapa 0 — caracterização da sessão do player no formato ATUAL (round-trip e legado, sem produção alterada).

Roda o ``PlayerSession.save_info`` REAL com faixas das classes reais (``LavalinkTrack``, ``PartialTrack``) e lê de volta
pelo ``get_player_sessions_local``/``get_player_sessions_mongo`` REAIS, no disco (``tmp_path``) e em um Mongo em memória.

Dois grupos:

* o que continua valendo depois da migração para JSON (``TestRoundTripDoDisco``, ``TestRoundTripDoMongo``,
  ``TestTiposDaSessao``): os mesmos dados e os mesmos tipos (``datetime`` UTC, ``set``, lista de log) voltam iguais;
* o que descrevia o formato antigo (pickle, protocolos, opcodes, ``voice_state``) saiu na etapa 5: o formato novo está em
  ``tests/test_f3_6b_etapa5_*.py`` e a migração do legado em ``test_f3_6b_etapa5_migracao_*.py``.
"""

import base64
import copy
import pickle
import zlib
from datetime import timedelta

import disnake
import pytest
import pytest_asyncio

from empiremuse.utils.music.interactions import base_skin
from tests.helpers_f3_6b import (
    BOT_ID,
    CANAL_DE_TEXTO,
    CANAL_DE_VOZ,
    DJ_A,
    DJ_B,
    DONO,
    INSTANTE,
    MENSAGEM,
    SERVIDOR,
    MongoEmMemoria,
    cog_de_sessoes,
    faixa_com_playlist,
    faixa_deezer,
    faixa_parcial,
    faixa_youtube,
    globais_do_pickle,
    jogador_falso,
    letras_sincronizadas,
    opcodes_do_pickle,
    protocolo_do_pickle,
)

# Opcodes que o gravador de hoje gera para a sessão (protocolos 4 e 5): ``STACK_GLOBAL`` e ``REDUCE`` só aparecem por
# causa de ``datetime`` e ``deque``. Fora desta lista não aparece nada (sem ``GLOBAL``, ``INST``, ``OBJ``, ``BUILD``,
# ``NEWOBJ`` nem ``PUT``/``BINPUT``: o protocolo 4 grava o memo por ``MEMOIZE``, sem índice explícito).
OPCODES_DA_SESSAO = frozenset(
    "PROTO FRAME STOP MARK NONE NEWTRUE NEWFALSE BININT BININT1 BININT2 LONG1 BINFLOAT SHORT_BINUNICODE BINUNICODE "
    "SHORT_BINBYTES BINBYTES EMPTY_LIST EMPTY_DICT EMPTY_TUPLE EMPTY_SET APPEND APPENDS SETITEM SETITEMS ADDITEMS "
    "TUPLE1 TUPLE2 TUPLE3 MEMOIZE BINGET LONG_BINGET STACK_GLOBAL REDUCE".split()
)
OPCODES_SEM_LUGAR = frozenset(
    "GLOBAL INST OBJ BUILD NEWOBJ NEWOBJ_EX FROZENSET EXT1 EXT2 EXT4 PERSID BINPERSID NEXT_BUFFER READONLY_BUFFER "
    "PUT BINPUT LONG_BINPUT".split()
)
GLOBAIS_DA_SESSAO = {
    ("datetime", "datetime"),
    ("datetime", "timezone"),
    ("datetime", "timedelta"),
    ("collections", "deque"),
}
CAMPOS_QUE_A_ETAPA_5_REMOVE = {"voice_state", "extra_info"}
CAMPOS_DA_SESSAO = {
    "_id", "version", "volume", "nightcore", "position", "voice_channel", "dj", "player_creator", "static", "paused",
    "text_channel_id", "message_id", "keep_connected", "loop", "autoplay", "stage_title_event", "stage_title_template",
    "skin", "skin_static", "custom_skin_data", "custom_skin_static_data", "uptime", "restrict_mode",
    "mini_queue_enabled", "listen_along_invite", "queue", "played", "queue_autoplay", "failed_tracks", "prefix_info",
    "time", "lastfm_artists", "start_timestamp", "last_voice_channel_id", "live_lyrics_status", "current_encoded",
    "command_log_list",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def jogador_completo(**campos):
    """Jogador com uma faixa atual (com letras), fila (Deezer, parcial, de playlist), tocadas, autoplay e falhas."""
    return jogador_falso(
        atual=faixa_youtube(0, letras=letras_sincronizadas()),
        fila=[faixa_deezer(1), faixa_parcial(2), faixa_com_playlist(3)],
        tocadas=[faixa_youtube(4)],
        autoplay=[faixa_youtube(5)],
        falhas=[faixa_youtube(6)],
        **campos,
    )


def infos(faixas):
    return [copy.deepcopy(faixa.info) for faixa in faixas]


async def gravar(cog, jogador) -> dict:
    """Roda o ``save_info`` real e devolve o ``data`` que ele montou (sem gravar em lugar nenhum)."""
    capturado = {}

    async def capturar(player, data):
        capturado.update(data)

    cog.save_session = capturar
    await cog.save_info(jogador)
    return capturado


def pasta_das_sessoes(tmp_path):
    return tmp_path / "local_database" / "player_sessions" / str(BOT_ID)


def esperado_da_sessao(jogador) -> dict:
    return {
        "_id": SERVIDOR,
        "version": 1,
        "volume": 80,
        "nightcore": True,
        "position": 45123.5,
        "voice_channel": CANAL_DE_VOZ,
        "dj": sorted([DJ_A, DJ_B]),  # o JSON guarda o conjunto como lista ordenada; o resume_player faz set(...)
        "player_creator": DONO,
        "static": False,
        "paused": True,
        "text_channel_id": CANAL_DE_TEXTO,
        "message_id": MENSAGEM,
        "keep_connected": True,
        "loop": "queue",
        "autoplay": True,
        "stage_title_event": False,
        "stage_title_template": "{track.title}",
        "skin": "default",
        "skin_static": "default",
        "custom_skin_data": {},
        "custom_skin_static_data": {},
        "uptime": 1234567,
        "restrict_mode": False,
        "mini_queue_enabled": True,
        "listen_along_invite": "https://exemplo.invalid/convite",
        "prefix_info": "!!",
        "time": INSTANTE,
        "lastfm_artists": ["Artista"],
        "start_timestamp": 1760882602.5,
        "last_voice_channel_id": CANAL_DE_VOZ,
        "live_lyrics_status": False,
        "current_encoded": "QAAAcodificado0",
        "command_log_list": list(jogador.command_log_list),
        "queue": infos([jogador.current, *jogador.queue]),
        "played": infos(jogador.played),
        "queue_autoplay": infos(jogador.queue_autoplay),
        "failed_tracks": infos(jogador.failed_tracks),
    }


def sem_os_campos_da_etapa_5(sessao: dict) -> dict:
    return {campo: valor for campo, valor in sessao.items() if campo not in CAMPOS_QUE_A_ETAPA_5_REMOVE}


# ============================================================================ o que vale antes e depois da migração


class TestRoundTripDoDisco:
    @pytest.mark.asyncio
    async def test_sessao_gravada_volta_igual_com_faixas_das_classes_reais(self, tmp_path):
        cog, jogador = cog_de_sessoes(), jogador_completo()
        await cog.save_info(jogador)
        lidas = await cog.get_player_sessions_local()
        assert len(lidas) == 1
        sessao = sem_os_campos_da_etapa_5(lidas[0])
        esperado = esperado_da_sessao(jogador)
        # o log volta como ``deque`` hoje e como lista depois da migração: a comparação é pelo conteúdo
        sessao["command_log_list"] = list(sessao["command_log_list"])
        assert sessao == esperado

    @pytest.mark.asyncio
    async def test_a_fila_tem_a_faixa_atual_primeiro_e_cada_tipo_de_faixa(self, tmp_path):
        cog, jogador = cog_de_sessoes(), jogador_completo()
        await cog.save_info(jogador)
        fila = (await cog.get_player_sessions_local())[0]["queue"]
        assert [f["sourceName"] for f in fila] == ["youtube", "deezer", "spotify", "youtube"]
        assert fila[0]["extra"]["lyrics"]["lines"][0]["range"] == {"start": 0, "end": 2900}
        assert fila[1]["pluginInfo"]["albumName"] == "Álbum de Teste" and fila[1]["extra"]["artist_id"] == 1
        assert fila[2]["is_partial"] is True and fila[2]["extra"]["requester"] == DONO
        assert fila[3]["playlist"] == {"name": "Minha Playlist", "url": "https://exemplo.invalid/playlist/1"}
        assert all(f["id"] or f.get("is_partial") for f in fila)

    @pytest.mark.asyncio
    async def test_skin_personalizada_do_modo_normal_vai_junto_da_sessao(self, tmp_path):
        skin = {**copy.deepcopy(base_skin), "content": "Tocando agora"}
        jogador = jogador_completo(skin="> custom_skin: Minha", custom_skin_data={"Minha": skin, "Outra": {}})
        cog = cog_de_sessoes()
        await cog.save_info(jogador)
        sessao = (await cog.get_player_sessions_local())[0]
        assert sessao["custom_skin_data"] == {"Minha": skin}
        assert sessao["custom_skin_static_data"] == {}

    @pytest.mark.asyncio
    async def test_skin_personalizada_do_modo_song_request_vai_junto_da_sessao(self, tmp_path):
        skin = copy.deepcopy(base_skin)
        jogador = jogador_completo(
            static=True, skin_static="> custom_skin: Fixa", custom_skin_static_data={"Fixa": skin}
        )
        cog = cog_de_sessoes()
        await cog.save_info(jogador)
        sessao = (await cog.get_player_sessions_local())[0]
        assert sessao["custom_skin_static_data"] == {"Fixa": skin} and sessao["custom_skin_data"] == {}

    @pytest.mark.asyncio
    async def test_varias_sessoes_no_mesmo_bot(self, tmp_path):
        cog = cog_de_sessoes()
        for servidor in (SERVIDOR, SERVIDOR + 10):
            jogador = jogador_falso(atual=faixa_youtube(0))
            jogador.guild.id = servidor
            jogador.bot.music.players = {servidor: jogador}
            await cog.save_info(jogador)
        assert sorted(s["_id"] for s in await cog.get_player_sessions_local()) == [SERVIDOR, SERVIDOR + 10]

    @pytest.mark.asyncio
    async def test_sem_pasta_nao_ha_sessoes(self, tmp_path):
        assert await cog_de_sessoes().get_player_sessions_local() == []


class TestRoundTripDoMongo:
    @pytest.mark.asyncio
    async def test_sessao_gravada_no_mongo_volta_igual(self, tmp_path):
        mongo = MongoEmMemoria()
        cog, jogador = cog_de_sessoes(mongo=mongo), jogador_completo()
        await cog.save_info(jogador)
        lidas = await cog.get_player_sessions_mongo()
        assert len(lidas) == 1
        sessao = sem_os_campos_da_etapa_5(lidas[0])
        sessao["command_log_list"] = list(sessao["command_log_list"])
        assert sessao == esperado_da_sessao(jogador)

    @pytest.mark.asyncio
    async def test_o_mongo_guarda_um_documento_por_servidor_na_colecao_das_sessoes(self, tmp_path):
        mongo = MongoEmMemoria()
        cog = cog_de_sessoes(mongo=mongo)
        await cog.save_info(jogador_completo())
        assert list(mongo.documentos) == [(str(BOT_ID), "player_sessions_json")]
        assert list(mongo.colecao(BOT_ID, "player_sessions_json")) == [str(SERVIDOR)]

    @pytest.mark.asyncio
    async def test_sem_mongo_configurado_nao_le_nada(self, tmp_path):
        assert await cog_de_sessoes(MONGO="").get_player_sessions_mongo() == []

    @pytest.mark.asyncio
    async def test_o_destino_da_gravacao_segue_a_configuracao(self, tmp_path):
        """``PLAYER_SESSIONS_MONGODB`` com ``MONGO`` grava no Mongo; sem um dos dois, grava no disco."""
        mongo = MongoEmMemoria()
        no_mongo = cog_de_sessoes(mongo=mongo)
        await no_mongo.save_info(jogador_completo())
        assert mongo.documentos and not pasta_das_sessoes(tmp_path).exists()

        no_disco = cog_de_sessoes(mongo=MongoEmMemoria(), PLAYER_SESSIONS_MONGODB=False)
        await no_disco.save_info(jogador_completo())
        assert (tmp_path / "local_database" / "player_sessions_json" / str(BOT_ID) / f"{SERVIDOR}.json").is_file()
        assert not pasta_das_sessoes(tmp_path).exists()


class TestTiposDaSessao:
    """Os tipos que a leitura devolve: o que ``resume_player`` espera e o JSON novo tem de reconstruir."""

    @pytest_asyncio.fixture
    async def sessao(self, tmp_path):
        cog = cog_de_sessoes()
        await cog.save_info(jogador_completo())
        return (await cog.get_player_sessions_local())[0]

    @pytest.mark.asyncio
    async def test_time_e_datetime_em_utc(self, sessao):
        assert type(sessao["time"]).__name__ == "datetime"
        assert sessao["time"].utcoffset() == timedelta(0) and sessao["time"] == INSTANTE
        assert (INSTANTE - sessao["time"]).total_seconds() == 0  # aritmética de data com fuso, como o resume faz

    @pytest.mark.asyncio
    async def test_dj_e_lista_ordenada_de_inteiros(self, sessao):
        assert type(sessao["dj"]) is list and sessao["dj"] == sorted([DJ_A, DJ_B])
        assert all(type(membro) is int for membro in sessao["dj"])

    @pytest.mark.asyncio
    async def test_os_ids_sao_inteiros_e_os_booleanos_sao_booleanos(self, sessao):
        for campo in (
            "_id",
            "voice_channel",
            "text_channel_id",
            "message_id",
            "player_creator",
            "last_voice_channel_id",
        ):
            assert type(sessao[campo]) is int, campo
        for campo in ("nightcore", "static", "paused", "keep_connected", "autoplay", "restrict_mode"):
            assert type(sessao[campo]) is bool, campo
        assert type(sessao["position"]) is float and type(sessao["start_timestamp"]) is float

    @pytest.mark.asyncio
    async def test_o_log_de_comandos_mantem_texto_emoji_e_instante(self, sessao):
        log = list(sessao["command_log_list"])
        assert [e["text"] for e in log] == ["Comando 0", "Comando 1", "Comando 2"]
        assert all(set(e) == {"text", "emoji", "timestamp"} and type(e["timestamp"]) is float for e in log)

    @pytest.mark.asyncio
    async def test_a_sessao_tem_exatamente_os_campos_do_plano(self, sessao):
        assert set(sessao) == CAMPOS_DA_SESSAO

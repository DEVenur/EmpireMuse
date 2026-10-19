"""F3-6b, etapa 0 — caracterização da sessão do player no formato ATUAL (round-trip e legado, sem produção alterada).

Roda o ``PlayerSession.save_info`` REAL com faixas das classes reais (``LavalinkTrack``, ``PartialTrack``) e lê de volta
pelo ``get_player_sessions_local``/``get_player_sessions_mongo`` REAIS, no disco (``tmp_path``) e em um Mongo em memória.

Dois grupos:

* o que continua valendo depois da migração para JSON (``TestRoundTripDoDisco``, ``TestRoundTripDoMongo``,
  ``TestTiposDaSessao``): os mesmos dados e os mesmos tipos (``datetime`` UTC, ``set``, lista de log) voltam iguais;
* o que descreve o formato antigo e muda DE PROPÓSITO nas etapas seguintes (``TestFormatoGravadoHoje``,
  ``TestCamposQueAMigracaoDescarta``): envelope, protocolo e opcodes. ``TestLegadoEmVariosProtocolos`` vale DEPOIS da
  etapa 2b: só os protocolos 4 e 5, com ``zlib``, são lidos (por ``load_legacy``). Cada um diz na docstring quando deixa de valer.
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
        "dj": {DJ_A, DJ_B},
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
        assert list(mongo.documentos) == [(str(BOT_ID), "player_sessions")]
        assert list(mongo.colecao(BOT_ID, "player_sessions")) == [str(SERVIDOR)]

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
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").is_file()


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
    async def test_dj_e_set_de_inteiros(self, sessao):
        assert type(sessao["dj"]) is set and sessao["dj"] == {DJ_A, DJ_B}
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
        assert set(sessao) == CAMPOS_DA_SESSAO | CAMPOS_QUE_A_ETAPA_5_REMOVE


# ============================================================================ o que o formato de hoje tem e a migração muda


class TestFormatoGravadoHoje:
    """Descreve o artefato gravado hoje. Deixa de valer na etapa 5 (JSON), quando estes testes são reescritos."""

    @pytest_asyncio.fixture
    async def bytes_do_disco(self, tmp_path):
        await cog_de_sessoes().save_info(jogador_completo())
        return (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").read_bytes()

    @pytest.mark.asyncio
    async def test_o_disco_guarda_pickle_comprimido_com_zlib_e_tira_copia_bak(self, tmp_path, bytes_do_disco):
        assert bytes_do_disco[:1] == b"x"  # cabeçalho do zlib
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.bak").read_bytes() == bytes_do_disco
        assert protocolo_do_pickle(zlib.decompress(bytes_do_disco)) == pickle.DEFAULT_PROTOCOL

    @pytest.mark.asyncio
    async def test_o_protocolo_gravado_e_o_4_ou_o_5(self, bytes_do_disco):
        """Confirma o byte ``PROTO`` do que o código grava de verdade (o leitor restrito só precisa aceitar 4 e 5)."""
        assert protocolo_do_pickle(zlib.decompress(bytes_do_disco)) in {4, 5}

    @pytest.mark.asyncio
    async def test_os_opcodes_gravados_cabem_na_lista_fechada(self, bytes_do_disco):
        usados = set(opcodes_do_pickle(zlib.decompress(bytes_do_disco)))
        assert usados <= OPCODES_DA_SESSAO, sorted(usados - OPCODES_DA_SESSAO)
        assert not usados & OPCODES_SEM_LUGAR

    @pytest.mark.asyncio
    async def test_as_unicas_classes_pedidas_sao_datetime_timezone_timedelta_e_deque(self, bytes_do_disco):
        assert globais_do_pickle(zlib.decompress(bytes_do_disco)) == GLOBAIS_DA_SESSAO

    @pytest.mark.asyncio
    async def test_o_set_do_dj_usa_opcodes_proprios_e_nao_uma_classe(self, bytes_do_disco):
        dados = zlib.decompress(bytes_do_disco)
        assert ("builtins", "set") not in globais_do_pickle(dados)
        assert {"EMPTY_SET", "ADDITEMS"} <= set(opcodes_do_pickle(dados))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_os_protocolos_4_e_5_usam_so_a_lista_fechada_de_opcodes(self, tmp_path, protocolo):
        dados = pickle.dumps(await gravar(cog_de_sessoes(), jogador_completo()), protocol=protocolo)
        usados = set(opcodes_do_pickle(dados))
        assert protocolo_do_pickle(dados) == protocolo
        assert usados <= OPCODES_DA_SESSAO, sorted(usados - OPCODES_DA_SESSAO)
        assert not usados & OPCODES_SEM_LUGAR
        assert globais_do_pickle(dados) == GLOBAIS_DA_SESSAO

    @pytest.mark.asyncio
    async def test_o_mongo_guarda_base64_de_zlib_de_pickle(self, tmp_path):
        mongo = MongoEmMemoria()
        await cog_de_sessoes(mongo=mongo).save_info(jogador_completo())
        documento = mongo.colecao(BOT_ID, "player_sessions")[str(SERVIDOR)]
        assert set(documento) == {"_id", "data"} and isinstance(documento["data"], str)
        dados = zlib.decompress(base64.b64decode(documento["data"]))
        assert protocolo_do_pickle(dados) in {4, 5} and globais_do_pickle(dados) == GLOBAIS_DA_SESSAO

    @pytest.mark.asyncio
    async def test_protocolo_3_pede_o_set_como_classe_e_o_4_nao(self, tmp_path):
        """Por isso o protocolo 3 ou menor não entra no leitor restrito: o ``set`` viria de ``builtins.set``."""
        cog = cog_de_sessoes()
        dados = await gravar(cog, jogador_completo())
        assert ("builtins", "set") in globais_do_pickle(pickle.dumps(dados, protocol=3))
        assert ("builtins", "set") not in globais_do_pickle(pickle.dumps(dados, protocol=4))
        assert ("builtins", "set") not in globais_do_pickle(pickle.dumps(dados, protocol=5))


class TestLegadoEmVariosProtocolos:
    """Depois da 2b (``load_legacy``): sessões nos protocolos 4 e 5 com ``zlib``; o resto é PULADO (e fica no disco/Mongo)."""

    @pytest_asyncio.fixture
    async def sessao_original(self, tmp_path):
        return await gravar(cog_de_sessoes(), jogador_completo())

    @staticmethod
    def escrever_no_disco(tmp_path, dados: bytes, nome=f"{SERVIDOR}.pkl"):
        pasta = pasta_das_sessoes(tmp_path)
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_bytes(dados)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_o_disco_le_a_sessao_nos_protocolos_4_e_5(self, tmp_path, sessao_original, protocolo):
        self.escrever_no_disco(tmp_path, zlib.compress(pickle.dumps(sessao_original, protocol=protocolo)))
        lidas = await cog_de_sessoes().get_player_sessions_local()
        assert lidas == [sessao_original]
        assert (
            type(lidas[0]["dj"]) is set and lidas[0]["time"] == INSTANTE and lidas[0]["command_log_list"].maxlen == 10
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_o_mongo_le_a_sessao_nos_protocolos_4_e_5(self, tmp_path, sessao_original, protocolo):
        mongo = MongoEmMemoria()
        cru = zlib.compress(pickle.dumps(sessao_original, protocol=protocolo))
        await mongo.update_data(
            SERVIDOR, {"data": base64.b64encode(cru).decode()}, db_name=BOT_ID, collection="player_sessions"
        )
        assert await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo() == [sessao_original]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3])
    async def test_o_disco_pula_a_sessao_de_protocolo_antigo_e_deixa_o_arquivo(
        self, tmp_path, sessao_original, protocolo
    ):
        self.escrever_no_disco(tmp_path, zlib.compress(pickle.dumps(sessao_original, protocol=protocolo)))
        assert await cog_de_sessoes().get_player_sessions_local() == []
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").is_file()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3])
    async def test_o_mongo_pula_a_sessao_de_protocolo_antigo_e_deixa_o_documento(
        self, tmp_path, sessao_original, protocolo
    ):
        mongo = MongoEmMemoria()
        cru = zlib.compress(pickle.dumps(sessao_original, protocol=protocolo))
        await mongo.update_data(
            SERVIDOR, {"data": base64.b64encode(cru).decode()}, db_name=BOT_ID, collection="player_sessions"
        )
        assert await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo() == []
        assert str(SERVIDOR) in mongo.colecao(BOT_ID, "player_sessions") and mongo.apagados == []

    @pytest.mark.asyncio
    async def test_o_disco_pula_pickle_sem_zlib(self, tmp_path, sessao_original):
        """Sem o antigo "se não for zlib, lê assim mesmo": o envelope é obrigatório."""
        self.escrever_no_disco(tmp_path, pickle.dumps(sessao_original, protocol=4))
        assert await cog_de_sessoes().get_player_sessions_local() == []

    @pytest.mark.asyncio
    async def test_o_mongo_pula_texto_sem_zlib(self, tmp_path, sessao_original):
        mongo = MongoEmMemoria()
        cru = base64.b64encode(pickle.dumps(sessao_original, protocol=4)).decode()
        await mongo.update_data(SERVIDOR, {"data": cru}, db_name=BOT_ID, collection="player_sessions")
        assert await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo() == []

    @pytest.mark.asyncio
    async def test_so_arquivos_pkl_sao_lidos_e_o_bak_fica_de_fora(self, tmp_path, sessao_original):
        dados = zlib.compress(pickle.dumps(sessao_original, protocol=4))
        self.escrever_no_disco(tmp_path, dados, f"{SERVIDOR}.bak")
        self.escrever_no_disco(tmp_path, dados, f"{SERVIDOR}.json")
        assert await cog_de_sessoes().get_player_sessions_local() == []

    @pytest.mark.asyncio
    async def test_o_nome_do_arquivo_nao_e_validado_hoje(self, tmp_path, sessao_original):
        """Qualquer nome ``*.pkl`` vira caminho e é lido; a etapa 5 passa a exigir só dígitos (1 a 20)."""
        self.escrever_no_disco(tmp_path, zlib.compress(pickle.dumps(sessao_original)), "nome qualquer.pkl")
        assert await cog_de_sessoes().get_player_sessions_local() == [sessao_original]


class TestCamposQueAMigracaoDescarta:
    """``voice_state`` e ``extra_info`` são gravados e lidos hoje; o JSON novo não os leva (migração descarta)."""

    @pytest.mark.asyncio
    async def test_voice_state_e_extra_info_sao_gravados_e_voltam_hoje(self, tmp_path):
        extra = {"guild-yt-oauth": ("token-de-teste", 1)}
        jogador = jogador_completo(extra_info=extra)
        cog = cog_de_sessoes()
        await cog.save_info(jogador)
        sessao = (await cog.get_player_sessions_local())[0]
        assert sessao["voice_state"] == jogador._voice_state
        assert sessao["extra_info"] == extra and type(sessao["extra_info"]["guild-yt-oauth"]) is tuple

    @pytest.mark.asyncio
    async def test_o_resto_da_sessao_nao_depende_desses_dois_campos(self, tmp_path):
        cog = cog_de_sessoes()
        await cog.save_info(jogador_completo(extra_info={}, _voice_state={}))
        sessao = (await cog.get_player_sessions_local())[0]
        assert sessao["voice_state"] == {} and sessao["extra_info"] == {}
        assert len(sessao["queue"]) == 4 and sessao["dj"] == {DJ_A, DJ_B}

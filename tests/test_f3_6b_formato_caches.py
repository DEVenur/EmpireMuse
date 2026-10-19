"""F3-6b, etapa 0 — caracterização dos caches em disco no formato ATUAL (sem produção alterada).

Quatro arquivos: ``playlist_cache.pkl``, ``partial_track_cache.pkl`` e ``.lyric_cache_data`` (em
``local_database/``, lidos pelo ``BotPool.load_cache``) e ``.lastfm_cache`` (na raiz do diretório de dados, lido e
gravado pelo ``LastFM``). Só o cache de playlist (``BotPool.cache_updater``) e o do Last.fm são gravados hoje; os outros
dois são lidos de versões antigas.

* o que continua valendo depois da migração: cache ausente, vazio ou ilegível NÃO derruba a inicialização e o cache
  começa vazio (``TestCacheIlegivel``); o que é gravado volta com as mesmas entradas (``TestRoundTrip``);
* o que muda de propósito (``TestFormatoGravadoHoje``): o gravador de hoje serializa o próprio ``TTLCache``, e por isso o
  arquivo pede classes de ``cachetools`` (e ``time.monotonic``); o leitor restrito da etapa 2 não as aceita, e é daí
  que vem a decisão de os caches não migrarem (descartam). Também fixa o aviso de "descartado" de hoje.
"""

import asyncio
import logging
import pickle
from types import SimpleNamespace

import pytest
from cachetools import TTLCache

from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.helpers_f3_6b import globais_do_pickle, opcodes_do_pickle, protocolo_do_pickle

PLAYLIST = "https://exemplo.invalid/playlist/1"
RESPOSTA_DE_PLAYLIST = {
    "loadType": "PLAYLIST_LOADED",
    "playlistInfo": {"name": "Minha Playlist", "selectedTrack": -1},
    "tracks": [{"track": "QAAAcodificado", "info": {"title": "Música 1", "length": 180000, "sourceName": "youtube"}}],
}
GLOBAIS_DO_TTLCACHE = {
    ("cachetools", "TTLCache"),
    ("cachetools", "TTLCache._Link"),
    ("cachetools", "_TimedCache._Timer"),
    ("collections", "OrderedDict"),
    ("time", "monotonic"),
}


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


def pasta_dos_caches(tmp_path):
    pasta = tmp_path / "local_database"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pool_vazio() -> BotPool:
    """``BotPool`` real sem ``__init__`` (que sobe cliente de Spotify, yt-dlp e o resto), só com os três caches."""
    pool = BotPool.__new__(BotPool)
    pool.playlist_cache = TTLCache(maxsize=500, ttl=1800)
    pool.partial_track_cache = TTLCache(maxsize=1000, ttl=80400)
    pool.lyric_data_cache = TTLCache(maxsize=30000, ttl=6000)
    return pool


ARQUIVOS_DE_CACHE = [
    ("playlist_cache.pkl", "playlist_cache"),
    ("partial_track_cache.pkl", "partial_track_cache"),
    (".lyric_cache_data", "lyric_data_cache"),
]


class Parou(Exception):
    pass


async def gravar_o_cache_de_playlist(pool: BotPool) -> None:
    """Roda o ``BotPool.cache_updater`` REAL por uma volta (o laço é infinito: a segunda espera interrompe)."""
    esperas = []

    async def esperar(segundos):
        esperas.append(segundos)
        if len(esperas) > 1:
            raise Parou

    anterior = client.asyncio
    client.asyncio = SimpleNamespace(sleep=esperar)
    try:
        with pytest.raises(Parou):
            await pool.cache_updater()
    finally:
        client.asyncio = anterior
    assert esperas[0] == 300


# ============================================================================ o que vale antes e depois da migração


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_cache_de_playlist_gravado_volta_com_as_mesmas_entradas(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        pool.playlist_cache["https://exemplo.invalid/playlist/2"] = {"loadType": "EMPTY", "tracks": []}
        await gravar_o_cache_de_playlist(pool)
        novo = pool_vazio()
        novo.load_cache()
        assert dict(novo.playlist_cache.items()) == dict(pool.playlist_cache.items())
        assert novo.playlist_cache[PLAYLIST]["tracks"][0]["info"]["title"] == "Música 1"
        assert not novo.partial_track_cache and not novo.lyric_data_cache

    @pytest.mark.asyncio
    async def test_o_cache_de_playlist_fica_em_local_database_e_a_pasta_e_criada(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1, 2, 3]
        await gravar_o_cache_de_playlist(pool)
        assert (tmp_path / "local_database" / "playlist_cache.pkl").is_file()

    @pytest.mark.asyncio
    async def test_cache_vazio_e_gravado_e_lido_sem_erro(self, tmp_path):
        await gravar_o_cache_de_playlist(pool_vazio())
        novo = pool_vazio()
        novo.load_cache()
        assert len(novo.playlist_cache) == 0

    def test_cache_do_lastfm_gravado_volta_com_as_mesmas_entradas(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["Artista - Música"] = {"name": "Música", "artist": "Artista", "album": "Álbum"}
        lastfm.cache["Sem Resultado - X"] = {}
        lastfm.scrobble_save_cache()
        outro = LastFM("chave", "segredo")
        assert dict(outro.cache.items()) == dict(lastfm.cache.items())
        assert (tmp_path / ".lastfm_cache").is_file() and not (tmp_path / "local_database").exists()

    def test_lastfm_sem_arquivo_comeca_com_cache_vazio(self, tmp_path):
        assert len(LastFM("chave", "segredo").cache) == 0


class TestLeituraDosArquivosAntigos:
    @pytest.mark.parametrize("protocolo", [3, 4, 5])
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_le_cada_cache_nos_protocolos_3_4_e_5(self, tmp_path, protocolo, arquivo, atributo):
        entradas = {PLAYLIST: RESPOSTA_DE_PLAYLIST, "outra": ["a", 1, None, True]}
        (pasta_dos_caches(tmp_path) / arquivo).write_bytes(pickle.dumps(entradas, protocol=protocolo))
        pool = pool_vazio()
        pool.load_cache()
        assert dict(getattr(pool, atributo).items()) == entradas
        for _, outro in ARQUIVOS_DE_CACHE:
            if outro != atributo:
                assert len(getattr(pool, outro)) == 0

    def test_os_tres_arquivos_juntos_vao_cada_um_para_o_seu_cache(self, tmp_path):
        for indice, (arquivo, _) in enumerate(ARQUIVOS_DE_CACHE):
            (pasta_dos_caches(tmp_path) / arquivo).write_bytes(pickle.dumps({f"chave{indice}": indice}))
        pool = pool_vazio()
        pool.load_cache()
        assert [dict(getattr(pool, atributo).items()) for _, atributo in ARQUIVOS_DE_CACHE] == [
            {"chave0": 0},
            {"chave1": 1},
            {"chave2": 2},
        ]

    def test_lastfm_le_o_arquivo_antigo(self, tmp_path):
        (tmp_path / ".lastfm_cache").write_bytes(pickle.dumps({"A - B": {"name": "B", "artist": "A", "album": ""}}))
        assert dict(LastFM("chave", "segredo").cache.items()) == {"A - B": {"name": "B", "artist": "A", "album": ""}}

    def test_sem_arquivos_os_caches_comecam_vazios(self, tmp_path):
        pool = pool_vazio()
        pool.load_cache()
        assert all(len(getattr(pool, atributo)) == 0 for _, atributo in ARQUIVOS_DE_CACHE)


# O mesmo conteúdo ruim em cada arquivo: a inicialização não pode cair e o cache fica vazio, seja qual for o formato.
CONTEUDOS_ILEGIVEIS = {
    "classe-inexistente": b"cnonexistent_module_xyz\nFakeClass\n)\x81}.",
    "bytes-sem-formato": b"BYTES_QUE_NAO_SAO_UM_CACHE",
    "arquivo-vazio": b"",
    "truncado": pickle.dumps({"a": list(range(50))})[:-12],
    "json-que-nao-e-cache": b'{"v": 1, "items": "nao-e-lista"}',
    "so-zeros": b"\x00" * 64,
}


class TestCacheIlegivel:
    @pytest.mark.parametrize("conteudo", list(CONTEUDOS_ILEGIVEIS.values()), ids=list(CONTEUDOS_ILEGIVEIS))
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_cache_ilegivel_nao_derruba_e_fica_vazio(self, tmp_path, arquivo, atributo, conteudo):
        (pasta_dos_caches(tmp_path) / arquivo).write_bytes(conteudo)
        pool = pool_vazio()
        pool.load_cache()
        assert len(getattr(pool, atributo)) == 0

    @pytest.mark.parametrize("conteudo", list(CONTEUDOS_ILEGIVEIS.values()), ids=list(CONTEUDOS_ILEGIVEIS))
    def test_lastfm_ilegivel_nao_derruba_e_fica_vazio(self, tmp_path, conteudo):
        (tmp_path / ".lastfm_cache").write_bytes(conteudo)
        assert len(LastFM("chave", "segredo").cache) == 0

    def test_um_cache_ruim_nao_impede_a_leitura_dos_outros(self, tmp_path):
        pasta = pasta_dos_caches(tmp_path)
        (pasta / "playlist_cache.pkl").write_bytes(CONTEUDOS_ILEGIVEIS["bytes-sem-formato"])
        (pasta / ".lyric_cache_data").write_bytes(pickle.dumps({"letra": {"text": "texto"}}))
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0 and dict(pool.lyric_data_cache.items()) == {"letra": {"text": "texto"}}


# Conteúdos que o ``except`` de hoje (``ModuleNotFoundError``, ``AttributeError``, ``UnpicklingError``, ``EOFError``)
# NÃO trata: o ``pickle`` levanta ``ValueError``, ``UnicodeDecodeError`` ou ``TypeError`` e a inicialização cai.
CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT = {
    "protocolo-desconhecido": b"\x80\x09.",
    "inteiro-malformado": b"I12x\n.",
    "texto-nao-utf8": b"X\x02\x00\x00\x00\xff\xfe.",
    "chave-nao-hashavel": b"(]]d.",
    "pickle-valido-de-inteiro": pickle.dumps(5),
    "pickle-valido-de-lista": pickle.dumps([1, 2, 3]),
}
ESCAPAM = (ValueError, TypeError, UnicodeDecodeError)


@pytest.mark.xfail(
    strict=True,
    raises=ESCAPAM,
    reason="achado de produção: o except de hoje não cobre ValueError, TypeError nem UnicodeDecodeError; "
    "passa quando a etapa 2b parar de ler os caches antigos",
)
class TestCacheIlegivelQueEscapaDoExcept:
    @pytest.mark.parametrize(
        "conteudo", list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT.values()), ids=list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT)
    )
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_cache_com_esse_conteudo_nao_derruba_e_fica_vazio(self, tmp_path, arquivo, atributo, conteudo):
        (pasta_dos_caches(tmp_path) / arquivo).write_bytes(conteudo)
        pool = pool_vazio()
        pool.load_cache()
        assert len(getattr(pool, atributo)) == 0

    @pytest.mark.parametrize(
        "conteudo", list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT.values()), ids=list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT)
    )
    def test_lastfm_com_esse_conteudo_nao_derruba_e_fica_vazio(self, tmp_path, conteudo):
        (tmp_path / ".lastfm_cache").write_bytes(conteudo)
        assert len(LastFM("chave", "segredo").cache) == 0


# ============================================================================ o que o formato de hoje tem e a migração muda


class TestFormatoGravadoHoje:
    """Deixa de valer quando a etapa 2b parar de ler os caches antigos e a etapa 6 gravar JSON."""

    @pytest.mark.asyncio
    async def test_o_cache_de_playlist_e_o_proprio_ttlcache_em_pickle(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        await gravar_o_cache_de_playlist(pool)
        dados = (tmp_path / "local_database" / "playlist_cache.pkl").read_bytes()
        assert protocolo_do_pickle(dados) in {4, 5}
        assert globais_do_pickle(dados) == GLOBAIS_DO_TTLCACHE
        assert {"NEWOBJ", "BUILD"} <= set(opcodes_do_pickle(dados))

    def test_o_cache_do_lastfm_tambem_e_o_ttlcache_em_pickle(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["A - B"] = {"name": "B", "artist": "A", "album": ""}
        lastfm.scrobble_save_cache()
        dados = (tmp_path / ".lastfm_cache").read_bytes()
        assert globais_do_pickle(dados) == GLOBAIS_DO_TTLCACHE

    def test_um_dicionario_comum_pede_so_tipos_simples(self):
        """O que os arquivos antigos "de versão anterior" (dicionário comum) guardam: nenhuma classe."""
        assert globais_do_pickle(pickle.dumps({PLAYLIST: RESPOSTA_DE_PLAYLIST})) == set()

    def test_o_ttlcache_pede_classes_de_fora_das_quatro_do_leitor_restrito(self):
        """Por isso os caches não passam pelo leitor restrito: viram descarte (cache não é dado do usuário)."""
        permitidas = {
            ("datetime", "datetime"),
            ("datetime", "timezone"),
            ("datetime", "timedelta"),
            ("collections", "deque"),
        }
        assert {("cachetools", "TTLCache"), ("time", "monotonic")} <= GLOBAIS_DO_TTLCACHE - permitidas

    @pytest.mark.parametrize(("arquivo", "_atributo"), ARQUIVOS_DE_CACHE)
    def test_cache_ilegivel_e_descartado_com_aviso_no_log(self, tmp_path, caplog, arquivo, _atributo):
        (pasta_dos_caches(tmp_path) / arquivo).write_bytes(CONTEUDOS_ILEGIVEIS["classe-inexistente"])
        with caplog.at_level(logging.WARNING):
            pool_vazio().load_cache()
        mensagens = [registro.getMessage().lower() for registro in caplog.records]
        assert any("descartado" in mensagem and arquivo in mensagem for mensagem in mensagens)

    def test_lastfm_ilegivel_e_descartado_com_aviso_no_log(self, tmp_path, caplog):
        (tmp_path / ".lastfm_cache").write_bytes(CONTEUDOS_ILEGIVEIS["bytes-sem-formato"])
        with caplog.at_level(logging.WARNING, logger=lastfm_tools.logger.name):
            LastFM("chave", "segredo")
        assert any("descartado" in registro.getMessage().lower() for registro in caplog.records)

    def test_a_gravacao_do_lastfm_e_sincrona_e_acontece_a_cada_chamada(self, tmp_path):
        """``scrobble_save_cache`` grava no ato (sem executor): a etapa 6 só muda o formato e o destino."""
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["x"] = {}
        lastfm.scrobble_save_cache()
        primeiro = (tmp_path / ".lastfm_cache").read_bytes()
        lastfm.cache["y"] = {"name": "n", "artist": "a", "album": ""}
        lastfm.scrobble_save_cache()
        assert (tmp_path / ".lastfm_cache").read_bytes() != primeiro
        assert not asyncio.iscoroutinefunction(LastFM.scrobble_save_cache)

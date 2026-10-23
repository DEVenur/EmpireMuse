"""F3-6b, etapas 0, 2b e 6 — os caches em disco: o que a leitura faz com os arquivos ANTIGOS e o que é gravado agora.

Quatro arquivos antigos: ``playlist_cache.pkl``, ``partial_track_cache.pkl`` e ``.lyric_cache_data`` (em ``local_database/``,
tratados pelo ``BotPool.load_cache``) e ``.lastfm_cache`` (na raiz do diretório de dados, tratado pelo ``LastFM``).

Depois da etapa 2b (chave de corte) NENHUM cache legado é lido: o arquivo é apagado sem ser aberto e o cache recomeça vazio
(decisão P3: caches não migram). Desde a etapa 6 só o cache de playlist (``BotPool.cache_updater``) e o do Last.fm são
GRAVADOS, em JSON (``playlist_cache.json`` e ``.lastfm_cache.json``); o formato novo é testado em
``tests/serialization/test_cache_json.py``. Aqui ficam as fixtures compartilhadas, o descarte dos arquivos antigos e o que vale
para qualquer formato: cache ausente ou ilegível não derruba a inicialização.
"""

import asyncio
import pickle
from types import SimpleNamespace

import pytest
from cachetools import TTLCache

from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.utils.music.lastfm_tools import LastFM

PLAYLIST = "https://exemplo.invalid/playlist/1"
RESPOSTA_DE_PLAYLIST = {
    "loadType": "PLAYLIST_LOADED",
    "playlistInfo": {"name": "Minha Playlist", "selectedTrack": -1},
    "tracks": [{"track": "QAAAcodificado", "info": {"title": "Música 1", "length": 180000, "sourceName": "youtube"}}],
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
    async def test_cache_de_playlist_gravado_volta_depois_do_reinicio(self, tmp_path):
        """Desde a etapa 6 o cache é JSON e VOLTA no reinício (dentro do TTL); o ``.pkl`` antigo continua sendo descartado."""
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        await gravar_o_cache_de_playlist(pool)
        arquivo = tmp_path / "local_database" / "playlist_cache.json"
        assert arquivo.is_file()
        novo = pool_vazio()
        novo.load_cache()
        assert novo.playlist_cache.get(PLAYLIST) == RESPOSTA_DE_PLAYLIST
        assert not novo.partial_track_cache and not novo.lyric_data_cache

    @pytest.mark.asyncio
    async def test_o_cache_de_playlist_fica_em_local_database_e_a_pasta_e_criada(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1, 2, 3]
        await gravar_o_cache_de_playlist(pool)
        assert (tmp_path / "local_database" / "playlist_cache.json").is_file()

    @pytest.mark.asyncio
    async def test_cache_vazio_e_gravado_e_o_reinicio_nao_da_erro(self, tmp_path):
        await gravar_o_cache_de_playlist(pool_vazio())
        novo = pool_vazio()
        novo.load_cache()
        assert len(novo.playlist_cache) == 0

    def test_cache_do_lastfm_e_gravado_na_raiz_e_volta_depois_do_reinicio(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["Artista - Música"] = {"name": "Música", "artist": "Artista", "album": "Álbum"}
        lastfm.cache["Sem Resultado - X"] = {}
        lastfm.scrobble_save_cache()
        assert (tmp_path / ".lastfm_cache.json").is_file() and not (tmp_path / "local_database").exists()
        assert len(LastFM("chave", "segredo").cache) == 2

    def test_lastfm_sem_arquivo_comeca_com_cache_vazio(self, tmp_path):
        assert len(LastFM("chave", "segredo").cache) == 0


class TestLeituraDosArquivosAntigos:
    """Depois da 2b, cada arquivo antigo (de QUALQUER protocolo) é descartado: o cache recomeça vazio e o arquivo some."""

    @pytest.mark.parametrize("protocolo", [3, 4, 5])
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_cada_cache_antigo_e_descartado_sem_ser_carregado(self, tmp_path, protocolo, arquivo, atributo):
        entradas = {PLAYLIST: RESPOSTA_DE_PLAYLIST, "outra": ["a", 1, None, True]}
        caminho = pasta_dos_caches(tmp_path) / arquivo
        caminho.write_bytes(pickle.dumps(entradas, protocol=protocolo))
        pool = pool_vazio()
        pool.load_cache()
        assert all(len(getattr(pool, nome)) == 0 for _, nome in ARQUIVOS_DE_CACHE)
        assert not caminho.exists()

    def test_os_tres_arquivos_juntos_somem_e_os_tres_caches_comecam_vazios(self, tmp_path):
        for indice, (arquivo, _) in enumerate(ARQUIVOS_DE_CACHE):
            (pasta_dos_caches(tmp_path) / arquivo).write_bytes(pickle.dumps({f"chave{indice}": indice}))
        pool = pool_vazio()
        pool.load_cache()
        assert all(len(getattr(pool, atributo)) == 0 for _, atributo in ARQUIVOS_DE_CACHE)
        assert [arquivo for arquivo, _ in ARQUIVOS_DE_CACHE if (pasta_dos_caches(tmp_path) / arquivo).exists()] == []

    def test_lastfm_descarta_o_arquivo_antigo(self, tmp_path):
        caminho = tmp_path / ".lastfm_cache"
        caminho.write_bytes(pickle.dumps({"A - B": {"name": "B", "artist": "A", "album": ""}}))
        assert len(LastFM("chave", "segredo").cache) == 0
        assert not caminho.exists()

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

    def test_um_cache_ruim_nao_impede_o_descarte_dos_outros(self, tmp_path):
        pasta = pasta_dos_caches(tmp_path)
        (pasta / "playlist_cache.pkl").write_bytes(CONTEUDOS_ILEGIVEIS["bytes-sem-formato"])
        (pasta / ".lyric_cache_data").write_bytes(pickle.dumps({"letra": {"text": "texto"}}))
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0 and len(pool.lyric_data_cache) == 0
        assert not (pasta / "playlist_cache.pkl").exists() and not (pasta / ".lyric_cache_data").exists()


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

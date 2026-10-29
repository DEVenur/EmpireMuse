"""Os caches em disco: o que é gravado (JSON) e o que acontece com os arquivos do formato antigo.

Quatro arquivos antigos: ``playlist_cache.pkl``, ``partial_track_cache.pkl`` e ``.lyric_cache_data`` (em ``local_database/``,
tratados pelo ``BotPool.load_cache``) e ``.lastfm_cache`` (na raiz do diretório de dados, tratado pelo ``LastFM``). NENHUM é
lido: o cache recomeça vazio e o arquivo antigo fica onde está (o aviso da subida está em ``legacy_notice``). Só o cache de
playlist (``BotPool.cache_updater``) e o do Last.fm são GRAVADOS, em JSON (``playlist_cache.json`` e ``.lastfm_cache.json``); o
formato novo é testado em ``tests/serialization/test_cache_json.py``. Aqui ficam as fixtures compartilhadas.
"""

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
    async def test_o_cache_de_playlist_fica_em_local_database_e_a_pasta_e_criada(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1, 2, 3]
        await gravar_o_cache_de_playlist(pool)
        assert (tmp_path / "local_database" / "playlist_cache.json").is_file()


class TestArquivosAntigosNaoSaoLidos:
    """Cada arquivo antigo (de qualquer protocolo ou conteúdo) é ignorado: o cache recomeça vazio e o arquivo fica intacto."""

    @pytest.mark.parametrize(
        "conteudo", [pickle.dumps({PLAYLIST: RESPOSTA_DE_PLAYLIST}, protocol=5), b"", b"\x80\x09."]
    )
    def test_o_cache_antigo_do_bot_nao_e_carregado_nem_apagado(self, tmp_path, conteudo):
        caminhos = [pasta_dos_caches(tmp_path) / arquivo for arquivo, _ in ARQUIVOS_DE_CACHE]
        for caminho in caminhos:
            caminho.write_bytes(conteudo)
        pool = pool_vazio()
        pool.load_cache()
        assert all(len(getattr(pool, atributo)) == 0 for _, atributo in ARQUIVOS_DE_CACHE)
        assert all(caminho.read_bytes() == conteudo for caminho in caminhos)

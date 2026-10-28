"""F3-6b, etapa 6 (RED do Backend) — os caches de playlist e do Last.fm gravados e lidos em JSON.

* ``empiremuse/serialization/cache.py``: ``encode_cache`` e ``decode_cache`` (v1): ``{"v": 1, "saved_at": epoch, "items":
  [{"k": texto, "d": JSON}]}``; playlist até 64 MiB, Last.fm até 4 MiB; item inválido é DESCARTADO sozinho (cache não é dado do
  usuário) e o arquivo mais velho que o TTL não volta;
* ``empiremuse/utils/music/json_cache.py``: ``save_json_cache`` (atômico, 0600) e ``load_json_cache`` (nunca derruba);
* ``BotPool.cache_updater`` grava ``local_database/playlist_cache.json`` fora do laço de eventos e ``BotPool.load_cache`` o lê;
  ``LastFM`` grava e lê ``<runtime>/.lastfm_cache.json``; os arquivos ``.pkl`` e ``.lastfm_cache`` antigos não são lidos nem
  apagados;
* nenhuma gravação em ``pickle`` sobra nos caches.
"""

import ast
import importlib
import json
import stat
import time
from pathlib import Path

import pytest

from empiremuse.utils.music.lastfm_tools import LastFM
from tests.support.serializacao_nucleo import SEGREDO
from tests.support.serializacao_nucleo import TYPE, falha, vazamentos
from tests.persistence.test_formato_caches import (
    PLAYLIST,
    RESPOSTA_DE_PLAYLIST,
    gravar_o_cache_de_playlist,
    pasta_dos_caches,
    pool_vazio,
)
from tests.support.raiz import RAIZ

MIB = 1024 * 1024


class _Modulo:
    def __init__(self, nome):
        self._nome = nome

    def __getattr__(self, atributo):
        return getattr(importlib.import_module(self._nome), atributo)


cache = _Modulo("empiremuse.serialization.cache")
json_cache = _Modulo("empiremuse.utils.music.json_cache")


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


def caminho_playlist(tmp_path) -> Path:
    return tmp_path / "local_database" / "playlist_cache.json"


def caminho_lastfm(tmp_path) -> Path:
    return tmp_path / ".lastfm_cache.json"


def codificar(itens, **opcoes):
    opcoes.setdefault("max_bytes", 64 * MIB)
    return cache.encode_cache(itens, **opcoes)


def decodificar(raw, **opcoes):
    opcoes.setdefault("max_bytes", 64 * MIB)
    opcoes.setdefault("max_age", 1800)
    return cache.decode_cache(raw, **opcoes)


# ============================================================================ serialization/cache.py


class TestDecodificar:
    @pytest.mark.parametrize(
        "bruto",
        [b"[]", b'{"v":1,"saved_at":1,"items":{}}'],
    )
    def test_documento_sem_o_formato_e_recusado(self, bruto):
        assert falha(decodificar, bruto, now=1.0).code in {TYPE, "missing"}

    def test_item_ruim_do_arquivo_e_descartado_sozinho(self):
        itens = [
            {"k": "a", "d": 1},
            {"d": 2},
            {"k": 5, "d": 3},
            {"k": "sem-d"},
            "texto",
            {"k": "b", "d": [[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]},
            {"k": "c", "d": {"ok": True}},
        ]
        bruto = json.dumps({"v": 1, "saved_at": 100.0, "items": itens}).encode()
        assert decodificar(bruto, now=100.0) == {"a": 1, "c": {"ok": True}}

    def test_nada_do_conteudo_vaza_no_erro(self):
        bruto = f'{{"v":1,"saved_at":"{SEGREDO}","items":[]}}'.encode()
        assert not vazamentos(falha(decodificar, bruto, now=1.0))


# ============================================================================ utils/music/json_cache.py


class TestArquivoDeCache:
    def test_grava_atomico_e_privado_e_le_de_volta(self, tmp_path):
        alvo = tmp_path / "x" / "cache.json"
        json_cache.save_json_cache(alvo, [("a", 1), ("b", [2])], max_bytes=MIB)
        assert stat.S_IMODE(alvo.stat().st_mode) == 0o600 and [p.name for p in alvo.parent.iterdir()] == ["cache.json"]
        assert json_cache.load_json_cache(alvo, max_bytes=MIB, max_age=600) == {"a": 1, "b": [2]}


# ============================================================================ BotPool: cache de playlist


class TestCachePlaylist:
    @pytest.mark.asyncio
    async def test_o_cache_updater_grava_json_privado_e_nao_pickle(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        await gravar_o_cache_de_playlist(pool)
        arquivo = caminho_playlist(tmp_path)
        assert arquivo.is_file() and stat.S_IMODE(arquivo.stat().st_mode) == 0o600
        assert json.loads(arquivo.read_bytes())["items"] == [{"k": PLAYLIST, "d": RESPOSTA_DE_PLAYLIST}]
        assert not (pasta_dos_caches(tmp_path) / "playlist_cache.pkl").exists()
        assert [p.name for p in arquivo.parent.iterdir()] == ["playlist_cache.json"]

    @pytest.mark.asyncio
    async def test_o_reinicio_le_o_que_foi_gravado(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        await gravar_o_cache_de_playlist(pool)
        novo = pool_vazio()
        novo.load_cache()
        assert novo.playlist_cache.get(PLAYLIST) == RESPOSTA_DE_PLAYLIST
        assert not novo.partial_track_cache and not novo.lyric_data_cache
        assert caminho_playlist(tmp_path).is_file()


# ============================================================================ Last.fm


class TestCacheLastFM:
    ENTRADA = {"name": "Música", "artist": "Artista", "album": "Álbum"}

    def test_cache_velho_demais_nao_volta(self, tmp_path):
        json_cache.save_json_cache(
            caminho_lastfm(tmp_path), [("A - B", self.ENTRADA)], max_bytes=MIB, saved_at=time.time() - 3000
        )
        assert len(LastFM("chave", "segredo").cache) == 0

    @pytest.mark.parametrize("conteudo", [b"", b'{"v":9,"saved_at":1,"items":[]}'])
    def test_arquivo_ruim_nao_derruba_e_fica(self, tmp_path, conteudo):
        caminho_lastfm(tmp_path).write_bytes(conteudo)
        assert len(LastFM("chave", "segredo").cache) == 0 and caminho_lastfm(tmp_path).read_bytes() == conteudo


# ============================================================================ arquitetura e infra

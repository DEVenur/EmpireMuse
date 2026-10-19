"""F3-6b, etapa 6 (RED do Backend) — os caches de playlist e do Last.fm gravados e lidos em JSON.

* ``empiremuse/serialization/cache.py``: ``encode_cache`` e ``decode_cache`` (v1): ``{"v": 1, "saved_at": epoch, "items":
  [{"k": texto, "d": JSON}]}``; playlist até 64 MiB, Last.fm até 4 MiB; item inválido é DESCARTADO sozinho (cache não é dado do
  usuário) e o arquivo mais velho que o TTL não volta;
* ``empiremuse/utils/music/json_cache.py``: ``save_json_cache`` (atômico, 0600) e ``load_json_cache`` (nunca derruba);
* ``BotPool.cache_updater`` grava ``local_database/playlist_cache.json`` fora do laço de eventos e ``BotPool.load_cache`` o lê;
  ``LastFM`` grava e lê ``<runtime>/.lastfm_cache.json``; os arquivos ``.pkl`` e ``.lastfm_cache`` antigos continuam sendo
  apagados sem abrir (2b);
* nenhuma gravação em ``pickle`` sobra nos caches.
"""

import ast
import importlib
import json
import logging
import stat
import threading
import time
from pathlib import Path

import pytest
from cachetools import TTLCache

from empiremuse.utils import client
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import (
    NOT_FINITE,
    SYNTAX,
    TOO_BIG,
    TYPE,
    VERSION,
    falha,
    vazamentos,
)
from tests.test_f3_6b_formato_caches import (
    PLAYLIST,
    RESPOSTA_DE_PLAYLIST,
    gravar_o_cache_de_playlist,
    pasta_dos_caches,
    pool_vazio,
)

MIB = 1024 * 1024
RAIZ = Path(__file__).resolve().parents[1]


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


class TestCodificar:
    def test_o_documento_tem_versao_instante_e_itens(self):
        bruto = json.loads(codificar([(PLAYLIST, RESPOSTA_DE_PLAYLIST), ("b", [1, None, True])], saved_at=1234.5))
        assert bruto == {
            "v": 1,
            "saved_at": 1234.5,
            "items": [{"k": PLAYLIST, "d": RESPOSTA_DE_PLAYLIST}, {"k": "b", "d": [1, None, True]}],
        }

    def test_o_instante_padrao_e_agora(self):
        antes = time.time()
        assert antes <= json.loads(codificar([("a", 1)]))["saved_at"] <= time.time()

    def test_sem_itens_gera_documento_valido(self):
        assert decodificar(codificar([]), now=time.time()) == {}

    def test_e_json_compacto_utf8(self):
        bruto = codificar([("música", {"t": "Álbum 😀"})])
        assert bruto[:1] == b"{" and b": " not in bruto and "Álbum 😀".encode() in bruto

    @pytest.mark.parametrize(
        "ruim",
        [b"x", (1, 2), {1, 2}, float("nan"), float("inf"), {"a": b"x"}, {1: "chave inteira"}, "ruim\ud800", object()],
        ids=lambda v: type(v).__name__,
    )
    def test_item_com_valor_invalido_e_descartado_e_os_outros_ficam(self, ruim):
        itens = [("a", 1), ("ruim", ruim), ("c", [2])]
        assert decodificar(codificar(itens), now=time.time()) == {"a": 1, "c": [2]}

    @pytest.mark.parametrize("chave", [1, None, b"k", ("a",), "k" * 513, "ruim\ud800"], ids=lambda v: type(v).__name__)
    def test_item_com_chave_invalida_e_descartado(self, chave):
        assert decodificar(codificar([("a", 1), (chave, 2)]), now=time.time()) == {"a": 1}

    def test_item_fundo_demais_e_descartado(self):
        fundo = 0
        for _ in range(40):
            fundo = [fundo]
        assert decodificar(codificar([("fundo", fundo), ("a", 1)]), now=time.time()) == {"a": 1}

    def test_o_teto_de_bytes_corta_os_itens_que_nao_cabem_e_nunca_passa_dele(self):
        itens = [(f"k{i}", "x" * 1000) for i in range(50)]
        bruto = codificar(itens, max_bytes=10_000)
        assert len(bruto) <= 10_000
        lidos = decodificar(bruto, max_bytes=10_000, now=time.time())
        assert 0 < len(lidos) < 50 and list(lidos) == [f"k{i}" for i in range(len(lidos))]

    def test_nao_altera_os_valores(self):
        valor = {"a": [1, {"b": 2}]}
        codificar([("k", valor)])
        assert valor == {"a": [1, {"b": 2}]}


class TestDecodificar:
    def test_ida_e_volta_na_mesma_ordem(self):
        itens = [(f"k{i}", {"i": i}) for i in range(20)]
        assert list(decodificar(codificar(itens), now=time.time()).items()) == itens

    def test_cache_mais_velho_que_o_ttl_nao_volta(self):
        raw = codificar([("a", 1)], saved_at=1000.0)
        assert decodificar(raw, max_age=1800, now=1000.0 + 1799) == {"a": 1}
        assert decodificar(raw, max_age=1800, now=1000.0 + 1800) == {}

    def test_instante_no_futuro_nao_volta(self):
        raw = codificar([("a", 1)], saved_at=10_000.0)
        assert decodificar(raw, now=5_000.0) == {}

    @pytest.mark.parametrize("v", [0, 2, "1", True, None])
    def test_versao_invalida_ou_futura_e_recusada(self, v):
        bruto = json.loads(codificar([("a", 1)]))
        bruto["v"] = v
        assert falha(decodificar, json.dumps(bruto).encode(), now=time.time()).code == VERSION

    def test_o_teto_de_bytes_vale_antes_de_decodificar(self):
        assert falha(decodificar, b" " * 5000, max_bytes=4096, now=time.time()).code == TOO_BIG

    def test_json_mal_formado_e_literal_nao_finito_sao_recusados(self):
        assert falha(decodificar, b"{", now=time.time()).code == SYNTAX
        assert falha(decodificar, b'{"v":1,"saved_at":NaN,"items":[]}', now=time.time()).code == NOT_FINITE

    @pytest.mark.parametrize(
        "bruto",
        [b"[]", b'{"v":1,"items":[]}', b'{"v":1,"saved_at":"x","items":[]}', b'{"v":1,"saved_at":1,"items":{}}'],
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

    def test_arquivo_ausente_da_cache_vazio_e_nao_cria_nada(self, tmp_path):
        assert json_cache.load_json_cache(tmp_path / "nada.json", max_bytes=MIB, max_age=600) == {}
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("conteudo", [b"", b"{", b"\xff\xfe", b"[]", b"conteudo de qualquer coisa"])
    def test_arquivo_ilegivel_da_cache_vazio_avisa_sem_o_conteudo_e_fica(self, tmp_path, caplog, conteudo):
        alvo = tmp_path / "cache.json"
        alvo.write_bytes(conteudo)
        with caplog.at_level(logging.DEBUG):
            assert json_cache.load_json_cache(alvo, max_bytes=MIB, max_age=600) == {}
        assert alvo.read_bytes() == conteudo and all(SEGREDO not in r.getMessage() for r in caplog.records)

    def test_arquivo_enorme_e_recusado_sem_ser_lido_inteiro(self, tmp_path):
        alvo = tmp_path / "cache.json"
        with open(alvo, "wb") as f:
            f.truncate(300 * MIB)
        inicio = time.perf_counter()
        assert json_cache.load_json_cache(alvo, max_bytes=4 * MIB, max_age=600) == {}
        assert time.perf_counter() - inicio < 2.0

    def test_falha_ao_gravar_levanta_oserror_e_deixa_o_arquivo_anterior(self, tmp_path, monkeypatch):
        alvo = tmp_path / "cache.json"
        json_cache.save_json_cache(alvo, [("a", 1)], max_bytes=MIB)
        antes = alvo.read_bytes()
        files = importlib.import_module("empiremuse.serialization.files")

        def negar(*args, **kwargs):
            raise OSError("negado")

        monkeypatch.setattr(files.os, "replace", negar)
        with pytest.raises(OSError):
            json_cache.save_json_cache(alvo, [("b", 2)], max_bytes=MIB)
        assert alvo.read_bytes() == antes


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
    async def test_a_gravacao_roda_fora_do_laco_de_eventos(self, tmp_path, monkeypatch):
        threads = []
        original = client.save_json_cache

        def espiao(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(client, "save_json_cache", espiao)
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1]
        await gravar_o_cache_de_playlist(pool)
        assert threads and threads[0] != threading.get_ident()

    @pytest.mark.asyncio
    async def test_item_que_nao_e_json_e_descartado_e_o_resto_e_gravado(self, tmp_path):
        pool = pool_vazio()
        pool.playlist_cache["bom"] = [1]
        pool.playlist_cache["ruim"] = {"b": b"bytes"}
        await gravar_o_cache_de_playlist(pool)
        assert [i["k"] for i in json.loads(caminho_playlist(tmp_path).read_bytes())["items"]] == ["bom"]

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

    def test_cache_gravado_ha_mais_que_o_ttl_nao_volta(self, tmp_path):
        alvo = caminho_playlist(tmp_path)
        json_cache.save_json_cache(alvo, [("k", [1])], max_bytes=MIB, saved_at=time.time() - 4000)
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0

    @pytest.mark.parametrize("conteudo", [b"", b"{", b"[]", b"lixo", b'{"v":9,"saved_at":1,"items":[]}'])
    def test_arquivo_ruim_nao_derruba_a_inicializacao(self, tmp_path, conteudo):
        alvo = caminho_playlist(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(conteudo)
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0 and alvo.read_bytes() == conteudo

    def test_o_json_e_o_pkl_antigo_convivem_o_pkl_e_apagado_sem_abrir(self, tmp_path):
        json_cache.save_json_cache(caminho_playlist(tmp_path), [("k", [1])], max_bytes=MIB)
        antigo = pasta_dos_caches(tmp_path) / "playlist_cache.pkl"
        antigo.write_bytes(b"qualquer coisa")
        pool = pool_vazio()
        pool.load_cache()
        assert pool.playlist_cache.get("k") == [1] and not antigo.exists()

    def test_o_cache_carregado_respeita_o_tamanho_maximo_do_ttlcache(self, tmp_path):
        json_cache.save_json_cache(caminho_playlist(tmp_path), [(f"k{i}", i) for i in range(30)], max_bytes=MIB)
        pool = pool_vazio()
        pool.playlist_cache = TTLCache(maxsize=10, ttl=1800)
        pool.load_cache()
        assert len(pool.playlist_cache) == 10

    def test_o_teto_do_arquivo_de_playlist_e_64_mib_e_o_do_lastfm_4_mib(self):
        assert cache.PLAYLIST_MAX_BYTES == 64 * MIB and cache.LASTFM_MAX_BYTES == 4 * MIB


# ============================================================================ Last.fm


class TestCacheLastFM:
    ENTRADA = {"name": "Música", "artist": "Artista", "album": "Álbum"}

    def test_grava_json_privado_na_raiz_sincrono_e_nao_pickle(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["Artista - Música"] = self.ENTRADA
        lastfm.cache["Sem Resultado - X"] = {}
        lastfm.scrobble_save_cache()
        arquivo = caminho_lastfm(tmp_path)
        assert arquivo.is_file() and stat.S_IMODE(arquivo.stat().st_mode) == 0o600
        assert not (tmp_path / ".lastfm_cache").exists() and not (tmp_path / "local_database").exists()
        itens = json.loads(arquivo.read_bytes())["items"]
        assert itens == [{"k": "Artista - Música", "d": self.ENTRADA}, {"k": "Sem Resultado - X", "d": {}}]

    def test_o_reinicio_le_o_que_foi_gravado(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["Artista - Música"] = self.ENTRADA
        lastfm.cache["Sem Resultado - X"] = {}
        lastfm.scrobble_save_cache()
        assert dict(LastFM("chave", "segredo").cache) == {"Artista - Música": self.ENTRADA, "Sem Resultado - X": {}}

    def test_cache_velho_demais_nao_volta(self, tmp_path):
        json_cache.save_json_cache(
            caminho_lastfm(tmp_path), [("A - B", self.ENTRADA)], max_bytes=MIB, saved_at=time.time() - 3000
        )
        assert len(LastFM("chave", "segredo").cache) == 0

    @pytest.mark.parametrize("conteudo", [b"", b"{", b"[]", b"lixo", b'{"v":9,"saved_at":1,"items":[]}'])
    def test_arquivo_ruim_nao_derruba_e_fica(self, tmp_path, conteudo):
        caminho_lastfm(tmp_path).write_bytes(conteudo)
        assert len(LastFM("chave", "segredo").cache) == 0 and caminho_lastfm(tmp_path).read_bytes() == conteudo

    def test_valor_que_nao_e_dicionario_e_descartado(self, tmp_path):
        json_cache.save_json_cache(
            caminho_lastfm(tmp_path), [("bom", self.ENTRADA), ("lista", [1]), ("numero", 5)], max_bytes=MIB
        )
        assert list(LastFM("chave", "segredo").cache) == ["bom"]

    def test_o_pickle_antigo_continua_sendo_apagado_sem_abrir(self, tmp_path):
        antigo = tmp_path / ".lastfm_cache"
        antigo.write_bytes(b"qualquer coisa")
        json_cache.save_json_cache(caminho_lastfm(tmp_path), [("A - B", self.ENTRADA)], max_bytes=MIB)
        assert "A - B" in LastFM("chave", "segredo").cache and not antigo.exists()

    def test_a_gravacao_continua_sincrona(self):
        import asyncio

        assert not asyncio.iscoroutinefunction(LastFM.scrobble_save_cache)


# ============================================================================ arquitetura e infra


class TestSemPickleNosCaches:
    @pytest.mark.parametrize("arquivo", ["utils/client.py", "utils/music/lastfm_tools.py", "utils/music/json_cache.py"])
    def test_os_modulos_dos_caches_nao_importam_pickle(self, arquivo):
        arvore = ast.parse((RAIZ / "empiremuse" / arquivo).read_text(encoding="utf-8"))
        importados = {
            alias.name.split(".")[0] for no in ast.walk(arvore) if isinstance(no, ast.Import) for alias in no.names
        }
        importados |= {(no.module or "").split(".")[0] for no in ast.walk(arvore) if isinstance(no, ast.ImportFrom)}
        assert not importados & {"pickle", "_pickle", "cPickle"}

    def test_o_novo_nome_do_cache_do_lastfm_nao_e_versionado_nem_vai_para_a_imagem(self):
        for nome in (".gitignore", ".dockerignore"):
            linhas = [linha.strip() for linha in (RAIZ / nome).read_text(encoding="utf-8").splitlines()]
            assert any(linha.endswith(".lastfm_cache.json") for linha in linhas), nome

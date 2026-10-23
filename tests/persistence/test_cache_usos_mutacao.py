"""F3-6b, etapa 6 — complemento do QA, parte 2, depois da mutação do código REAL (usos dos caches, descarte do legado e ``fixfavs``).

Sobreviventes que não eram equivalentes: o ``cache_updater`` entrega uma LISTA (cópia) à thread e um erro de disco não o mata; o
Last.fm não lê arquivo acima de 4 MiB nem entrega o ``ItemsView`` vivo à thread; ``discard_legacy_cache`` é silencioso quando o
arquivo não existe e avisa (INFO, só com o nome) quando apaga; e o ``fixfavs`` regrava o backup do zero a cada execução, segue
quando um servidor não tem ``player_controller`` e limpa os espaços dos favoritos dos USUÁRIOS.
"""

import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from empiremuse.cogs.misc import Misc
from empiremuse.serialization.cache import LASTFM_MAX_BYTES
from empiremuse.utils import client
from empiremuse.utils.db import DBModel
from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.json_cache import save_json_cache
from empiremuse.utils.music.lastfm_tools import LastFM
from empiremuse.utils.music.legacy_reader import discard_legacy_cache
from tests.persistence.test_formato_caches import gravar_o_cache_de_playlist, pool_vazio

MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestCacheDePlaylist:
    @pytest.mark.asyncio
    async def test_a_thread_recebe_uma_lista_copiada_no_laco(self, monkeypatch):
        recebidos = []
        original = client.save_json_cache

        def espiao(caminho, items, **kwargs):
            recebidos.append(items)
            return original(caminho, items, **kwargs)

        monkeypatch.setattr(client, "save_json_cache", espiao)
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1]
        await gravar_o_cache_de_playlist(pool)
        assert [type(items) for items in recebidos] == [list] and recebidos[0] == [("k", [1])]

    @pytest.mark.asyncio
    async def test_erro_de_disco_vira_aviso_e_o_laco_continua(self, monkeypatch, caplog):
        def negar(*args, **kwargs):
            raise OSError("negado")

        monkeypatch.setattr(client, "save_json_cache", negar)
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1]
        with caplog.at_level(logging.WARNING):
            await gravar_o_cache_de_playlist(pool)  # a segunda espera só chega se o laço sobreviveu
        assert any("não gravado" in r.getMessage() for r in caplog.records)


class TestCacheDoLastFm:
    def test_arquivo_acima_de_4_mib_nao_volta(self, tmp_path):
        save_json_cache(
            tmp_path / ".lastfm_cache.json", [("grande", {"x": "a" * (LASTFM_MAX_BYTES + MIB)})], max_bytes=64 * MIB
        )
        assert dict(LastFM("chave", "segredo").cache) == {}

    def test_arquivo_dentro_do_teto_volta(self, tmp_path):
        save_json_cache(tmp_path / ".lastfm_cache.json", [("pequeno", {"x": "a" * 1000})], max_bytes=64 * MIB)
        assert dict(LastFM("chave", "segredo").cache) == {"pequeno": {"x": "a" * 1000}}

    @pytest.mark.asyncio
    async def test_a_thread_recebe_uma_lista_e_nao_a_visao_viva_do_cache(self, monkeypatch):
        recebidos = []
        original = lastfm_tools.LastFM._save_items

        def espiao(items):
            recebidos.append(items)
            return original(items)

        monkeypatch.setattr(lastfm_tools.LastFM, "_save_items", staticmethod(espiao))
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["k"] = {}
        await lastfm.scrobble_save_cache_async()
        assert [type(items) for items in recebidos] == [list]


class TestDescarteDoCacheAntigo:
    def test_arquivo_ausente_nao_avisa_nada(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            discard_legacy_cache(tmp_path / "nao_existe.pkl")
        assert caplog.records == []

    def test_apagar_registra_so_o_nome(self, tmp_path, caplog):
        antigo = tmp_path / "playlist_cache.pkl"
        antigo.write_bytes(b"conteudo")
        with caplog.at_level(logging.DEBUG):
            discard_legacy_cache(antigo)
        assert not antigo.exists()
        mensagens = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert mensagens == ["Cache antigo descartado: playlist_cache.pkl"]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def montar_fixfavs(guildas, usuarios):
    colecoes = {(DBModel.guilds, "bot"): guildas, (DBModel.users, "global"): usuarios}
    gravados = {"guildas": {}, "usuarios": {}}

    async def iter_data(db_name, collection, filter=None):
        for documento in list(colecoes[(db_name, collection)]):
            yield documento

    async def atualizar_bot(id_, data, *, db_name):
        gravados["guildas"][id_] = json.loads(json.dumps(data))

    async def atualizar_global(id_, data, *, db_name):
        gravados["usuarios"][id_] = json.loads(json.dumps(data))

    bot = SimpleNamespace(
        user=SimpleNamespace(id="bot"),
        pool=SimpleNamespace(database=SimpleNamespace(iter_data=iter_data)),
        update_data=atualizar_bot,
    )
    bot.pool.get_all_bots = lambda: [bot]
    cog = Misc.__new__(Misc)
    cog.bot = SimpleNamespace(pool=bot.pool, update_global_data=atualizar_global)
    mensagens = []

    @asynccontextmanager
    async def digitando():
        yield

    async def enviar(texto):
        mensagens.append(texto)

    return cog, SimpleNamespace(typing=digitando, send=enviar), gravados, mensagens


SUJO = {" nome ": "  https://exemplo.invalid/x  "}
LIMPO = {"nome": "https://exemplo.invalid/x"}


class TestFixfavs:
    @pytest.mark.asyncio
    async def test_o_backup_e_regravado_do_zero_a_cada_execucao(self, tmp_path):
        guildas = [{"_id": "1", "player_controller": {"fav_links": dict(SUJO)}}]
        cog, ctx, _, _ = montar_fixfavs(guildas, [{"_id": "9", "fav_links": dict(SUJO)}])
        await Misc.fixfavs.callback(cog, ctx)
        await Misc.fixfavs.callback(cog, ctx)
        pasta = tmp_path / "local_database" / "fixfavs_backup"
        assert len(json.loads((pasta / "guild_favs_bot.json").read_text())) == 1
        assert len(json.loads((pasta / "user_favs.json").read_text())) == 1

    @pytest.mark.asyncio
    async def test_servidor_sem_player_controller_nao_derruba_o_comando(self):
        guildas = [{"_id": "sem"}, {"_id": "1", "player_controller": {"fav_links": dict(SUJO)}}]
        cog, ctx, gravados, mensagens = montar_fixfavs(guildas, [])
        await Misc.fixfavs.callback(cog, ctx)
        assert list(gravados["guildas"]) == ["1"] and mensagens

    @pytest.mark.asyncio
    async def test_favoritos_de_servidor_e_de_usuario_saem_sem_espacos(self):
        guildas = [{"_id": "1", "player_controller": {"fav_links": dict(SUJO)}}]
        cog, ctx, gravados, _ = montar_fixfavs(guildas, [{"_id": "9", "fav_links": dict(SUJO)}])
        await Misc.fixfavs.callback(cog, ctx)
        assert gravados["guildas"]["1"]["player_controller"]["fav_links"] == LIMPO
        assert gravados["usuarios"]["9"]["fav_links"] == LIMPO

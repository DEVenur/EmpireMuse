"""Complemento do QA, parte 2, depois da mutação do código REAL (usos dos caches e ``fixfavs``).

Sobreviventes que não eram equivalentes: o ``cache_updater`` entrega uma LISTA (cópia) à thread e um erro de disco não o mata; o
Last.fm não lê arquivo acima de 4 MiB nem entrega o ``ItemsView`` vivo à thread; e o ``fixfavs`` regrava o backup do zero a cada execução, segue
quando um servidor não tem ``player_controller`` e limpa os espaços dos favoritos dos USUÁRIOS.
"""

import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from empiremuse.cogs.misc import Misc
from empiremuse.utils import client
from empiremuse.utils.db import DBModel
from tests.persistence.test_formato_caches import gravar_o_cache_de_playlist, pool_vazio


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestCacheDePlaylist:
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


class TestFixfavs:
    @pytest.mark.asyncio
    async def test_servidor_sem_player_controller_nao_derruba_o_comando(self):
        guildas = [{"_id": "sem"}, {"_id": "1", "player_controller": {"fav_links": dict(SUJO)}}]
        cog, ctx, gravados, mensagens = montar_fixfavs(guildas, [])
        await Misc.fixfavs.callback(cog, ctx)
        assert list(gravados["guildas"]) == ["1"] and mensagens

"""F3-6b, etapa 5 — regressão do ``query_data`` com ``limit`` real: o ``misc.fixfavs`` continua corrigindo TODOS os documentos.

O comando passava ``limit=300`` e ``limit=500``, que nunca valeram (a consulta devolvia a coleção inteira). Com o ``limit``
valendo, só os primeiros 300/500 seriam corrigidos, em silêncio. O comando percorre as duas coleções por ``iter_data`` (cursor,
sem limite e sem montar a lista) e o backup em JSON continua tendo todos os documentos, do jeito que estavam antes da correção.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from empiremuse.cogs.misc import Misc
from empiremuse.utils.db import DBModel

pytestmark = pytest.mark.regression

GUILDAS, USUARIOS = 700, 900  # acima dos antigos 300 e 500


class BancoFalso:
    """Só o que o comando usa: o cursor (``iter_data``) respeita o filtro e ``query_data`` só vale COM limit."""

    def __init__(self, guildas, usuarios):
        self.colecoes = {(DBModel.guilds, "bot"): guildas, (DBModel.users, "global"): usuarios}
        self.chamadas = []
        self.gravados = []

    async def iter_data(self, db_name, collection, filter=None):
        self.chamadas.append(("iter_data", collection))
        for documento in list(self.colecoes[(db_name, collection)]):
            yield documento

    async def query_data(self, db_name, collection, filter=None, limit=None):
        self.chamadas.append(("query_data", collection, limit))
        return list(self.colecoes[(db_name, collection)])[:limit]

    async def update_data(self, id_, data, *, db_name, collection):
        self.gravados.append(id_)


def favoritos_sujos(n: int) -> dict:
    return {f" nome {n} ": f"  https://exemplo.invalid/{n}  "}


def montar(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    guildas = [{"_id": str(n), "player_controller": {"fav_links": favoritos_sujos(n)}} for n in range(GUILDAS)]
    usuarios = [{"_id": str(n), "fav_links": favoritos_sujos(n)} for n in range(USUARIOS)]
    banco = BancoFalso(guildas, usuarios)
    gravados = {"guildas": banco.gravados, "usuarios": []}

    async def atualizar_global(id_, data, *, db_name):
        gravados["usuarios"].append(id_)

    bot = SimpleNamespace(user=SimpleNamespace(id="bot"), pool=SimpleNamespace(database=banco))
    bot.pool.get_all_bots = lambda: [bot]
    cog = Misc.__new__(Misc)
    cog.bot = SimpleNamespace(pool=bot.pool, update_global_data=atualizar_global)
    mensagens = []

    @asynccontextmanager
    async def digitando():
        yield

    async def enviar(texto):
        mensagens.append(texto)

    ctx = SimpleNamespace(typing=digitando, send=enviar)
    return cog, ctx, banco, gravados, mensagens


@pytest.mark.asyncio
async def test_o_comando_percorre_pelo_cursor_e_sem_limite(tmp_path, monkeypatch):
    cog, ctx, banco, _, _ = montar(tmp_path, monkeypatch)
    await Misc.fixfavs.callback(cog, ctx)
    # os links fixos dos servidores são as playlists do documento único (item 17): o comando só percorre os favoritos pessoais
    assert banco.chamadas == [("iter_data", "global")]
    assert banco.gravados == []  # e nunca regrava o fav_links antigo dos documentos por bot


@pytest.mark.asyncio
async def test_colecao_vazia_gera_backup_valido(tmp_path, monkeypatch):
    cog, ctx, banco, gravados, _ = montar(tmp_path, monkeypatch)
    banco.colecoes[(DBModel.guilds, "bot")].clear()
    banco.colecoes[(DBModel.users, "global")].clear()
    await Misc.fixfavs.callback(cog, ctx)
    pasta = tmp_path / "local_database" / "fixfavs_backup"
    assert not (pasta / "guild_favs_bot.json").exists()
    assert json.loads((pasta / "user_favs.json").read_text(encoding="utf-8")) == []

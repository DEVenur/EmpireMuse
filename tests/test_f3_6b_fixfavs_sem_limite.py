"""F3-6b, etapa 5 — regressão do ``query_data`` com ``limit`` real: o ``misc.fixfavs`` continua corrigindo TODOS os documentos.

O comando passava ``limit=300`` e ``limit=500``, que nunca valeram (a consulta devolvia a coleção inteira). Com o ``limit``
valendo, só os primeiros 300/500 seriam corrigidos, em silêncio. O comando percorre as duas coleções por ``iter_data`` (cursor,
sem limite e sem montar a lista) e o backup em JSON continua tendo todos os documentos, do jeito que estavam antes da correção.
"""

import ast
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from empiremuse.cogs.misc import Misc
from empiremuse.utils.db import DBModel

RAIZ = Path(__file__).resolve().parents[1]
GUILDAS, USUARIOS = 700, 900  # acima dos antigos 300 e 500


class BancoFalso:
    """Só o que o comando usa: o cursor (``iter_data``) respeita o filtro e ``query_data`` só vale COM limit."""

    def __init__(self, guildas, usuarios):
        self.colecoes = {(DBModel.guilds, "bot"): guildas, (DBModel.users, "global"): usuarios}
        self.chamadas = []

    async def iter_data(self, db_name, collection, filter=None):
        self.chamadas.append(("iter_data", collection))
        for documento in list(self.colecoes[(db_name, collection)]):
            yield documento

    async def query_data(self, db_name, collection, filter=None, limit=None):
        self.chamadas.append(("query_data", collection, limit))
        return list(self.colecoes[(db_name, collection)])[:limit]


def favoritos_sujos(n: int) -> dict:
    return {f" nome {n} ": f"  https://exemplo.invalid/{n}  "}


def montar(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    guildas = [{"_id": str(n), "player_controller": {"fav_links": favoritos_sujos(n)}} for n in range(GUILDAS)]
    usuarios = [{"_id": str(n), "fav_links": favoritos_sujos(n)} for n in range(USUARIOS)]
    banco = BancoFalso(guildas, usuarios)
    gravados = {"guildas": [], "usuarios": []}

    async def atualizar_bot(id_, data, *, db_name):
        gravados["guildas"].append(id_)

    async def atualizar_global(id_, data, *, db_name):
        gravados["usuarios"].append(id_)

    bot = SimpleNamespace(
        user=SimpleNamespace(id="bot"), pool=SimpleNamespace(database=banco), update_data=atualizar_bot
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

    ctx = SimpleNamespace(typing=digitando, send=enviar)
    return cog, ctx, banco, gravados, mensagens


@pytest.mark.asyncio
async def test_todos_os_documentos_sao_corrigidos_mesmo_acima_dos_antigos_limites(tmp_path, monkeypatch):
    cog, ctx, banco, gravados, mensagens = montar(tmp_path, monkeypatch)
    await Misc.fixfavs.callback(cog, ctx)
    assert len(gravados["guildas"]) == GUILDAS and len(gravados["usuarios"]) == USUARIOS
    assert sorted(gravados["usuarios"], key=int) == [str(n) for n in range(USUARIOS)]
    guildas = banco.colecoes[(DBModel.guilds, "bot")]
    assert all(
        g["player_controller"]["fav_links"] == {f"nome {n}": f"https://exemplo.invalid/{n}"}
        for n, g in enumerate(guildas)
    )
    assert mensagens and "corrigidos" in mensagens[0]


@pytest.mark.asyncio
async def test_o_comando_percorre_pelo_cursor_e_sem_limite(tmp_path, monkeypatch):
    cog, ctx, banco, _, _ = montar(tmp_path, monkeypatch)
    await Misc.fixfavs.callback(cog, ctx)
    assert banco.chamadas == [("iter_data", "bot"), ("iter_data", "global")]


@pytest.mark.asyncio
async def test_o_backup_tem_todos_os_documentos_como_estavam_antes_da_correcao(tmp_path, monkeypatch):
    cog, ctx, banco, _, _ = montar(tmp_path, monkeypatch)
    await Misc.fixfavs.callback(cog, ctx)
    pasta = tmp_path / "local_database" / "fixfavs_backup"
    guildas = json.loads((pasta / "guild_favs_bot.json").read_text(encoding="utf-8"))
    usuarios = json.loads((pasta / "user_favs.json").read_text(encoding="utf-8"))
    assert len(guildas) == GUILDAS and len(usuarios) == USUARIOS
    assert guildas[5]["player_controller"]["fav_links"] == favoritos_sujos(5)
    assert usuarios[800]["fav_links"] == favoritos_sujos(800)


@pytest.mark.asyncio
async def test_colecao_vazia_gera_backup_valido(tmp_path, monkeypatch):
    cog, ctx, banco, gravados, _ = montar(tmp_path, monkeypatch)
    banco.colecoes[(DBModel.guilds, "bot")].clear()
    banco.colecoes[(DBModel.users, "global")].clear()
    await Misc.fixfavs.callback(cog, ctx)
    pasta = tmp_path / "local_database" / "fixfavs_backup"
    assert json.loads((pasta / "guild_favs_bot.json").read_text(encoding="utf-8")) == []
    assert json.loads((pasta / "user_favs.json").read_text(encoding="utf-8")) == []


def test_nenhuma_chamada_do_misc_passa_limit_ao_query_data():
    arvore = ast.parse((RAIZ / "empiremuse" / "cogs" / "misc.py").read_text(encoding="utf-8"))
    chamadas = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "query_data"
    ]
    assert all("limit" not in {k.arg for k in no.keywords} for no in chamadas)

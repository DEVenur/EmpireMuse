"""Regressão: o ``/play`` lia o documento do servidor com o id do AUTOR (``play_command.py:259``), então a configuração do
servidor (DJ, modo restrito, canal de pedidos) era a de um servidor que não existe, ou a de outro."""

from types import SimpleNamespace

import pytest

from empiremuse.music_cog.play_command import PlayCommandMixin
from empiremuse.utils.db import DBModel

pytestmark = pytest.mark.regression

GUILD_ID, AUTHOR_ID = 111, 999


@pytest.mark.asyncio
async def test_play_reads_the_server_document_not_the_authors():
    pedidos = []

    async def get_data(id_, *, db_name):
        pedidos.append((id_, db_name))
        return {"_id": id_}

    bot = SimpleNamespace(get_data=get_data)
    inter = SimpleNamespace(
        bot=bot,
        guild=SimpleNamespace(id=GUILD_ID),
        author=SimpleNamespace(id=AUTHOR_ID),
        response=SimpleNamespace(is_done=lambda: True),  # sem adiar a resposta: só importa a leitura
    )
    req = SimpleNamespace(inter=inter, mix=False)

    await PlayCommandMixin._play_prepare(SimpleNamespace(), req)

    assert pedidos == [(GUILD_ID, DBModel.guilds)]
    assert req.guild_data == {"_id": GUILD_ID}

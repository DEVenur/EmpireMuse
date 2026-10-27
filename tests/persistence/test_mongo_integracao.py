"""A16 — ``MongoDatabase`` contra um ``mongo:8`` real, local e descartável.

Só roda com ``MONGO_TEST_URI`` apontando para localhost; sem a variável é pulado. Nunca lê ``MONGO`` nem o ``.env``: o banco
``global`` de produção guarda refresh tokens. O mongod sobe e fica pronto antes do pytest (gate); aqui não há espera por tempo.
Tudo roda num banco com nome único, apagado no fim.
"""

import asyncio
import os
import uuid
from urllib.parse import urlparse

import pytest

from empiremuse.utils import db
from empiremuse.utils.db import DBModel, MongoDatabase

pytestmark = pytest.mark.integration

URI = os.environ.get("MONGO_TEST_URI", "")
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}

if not URI:
    pytest.skip("MONGO_TEST_URI ausente: sem mongod descartável", allow_module_level=True)

if urlparse(URI).hostname not in HOSTS_LOCAIS:
    pytest.fail("MONGO_TEST_URI precisa apontar para localhost", pytrace=False)


async def _ciclo():
    banco = MongoDatabase(URI, timeout=5)
    nome = f"litmus_{uuid.uuid4().hex}"
    versao = db.db_models[DBModel.guilds]["ver"]
    try:
        # sem documento: o padrão, sem inserir
        assert (await banco.get_data(1, db_name=DBModel.guilds, collection=nome))["ver"] == versao
        assert await banco.query_data(DBModel.guilds, nome) == []

        # push
        await banco.push_data({"_id": "2", "ver": versao, "autoplay": True}, db_name=DBModel.guilds, collection=nome)
        banco.cache.clear()
        assert (await banco.get_data(2, db_name=DBModel.guilds, collection=nome))["autoplay"] is True

        # migração por versão: salva de volta já na versão nova, preservando o valor gravado
        await banco.push_data({"_id": "3", "ver": 0.5, "djroles": ["4"]}, db_name=DBModel.guilds, collection=nome)
        migrado = await banco.get_data(3, db_name=DBModel.guilds, collection=nome)
        assert migrado["ver"] == versao and migrado["djroles"] == ["4"]
        banco.cache.clear()
        assert (await banco._connect[nome][DBModel.guilds].find_one({"_id": "3"}))["ver"] == versao

        # update com upsert (documento novo) e sobre o existente
        await banco.update_data(5, {"x": 1, "ver": versao}, db_name=DBModel.guilds, collection=nome)
        await banco.update_data(5, {"x": 2}, db_name=DBModel.guilds, collection=nome)
        assert (await banco._connect[nome][DBModel.guilds].find_one({"_id": "5"}))["x"] == 2

        # query com e sem limit, filtro e iter
        todos = await banco.query_data(DBModel.guilds, nome)
        assert sorted(d["_id"] for d in todos) == ["2", "3", "5"]
        assert len(await banco.query_data(DBModel.guilds, nome, limit=2)) == 2
        assert [d["_id"] for d in await banco.query_data(DBModel.guilds, nome, {"x": 2})] == ["5"]
        assert sorted([d["_id"] async for d in banco.iter_data(DBModel.guilds, nome)]) == ["2", "3", "5"]

        # delete invalida o cache
        banco.cache[f"{nome}:{DBModel.guilds}:2"] = {"velho": True}
        await banco.delete_data(2, DBModel.guilds, nome)
        assert f"{nome}:{DBModel.guilds}:2" not in banco.cache
        assert await banco._connect[nome][DBModel.guilds].find_one({"_id": "2"}) is None
    finally:
        await banco._connect.drop_database(nome)
        await banco._connect.close()


def test_mongo_database_round_trip_against_a_real_mongod():
    asyncio.run(_ciclo())

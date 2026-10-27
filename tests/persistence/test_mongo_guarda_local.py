"""A guarda do teste de integração (A16) recusa qualquer URI que possa alcançar um mongod que não seja local. Sem rede."""

import pytest

from tests.support.mongo_local import uri_so_local

LOCAIS = [
    "mongodb://localhost:27017",
    "mongodb://localhost/db",
    "mongodb://usuario:senha@127.0.0.1:27017/db?retryWrites=true",
    "mongodb://[::1]:27017/db",
    "mongodb://localhost:27017,127.0.0.1:27018,[::1]:27019/db",
]
REMOTAS = [
    "mongodb://cluster0-shard-00-01.x.mongodb.net:27017/db",
    "mongodb://localhost:27017,cluster0-shard-00-01.x.mongodb.net:27017/db",
    "mongodb://cluster0.x.mongodb.net,localhost/db",
    "mongodb+srv://localhost",
    "mongodb+srv://usuario:senha@localhost/db",
    "mongodb://usuario:localhost@cluster0.x.mongodb.net/db",
    "mongodb://localhost.evil.example:27017/db",
    "http://localhost/db",
    "",
]


@pytest.mark.parametrize("uri", LOCAIS)
def test_local_seed_lists_are_accepted(uri):
    assert uri_so_local(uri)


@pytest.mark.parametrize("uri", REMOTAS)
def test_any_remote_seed_or_srv_is_rejected(uri):
    assert not uri_so_local(uri)

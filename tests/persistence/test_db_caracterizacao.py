"""KI-27 — caracterização de `empiremuse/utils/db.py` além do que já cobrem `test_db_bugs_altos.py` e `test_db_limite_e_cursor.py`.

* `LocalDatabase` (TinyMongo real em `tmp_path`): criação do diretório, documento padrão inserido, cache, migração por versão,
  gravação, exclusão e o caminho padrão sob o RUNTIME_DIR (`EMPIREMUSE_HOME`);
* `MongoDatabase` com um cliente motor falso (nada de rede): correção SSL do endereço, padrão sem inserir, migração, upsert,
  exclusão, `push_data` e a importação dos JSON antigos (`update_from_json`);
* `get_default`, `get_prefix` e `DatetimeSerializer`.
"""

import asyncio
import json
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from empiremuse.utils import db
from empiremuse.utils.db import DBModel, LocalDatabase, MongoDatabase


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    return tmp_path


# ============================================================================ LocalDatabase


class TestLocalDatabase:
    def make(self, tmp_path):
        return LocalDatabase(str(tmp_path / "bd"))

    @pytest.mark.parametrize("dir_", [None, "./local_database"])
    def test_default_directory_is_under_the_runtime_dir(self, home, dir_):
        banco = LocalDatabase(dir_)
        assert banco.dir == str(home / "local_database") and (home / "local_database").is_dir()

    def test_created_document_is_persisted_but_only_update_fills_the_cache(self, tmp_path):
        banco = self.make(tmp_path)
        first = run(banco.get_data(10, db_name=DBModel.guilds, collection="g"))
        second = run(banco.get_data(10, db_name=DBModel.guilds, collection="g"))
        assert second == first and second is not first  # releitura do disco: get_data não grava no cache

        run(banco.update_data(10, second, db_name=DBModel.guilds, collection="g"))
        assert run(banco.get_data(10, db_name=DBModel.guilds, collection="g")) is second

    @pytest.mark.smoke
    def test_old_version_is_migrated_keeping_saved_values(self, tmp_path):
        banco = self.make(tmp_path)
        modelo = db.db_models[DBModel.guilds]
        antigo = {"_id": "7", "ver": 0.1, "prefix_antigo": "x", "djroles": ["9"], "autoplay": True}
        banco._connect["g"][DBModel.guilds].insert_one(antigo)

        data = run(banco.get_data(7, db_name=DBModel.guilds, collection="g"))

        assert data["ver"] == modelo["ver"]
        assert data["djroles"] == ["9"] and data["autoplay"] is True
        assert data["prefix_antigo"] == "x"  # chaves removidas do modelo são preservadas
        assert data["default_player_volume"] == 100  # chaves novas ganham o padrão

    def test_delete_removes_from_disk_and_cache(self, tmp_path):
        banco = self.make(tmp_path)
        data = run(banco.get_data(10, db_name=DBModel.guilds, collection="g"))
        data["autoplay"] = True
        run(banco.update_data(10, data, db_name=DBModel.guilds, collection="g"))

        run(banco.delete_data(10, DBModel.guilds, "g"))

        novo = run(banco.get_data(10, db_name=DBModel.guilds, collection="g"))
        assert novo["autoplay"] is False

    def test_delete_of_unknown_document_does_not_raise(self, tmp_path):
        run(self.make(tmp_path).delete_data(404, DBModel.guilds, "g"))

    @pytest.mark.smoke
    def test_get_default_returns_independent_copies(self, tmp_path):
        banco = self.make(tmp_path)
        a = banco.get_default("g", DBModel.guilds)
        a["djroles"].append("x")
        assert banco.get_default("g", DBModel.guilds)["djroles"] == []

    def test_get_default_global_uses_the_global_models(self, tmp_path):
        banco = self.make(tmp_path)
        assert banco.get_default("global", DBModel.users) == db.global_db_models[DBModel.users]


# ============================================================================ MongoDatabase (cliente motor falso)


class CursorFalso:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __aiter__(self):
        return self._it()

    async def _it(self):
        for d in self.docs:
            yield d


class ColecaoFalsa:
    def __init__(self):
        self.docs = {}
        self.calls = []

    async def find_one(self, filtro):
        return deepcopy(self.docs.get(filtro["_id"]))

    async def insert_one(self, doc):
        self.docs[doc["_id"]] = deepcopy(doc)

    async def update_one(self, filtro, update, upsert=False):
        self.calls.append(("update_one", filtro, update, upsert))
        atual = self.docs.setdefault(filtro["_id"], {"_id": filtro["_id"]})
        atual.update(deepcopy(update["$set"]))

    async def delete_one(self, filtro):
        self.calls.append(("delete_one", filtro))
        return self.docs.pop(filtro["_id"], None)

    def find(self, filtro):
        return CursorFalso(d for d in self.docs.values() if all(d.get(k) == v for k, v in filtro.items()))


class ClienteFalso:
    instances = []

    def __init__(self, uri, connectTimeoutMS=None):
        self.uri, self.timeout = uri, connectTimeoutMS
        self.colecoes = {}
        ClienteFalso.instances.append(self)

    def __getitem__(self, collection):
        return ColecoesPorNome(self, collection)


class ColecoesPorNome:
    def __init__(self, cliente, collection):
        self.cliente, self.collection = cliente, collection

    def __getitem__(self, db_name):
        return self.cliente.colecoes.setdefault((self.collection, db_name), ColecaoFalsa())


@pytest.fixture
def mongo(monkeypatch):
    ClienteFalso.instances.clear()
    monkeypatch.setattr(db, "AsyncIOMotorClient", ClienteFalso)
    monkeypatch.delenv("MONGO_SSL_FIX", raising=False)
    return MongoDatabase("<mongodb://u:p@host/db>", timeout=5)


def colecao(banco, collection="g", db_name=DBModel.guilds):
    return banco._connect[collection][db_name]


class TestMongoDatabaseConnection:
    def test_ssl_fix_adds_the_tls_parameters(self, monkeypatch):
        monkeypatch.setattr(db, "AsyncIOMotorClient", ClienteFalso)
        monkeypatch.setenv("MONGO_SSL_FIX", "1")
        banco = MongoDatabase("mongodb://u:p@host/db?retryWrites=true")
        uri = banco._connect.uri
        assert "ssl=true" in uri and "tlsAllowInvalidCertificates=true" in uri and "retryWrites=true" in uri


class TestMongoDatabaseData:
    def test_unknown_document_returns_the_default_without_inserting(self, mongo):
        data = run(mongo.get_data(1, db_name=DBModel.guilds, collection="g"))
        assert data["ver"] == db.db_models[DBModel.guilds]["ver"]
        assert colecao(mongo).docs == {}

    def test_old_version_is_migrated_and_saved(self, mongo):
        colecao(mongo).docs["1"] = {"_id": "1", "ver": 0.5, "djroles": ["4"]}
        data = run(mongo.get_data(1, db_name=DBModel.guilds, collection="g"))
        assert data["ver"] == db.db_models[DBModel.guilds]["ver"] and data["djroles"] == ["4"]
        assert colecao(mongo).docs["1"]["ver"] == data["ver"]

    def test_cached_result_skips_the_database(self, mongo):
        mongo.cache["g:guilds:1"] = {"cache": True}
        assert run(mongo.get_data(1, db_name=DBModel.guilds, collection="g")) == {"cache": True}

    def test_push_data_inserts(self, mongo):
        run(mongo.push_data({"_id": "5", "x": 1}, db_name=DBModel.guilds, collection="g"))
        assert colecao(mongo).docs["5"]["x"] == 1

    def test_delete_without_cache_entry_still_deletes(self, mongo):
        run(mongo.delete_data(1, DBModel.guilds, "g"))
        assert colecao(mongo).calls == [("delete_one", {"_id": "1"})]


class TestUpdateFromJson:
    def write(self, home, nome, conteudo):
        pasta = home / "local_dbs"
        pasta.mkdir(exist_ok=True)
        (pasta / nome).write_text(json.dumps(conteudo), encoding="utf-8")
        return pasta

    def test_imports_documents_and_moves_the_file_to_backups(self, mongo, home):
        pasta = self.write(home, "g.json", {"guilds": {"1": {"autoplay": True}, "2": {}}, "users": {}})
        (pasta / "backups").mkdir()
        (pasta / "ignorar.txt").write_text("x", encoding="utf-8")

        run(mongo.update_from_json())

        assert colecao(mongo, "g", "guilds").docs["1"]["autoplay"] is True
        assert (pasta / "backups" / "g.json").is_file() and not (pasta / "g.json").exists()
        assert (pasta / "ignorar.txt").exists()

    def test_move_failure_is_reported_but_not_raised(self, mongo, home, monkeypatch, capsys):
        self.write(home, "g.json", {"guilds": {"1": {"autoplay": True}}})

        def falha(*a, **k):
            raise OSError("sem permissão")

        monkeypatch.setattr(db.shutil, "move", falha)
        run(mongo.update_from_json())
        assert "sem permissão" in capsys.readouterr().err


# ============================================================================ utilitários


class TestDatetimeSerializer:
    def test_round_trip_with_the_default_format(self):
        serializer = db.DatetimeSerializer()
        momento = datetime(2026, 10, 23, 8, 30, 15)
        assert serializer.encode(momento) == "2026-10-23T08:30:15"
        assert serializer.decode("2026-10-23T08:30:15") == momento


class TestGetPrefix:
    class Banco:
        def __init__(self, guild_prefix=None, user_prefix=""):
            self.guild_prefix, self.user_prefix, self.reads = guild_prefix, user_prefix, []

        async def get_global_data(self, id_, db_name):
            self.reads.append(db_name)
            if db_name == DBModel.users:
                return {"custom_prefix": self.user_prefix}
            return {"prefix": self.guild_prefix}

    def bot(self, banco, **config):
        bot = SimpleNamespace(
            user=SimpleNamespace(id=99),
            pool=SimpleNamespace(user_prefix_cache={}, guild_prefix_cache={}),
            config=config,
            default_prefix="$",
        )
        bot.get_global_data = banco.get_global_data
        return bot

    def message(self, content, guild=True):
        return SimpleNamespace(
            content=content, author=SimpleNamespace(id=1), guild=SimpleNamespace(id=2) if guild else None
        )

    def test_mention_prefix_wins(self):
        bot = self.bot(self.Banco())
        result = run(db.get_prefix(bot, self.message("<@99> oi")))
        assert callable(result) or isinstance(result, (list, tuple))
        assert self.Banco().reads == []

    def test_user_prefix_wins_over_guild_prefix(self):
        bot = self.bot(self.Banco(guild_prefix="!", user_prefix=">>"))
        assert run(db.get_prefix(bot, self.message(">>play"))) == ">>"

    def test_direct_message_uses_the_default_prefix(self):
        bot = self.bot(self.Banco())
        result = run(db.get_prefix(bot, self.message("play", guild=False)))
        assert callable(result)

    def test_falls_back_to_the_configured_default_prefix(self):
        bot = self.bot(self.Banco(guild_prefix=None), DEFAULT_PREFIX="::")
        assert run(db.get_prefix(bot, self.message("play"))) == "::"

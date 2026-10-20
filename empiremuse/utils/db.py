# -*- coding: utf-8 -*-
from __future__ import annotations

import collections.abc
import json
import os
import shutil
import traceback
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

import disnake
from cachetools import TTLCache
from disnake.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from tinydb_serialization import Serializer, SerializationMiddleware
from tinymongo import TinyMongoClient
from tinymongo.serializers import DateTimeSerializer

from empiremuse import paths

if TYPE_CHECKING:
    from empiremuse.utils.client import BotCore


class DBModel:
    guilds = "guilds"
    users = "users"
    default = "default"


db_models = {
    DBModel.guilds: {
        "ver": 1.11,
        "player_controller": {
            "channel": None,
            "message_id": None,
            "skin": None,
            "static_skin": None,
            "fav_links": {},
        },
        "autoplay": False,
        "check_other_bots_in_vc": False,
        "enable_restrict_mode": False,
        "default_player_volume": 100,
        "djroles": [],
    },
    DBModel.users: {
        "ver": 1.0,
        "fav_links": {},
    },
}

scrobble_model = {DBModel.users: {"ver": 1.0, "tracks": []}}

global_db_models = {
    DBModel.users: {
        "ver": 1.6,
        "fav_links": {},
        "integration_links": {},
        "token": "",
        "custom_prefix": "",
        "last_tracks": [],
        "lastfm": {
            "username": "",
            "sessionkey": "",
            "scrobble": False,
        },
    },
    DBModel.guilds: {
        "ver": 1.4,
        "prefix": "",
        "global_skin": False,
        "player_skin": None,
        "player_skin_static": None,
        "voice_channel_status": "",
        "custom_skins": {},
        "custom_skins_static": {},
        "listen_along_invites": {},
    },
    DBModel.default: {"ver": 1.0, "extra_tokens": {}},
}


async def get_prefix(bot: BotCore, message: disnake.Message):
    if str(message.content).startswith((f"<@!{bot.user.id}> ", f"<@{bot.user.id}> ")):
        return commands.when_mentioned(bot, message)

    try:
        user_prefix = bot.pool.user_prefix_cache[message.author.id]
    except KeyError:
        user_data = await bot.get_global_data(message.author.id, db_name=DBModel.users)
        bot.pool.user_prefix_cache[message.author.id] = user_data["custom_prefix"]
        user_prefix = user_data["custom_prefix"]

    if user_prefix and message.content.startswith(user_prefix):
        return user_prefix

    if not message.guild:
        return commands.when_mentioned_or(bot.default_prefix)

    try:
        guild_prefix = bot.pool.guild_prefix_cache[message.guild.id]
    except KeyError:
        data = await bot.get_global_data(message.guild.id, db_name=DBModel.guilds)
        guild_prefix = data.get("prefix")

    if not guild_prefix:
        guild_prefix = bot.config.get("DEFAULT_PREFIX") or "!!"

    return guild_prefix


class BaseDB:
    def __init__(self, cache_maxsize: int = 1000, cache_ttl=300):
        self.cache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)

    def get_default(self, collection: str, db_name: Union[DBModel.guilds, DBModel.users]):
        if collection == "global":
            return deepcopy(global_db_models[db_name])
        return deepcopy(db_models[db_name])


class DatetimeSerializer(Serializer):
    OBJ_CLASS = datetime

    def __init__(self, format="%Y-%m-%dT%H:%M:%S", *args, **kwargs):
        super(DatetimeSerializer, self).__init__(*args, **kwargs)
        self._format = format

    def encode(self, obj):
        return obj.strftime(self._format)

    def decode(self, s):
        return datetime.strptime(s, self._format)


class CustomTinyMongoClient(TinyMongoClient):
    @property
    def _storage(self):
        serialization = SerializationMiddleware()
        serialization.register_serializer(DateTimeSerializer(), "TinyDate")
        return serialization


class LocalDatabase(BaseDB):
    def __init__(self, dir_=None, cache_maxsize=1000, cache_ttl=300):
        super().__init__(cache_maxsize=cache_maxsize, cache_ttl=cache_ttl)

        if dir_ is None or dir_ == "./local_database":
            dir_ = str(paths.RUNTIME_DIR / "local_database")

        self.dir = dir_

        if not os.path.isdir(dir_):
            os.makedirs(dir_)

        self._connect = CustomTinyMongoClient(dir_)

    async def get_data(
        self, id_: int, *, db_name: Union[DBModel.guilds, DBModel.users], collection: str, default_model: dict = None
    ):
        if not default_model:
            default_model = db_models

        id_ = str(id_)

        if (cached_result := self.cache.get(f"{collection}:{db_name}:{id_}")) is not None:
            return cached_result

        data = self._connect[collection][db_name].find_one({"_id": id_})

        if not data:
            data = deepcopy(default_model[db_name])
            data["_id"] = str(id_)
            self._connect[collection][db_name].insert_one(data)

        elif data["ver"] != default_model[db_name]["ver"]:
            data = update_values(deepcopy(default_model[db_name]), data)
            data["ver"] = default_model[db_name]["ver"]

            await self.update_data(id_, data, db_name=db_name, collection=collection)

        return data

    async def update_data(
        self,
        id_,
        data: dict,
        *,
        db_name: Union[DBModel.guilds, DBModel.users],
        collection: str,
        default_model: dict = None,
    ):
        id_ = str(id_)
        data["_id"] = id_

        # upsert como no MongoDatabase: documento novo também vai para o disco. Se a gravação falhar, o erro original
        # sobe e o cache não é atualizado (senão o dado "salvo" some quando o cache expirar).
        if not self._connect[collection][db_name].update_one({"_id": id_}, {"$set": data}, upsert=True).raw_result:
            self._connect[collection][db_name].insert_one(data)

        self.cache[f"{collection}:{db_name}:{id_}"] = data

        return data

    async def query_data(self, db_name: str, collection: str, filter: dict = None, limit: Optional[int] = None):
        """Os documentos que casam com ``filter``; ``limit`` (se informado) é o máximo devolvido. Sem ``limit`` vem tudo."""
        cursor = self._connect[collection][db_name].find(filter or {})
        return cursor if limit is None else cursor.limit(limit)

    async def iter_data(self, db_name: str, collection: str, filter: dict = None):
        """Os documentos, um por vez. O TinyMongo já guarda a coleção na memória; a fotografia da lista evita que quem grava
        enquanto percorre (como o ``fixfavs``) mexa no que está sendo percorrido."""
        for document in list(self._connect[collection][db_name].find(filter or {})):
            yield document

    async def delete_data(self, id_, db_name: str, collection: str):
        try:
            self._connect[collection][db_name].delete_one({"_id": str(id_)})
        except TypeError:
            return

        try:
            self.cache.pop(f"{collection}:{db_name}:{id_}")
        except KeyError:
            pass


class MongoDatabase(BaseDB):
    def __init__(self, token: str, timeout=30, cache_maxsize=1000, cache_ttl=300):
        super().__init__(cache_maxsize=cache_maxsize, cache_ttl=cache_ttl)

        fix_ssl = os.environ.get("MONGO_SSL_FIX")

        if fix_ssl:
            parse_result = urlparse(token)
            parameters = parse_qs(parse_result.query)

            parameters.update({"ssl": ["true"], "tlsAllowInvalidCertificates": ["true"]})

            token = urlunparse(parse_result._replace(query=urlencode(parameters, doseq=True)))

        self._connect = AsyncIOMotorClient(token.strip("<>"), connectTimeoutMS=timeout * 1000)

    async def push_data(self, data, *, db_name: Union[DBModel.guilds, DBModel.users], collection: str):
        await self._connect[collection][db_name].insert_one(data)

    async def update_from_json(self):
        dbs_dir = paths.RUNTIME_DIR / "local_dbs"
        backups_dir = dbs_dir / "backups"
        if not backups_dir.is_dir():
            backups_dir.mkdir(parents=True, exist_ok=True)

        if dbs_dir.is_dir():
            for f in os.listdir(dbs_dir):
                if not f.endswith(".json"):
                    continue

                with open(dbs_dir / f) as file:
                    data = json.load(file)

                for db_name, db_data in data.items():
                    if not db_data:
                        continue

                    for id_, d in db_data.items():
                        await self.update_data(id_=id_, data=d, db_name=db_name, collection=f[:-5])

                try:
                    shutil.move(str(dbs_dir / f), str(backups_dir / f))
                except:
                    traceback.print_exc()

    async def get_data(
        self, id_: int, *, db_name: Union[DBModel.guilds, DBModel.users], collection: str, default_model: dict = None
    ):
        if not default_model:
            default_model = db_models

        id_ = str(id_)

        if (cached_result := self.cache.get(f"{collection}:{db_name}:{id_}")) is not None:
            return cached_result

        data = await self._connect[collection][db_name].find_one({"_id": id_})

        if not data:
            return deepcopy(default_model[db_name])

        elif data["ver"] != default_model[db_name]["ver"]:
            data = update_values(deepcopy(default_model[db_name]), data)
            data["ver"] = default_model[db_name]["ver"]
            await self.update_data(id_, data, db_name=db_name, collection=collection)

        return data

    async def update_data(
        self,
        id_,
        data: dict,
        *,
        db_name: Union[DBModel.guilds, DBModel.users, str],
        collection: str,
        default_model: dict = None,
    ):
        self.cache[f"{collection}:{db_name}:{id_}"] = data

        try:
            del data["_id"]
        except KeyError:
            pass

        await self._connect[collection][db_name].update_one({"_id": str(id_)}, {"$set": data}, upsert=True)
        return data

    async def query_data(self, db_name: str, collection: str, filter: dict = None, limit: Optional[int] = None) -> list:
        """Os documentos que casam com ``filter`` numa lista; ``limit`` (se informado) é o máximo puxado do cursor."""
        cursor = self._connect[collection][db_name].find(filter or {})
        if limit is not None:
            cursor = cursor.limit(limit)
        return [d async for d in cursor]

    async def iter_data(self, db_name: str, collection: str, filter: dict = None):
        """O cursor do motor entregue um documento por vez: nada da coleção é guardado na memória."""
        async for document in self._connect[collection][db_name].find(filter or {}):
            yield document

    async def delete_data(self, id_, db_name: str, collection: str):
        try:
            self.cache.pop(f"{collection}:{db_name}:{id_}")
        except KeyError:
            pass
        return await self._connect[collection][db_name].delete_one({"_id": str(id_)})


def update_values(d: dict, u: collections.abc.Mapping) -> dict:
    """Migra o documento salvo `u` para o modelo `d` (o modelo é alterado e devolvido; passe uma cópia).

    Só acrescenta e atualiza, nunca apaga: o valor salvo vence o padrão em qualquer tipo (inclusive listas), chaves
    novas do modelo ficam com o padrão e chaves removidas do modelo são preservadas. Nada do documento salvo é
    compartilhado com o resultado (cópia profunda).
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping) and isinstance(d.get(k), collections.abc.Mapping):
            d[k] = update_values(d[k], v)
        else:
            d[k] = deepcopy(v)
    return d

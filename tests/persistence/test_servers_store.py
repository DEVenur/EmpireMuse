"""Documento único por servidor (``pool.servers``): migração só do principal, falha que não grava, trava, compare-and-set e fachada.

Banco falso em memória com o contrato de ``find_doc``/``save_doc_cas``; o mundo é um pool com o principal (``TOKEN``) e uma reserva.
"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from empiremuse.rules.servers import SettingError
from empiremuse.utils.db import DBModel
from empiremuse.utils.servers import (
    ServerConfigConflict,
    ServerConfigUnavailable,
    ServerStore,
    StaleSettingsWriter,
    UnknownGuild,
)

pytestmark = pytest.mark.critical

GID = 111
MAIN_ID, RESERVE_ID = 1001, 1002
SERVERS = (DBModel.servers, "global")


class Banco:
    """Documentos por ``(db_name, collection, _id)``; falhas de leitura/gravação e conflito de ``rev`` sob demanda."""

    def __init__(self):
        self.docs = {}
        self.read_error = False
        self.write_error = False
        self.conflicts = 0  # quantas gravações perdem a corrida (alguém mudou o rev antes)
        self.saves = []

    def put(self, db_name, collection, id_, doc):
        self.docs[(db_name, collection, str(id_))] = deepcopy(doc)

    def servers_doc(self, gid=GID):
        return self.docs.get((*SERVERS, str(gid)))

    async def find_doc(self, id_, *, db_name, collection):
        if self.read_error and db_name == DBModel.guilds:
            raise OSError("leitura falhou")
        return deepcopy(self.docs.get((db_name, collection, str(id_))))

    async def save_doc_cas(self, id_, doc, *, expected_rev, db_name, collection):
        if self.write_error:
            raise OSError("gravação falhou")
        key = (db_name, collection, str(id_))
        if self.conflicts:
            self.conflicts -= 1
            return False
        stored = self.docs.get(key)
        if (stored is None) != (expected_rev is None) or (stored and stored["rev"] != expected_rev):
            return False
        self.docs[key] = deepcopy(doc)
        self.saves.append(deepcopy(doc))
        return True

    async def get_data(self, id_, *, db_name, collection):
        stored = self.docs.get((db_name, collection, str(id_)))
        return (
            deepcopy(stored)
            if stored
            else {"_id": str(id_), "player_controller": {"channel": None, "message_id": None}}
        )

    async def update_data(self, id_, data, *, db_name, collection):
        self.docs[(db_name, collection, str(id_))] = deepcopy(data)


def make_bot(bot_id, identifier, *, online=True, guilds=(GID,)):
    roles = [SimpleNamespace(id=10), SimpleNamespace(id=20)]
    return SimpleNamespace(
        user=SimpleNamespace(id=bot_id) if online else None,
        identifier=identifier,
        exclusive_guild_id=None,
        player_skins={"default": 1},
        player_static_skins={"static": 1},
        get_guild=lambda gid: SimpleNamespace(roles=roles) if gid in guilds else None,
    )


@pytest.fixture
def world():
    banco = Banco()
    bots = [make_bot(MAIN_ID, "TOKEN"), make_bot(RESERVE_ID, "TOKEN_2")]
    pool = SimpleNamespace(database=banco, get_all_bots=lambda: bots)
    return SimpleNamespace(banco=banco, bots=bots, pool=pool, store=ServerStore(pool))


def old_doc(**settings):
    return {
        "_id": str(GID),
        "ver": 1.0,
        "player_controller": {"channel": "5", "message_id": "6", **settings.pop("pc", {})},
    } | settings


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------- S1: migração só do principal, idempotente


def test_migration_copies_only_the_main_document_and_ignores_the_reserve(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, old_doc(autoplay=True, djroles=[10], pc={"skin": "default"}))
    world.banco.put(
        DBModel.guilds, str(RESERVE_ID), GID, old_doc(autoplay=False, enable_restrict_mode=True, djroles=[20])
    )
    reserve_before = deepcopy(world.banco.docs[(DBModel.guilds, str(RESERVE_ID), str(GID))])

    settings = run(world.store.settings(GID))

    assert settings["autoplay"] is True and settings["djroles"] == ["10"] and settings["skin"] == "default"
    assert settings["enable_restrict_mode"] is False  # o valor da reserva não entra
    assert world.banco.servers_doc()["migrated"]["settings"] is True
    assert world.banco.docs[(DBModel.guilds, str(RESERVE_ID), str(GID))] == reserve_before


def test_two_boots_give_the_same_document_and_the_second_writes_nothing(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, old_doc(autoplay=True))
    first = run(world.store.get(GID))
    saves = len(world.banco.saves)

    second = run(ServerStore(world.pool).get(GID))  # outro boot: cache vazio, mesmo banco

    assert second == first and len(world.banco.saves) == saves


def test_missing_main_document_migrates_to_the_defaults(world):
    settings = run(world.store.settings(GID))
    assert settings["autoplay"] is False and world.banco.servers_doc()["migrated"]["settings"] is True


def test_invalid_restrict_mode_in_the_main_document_migrates_closed(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, old_doc(enable_restrict_mode="talvez"))
    assert run(world.store.settings(GID))["enable_restrict_mode"] is True


# ---------------------------------------------------------------------- S2/S2b/S4: falha → nada gravado, levanta, nunca o padrão


@pytest.mark.parametrize("cause", ["read_error", "main_offline", "reserve_only"])
def test_migration_that_cannot_decide_writes_nothing_and_retries_later(world, cause):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, old_doc(enable_restrict_mode=True))
    if cause == "read_error":
        world.banco.read_error = True
    else:
        world.bots[0].user = None  # principal não logado (a reserva está online, mas não decide)
        if cause == "main_offline":
            world.bots.pop(1)

    with pytest.raises(ServerConfigUnavailable):
        run(world.store.get(GID))
    assert world.banco.servers_doc() is None and world.banco.saves == []
    assert (DBModel.guilds, str(RESERVE_ID), str(GID)) not in world.banco.docs  # doc por bot não é criado

    world.banco.read_error, world.bots[0].user = False, SimpleNamespace(id=MAIN_ID)
    assert run(world.store.settings(GID))["enable_restrict_mode"] is True  # a próxima chamada migra o valor de verdade


def test_failed_write_keeps_the_copy_and_the_migration_flag_as_they_were(world):
    world.banco.write_error = True
    with pytest.raises(ServerConfigUnavailable):
        run(world.store.get(GID))
    assert world.banco.servers_doc() is None and not world.store._docs

    world.banco.write_error = False
    assert run(world.store.get(GID))["migrated"]["settings"] is True

    world.banco.write_error = True
    with pytest.raises(ServerConfigUnavailable):
        run(world.store.patch(GID, "settings", {"autoplay": True}))
    assert run(world.store.settings(GID))["autoplay"] is False and world.banco.servers_doc()["rev"] == 1


# ---------------------------------------------------------------------- S3: escritas concorrentes e compare-and-set


def test_simultaneous_patches_and_role_changes_all_survive(world):
    async def scenario():
        await world.store.get(GID)
        await asyncio.gather(
            world.store.patch(GID, "settings", {"autoplay": True}),
            world.store.patch(GID, "settings", {"default_player_volume": 50}),
            world.store.add_djrole(GID, 10),
            world.store.add_djrole(GID, 20),
        )
        return await world.store.settings(GID)

    settings = run(scenario())
    assert settings["autoplay"] is True and settings["default_player_volume"] == 50
    assert sorted(settings["djroles"]) == ["10", "20"]
    assert world.banco.servers_doc()["rev"] == 5  # migração + 4 gravações, cada uma a partir da anterior


@pytest.mark.parametrize(("conflicts", "survives"), [(1, True), (2, False)])
def test_lost_cas_race_retries_once_then_gives_up(world, conflicts, survives):
    run(world.store.get(GID))
    world.banco.conflicts = conflicts
    if survives:
        assert run(world.store.patch(GID, "settings", {"autoplay": True}))["autoplay"] is True
    else:
        with pytest.raises(ServerConfigConflict):
            run(world.store.patch(GID, "settings", {"autoplay": True}))
        assert run(world.store.settings(GID))["autoplay"] is False


def test_patch_refuses_invalid_changes_without_writing(world):
    run(world.store.get(GID))
    saves = len(world.banco.saves)
    with pytest.raises(SettingError):
        run(world.store.patch(GID, "settings", {"default_player_volume": 7}))
    with pytest.raises(SettingError):
        run(world.store.add_djrole(GID, 999))  # cargo que não existe no servidor
    assert len(world.banco.saves) == saves


# ---------------------------------------------------------------------- S-V11: servidor fora do pool


@pytest.mark.parametrize("gid", [999, 0, -5, "abc", None, True])
def test_guild_outside_the_pool_is_refused_and_nothing_is_created(world, gid):
    with pytest.raises(UnknownGuild):
        run(world.store.get(gid))
    with pytest.raises(UnknownGuild):
        run(world.store.patch(gid, "settings", {"autoplay": True}))
    assert world.banco.servers_doc(gid) is None and world.banco.saves == []


# ---------------------------------------------------------------------- S3b: fachada antiga


def test_legacy_writer_that_changed_settings_raises_and_the_others_are_saved(world):
    bot = world.bots[0]
    doc = run(world.store.legacy_doc(bot, GID))
    assert doc["autoplay"] is False and doc["player_controller"]["channel"] is None

    doc["autoplay"] = True
    with pytest.raises(StaleSettingsWriter):
        run(world.store.save_legacy(bot, GID, doc))
    assert run(world.store.settings(GID))["autoplay"] is False

    doc["autoplay"] = False
    doc["player_controller"]["channel"] = "77"
    run(world.store.save_legacy(bot, GID, doc))
    stored = world.banco.docs[(DBModel.guilds, str(MAIN_ID), str(GID))]
    assert (
        stored["player_controller"]["channel"] == "77" and "autoplay" not in stored
    )  # settings nunca vão ao doc do bot


def test_legacy_view_is_a_deep_copy(world):
    run(world.store.patch(GID, "settings", {"djroles": [10]}))
    view = run(world.store.legacy_doc(world.bots[0], GID))
    view["djroles"].append("x")
    assert run(world.store.settings(GID))["djroles"] == ["10"]


def test_legacy_view_outside_the_pool_uses_the_bot_own_data_without_creating_a_document(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), 999, {"_id": "999", "autoplay": True, "player_controller": {}})
    assert run(world.store.legacy_doc(world.bots[0], 999))["autoplay"] is True
    assert world.banco.servers_doc(999) is None

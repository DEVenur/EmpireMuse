"""Canal de pedidos único no store (item 11, P4, S7 e S-V11): o canal migra só do principal, a eleição do bot do painel é decidida dentro
da trava conferindo quem está no servidor, e o formato antigo grava canal/mensagem só no documento único e só o que o escritor mudou."""

import asyncio
from types import SimpleNamespace

import pytest

from empiremuse.rules.servers import SettingError
from empiremuse.utils.db import DBModel
from empiremuse.utils.servers import ServerConfigConflict, ServerConfigUnavailable, ServerStore, UnknownGuild
from tests.persistence.test_servers_store import GID, MAIN_ID, RESERVE_ID, Banco, make_bot

pytestmark = pytest.mark.critical

OUTSIDE = 777  # servidor fora do pool


def run(coro):
    return asyncio.run(coro)


def legacy(channel="12", message="34"):
    return {"_id": str(GID), "player_controller": {"channel": channel, "message_id": message}}


@pytest.fixture
def world():
    banco = Banco()
    bots = [make_bot(MAIN_ID, "TOKEN"), make_bot(RESERVE_ID, "TOKEN_2")]
    for bot in bots:
        bot.music = SimpleNamespace(players={})
    pool = SimpleNamespace(database=banco, get_all_bots=lambda: bots)
    store = ServerStore(pool)
    return SimpleNamespace(banco=banco, bots=bots, pool=pool, store=store, request=store.request)


def request_doc(world):
    return world.banco.servers_doc()["request"]


# ---------------------------------------------------------------------- migração: só o canal do principal


def test_the_channel_comes_only_from_the_main_bot_and_two_boots_agree(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, legacy("12", "34"))
    world.banco.put(DBModel.guilds, str(RESERVE_ID), GID, legacy("99", "88"))

    config = run(world.request.get(GID))

    assert (config.channel, config.message_id, config.panel_bot_id) == (12, 34, None)  # o painel ainda não foi eleito
    saves = len(world.banco.saves)
    assert run(ServerStore(world.pool).request.get(GID)) == config and len(world.banco.saves) == saves


@pytest.mark.parametrize("old", [None, legacy("não é id", "34"), legacy(None, "34"), legacy("-3", "34")])
def test_a_missing_or_garbage_channel_migrates_to_no_channel_without_creating_the_bots_document(world, old):
    if old is not None:
        world.banco.put(DBModel.guilds, str(MAIN_ID), GID, old)
    config = run(world.request.get(GID))
    assert (config.channel, config.message_id) == (None, None)
    assert world.banco.servers_doc()["migrated"]["request"] is True
    if old is None:
        assert (DBModel.guilds, str(MAIN_ID), str(GID)) not in world.banco.docs


@pytest.mark.parametrize("cause", ["read_error", "main_offline"])
def test_migration_that_cannot_decide_writes_nothing_raises_and_retries_later(world, cause):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, legacy("12", "34"))
    if cause == "read_error":
        world.banco.read_error = True
    else:
        world.bots[0].user = None

    with pytest.raises(ServerConfigUnavailable):
        run(world.request.get(GID))
    assert world.banco.servers_doc() is None and world.banco.saves == []

    world.banco.read_error, world.bots[0].user = False, SimpleNamespace(id=MAIN_ID)
    assert run(world.request.get(GID)).channel == 12  # nunca o "sem canal" do modelo


# ---------------------------------------------------------------------- gravar e limpar


def test_set_and_clear_go_through_the_server_document(world):
    config = run(world.request.set(GID, 12, 34))
    assert (config.channel, config.message_id) == (12, 34) and request_doc(world)["channel"] == "12"
    assert run(world.request.set(GID, None, 34)).message_id is None  # sem canal não há mensagem
    run(world.request.set(GID, 12, 34))
    assert run(world.request.clear(GID)).channel is None and request_doc(world)["message_id"] is None


def test_a_stale_version_is_refused_and_a_failed_write_changes_nothing(world):
    stale = run(world.request.get(GID)).rev
    run(world.request.set(GID, 12, 34))
    saves = len(world.banco.saves)
    with pytest.raises(ServerConfigConflict):
        run(world.request.set(GID, 99, 98, expected_rev=stale))
    world.banco.write_error = True
    with pytest.raises(ServerConfigUnavailable):
        run(world.request.set(GID, 99, 98))
    world.banco.write_error = False
    assert len(world.banco.saves) == saves and run(world.request.get(GID)).channel == 12


def test_two_simultaneous_writers_to_the_same_server_never_lose_the_last_one(world):
    async def scenario():
        await world.request.get(GID)
        await asyncio.gather(world.request.set(GID, 1, 2), world.request.set(GID, 3, 4))
        return await world.request.get(GID)

    config = run(scenario())
    assert (config.channel, config.message_id) in ((1, 2), (3, 4))  # um inteiro, nunca canal de um e mensagem do outro


# ---------------------------------------------------------------------- o bot do painel (S7, S-V11)


def test_the_main_is_the_panel_bot_and_a_reserve_is_not_while_the_main_is_in_the_server(world):
    election = run(world.request.elect(GID))
    assert (
        election.bot is world.bots[0]
        and election.changed is True
        and request_doc(world)["panel_bot_id"] == str(MAIN_ID)
    )
    assert run(world.request.elect(GID)).changed is False  # igual ao gravado: ninguém reenvia o painel
    assert run(world.request.is_panel_bot(GID, world.bots[0])) is True
    saves = len(world.banco.saves)
    assert run(world.request.is_panel_bot(GID, world.bots[1])) is False and len(world.banco.saves) == saves


def test_when_the_main_leaves_the_first_reserve_takes_over_and_the_change_is_reported(world):
    run(world.request.elect(GID))
    world.bots[0].get_guild = lambda gid: None  # o principal saiu do servidor

    election = run(world.request.elect(GID))

    assert election.bot is world.bots[1] and election.changed is True  # quem muda reenvia o painel
    assert run(world.request.is_panel_bot(GID, world.bots[1])) is True
    assert run(world.request.is_panel_bot(GID, world.bots[0])) is False


def test_nobody_in_the_server_means_no_panel_bot(world):
    for bot in world.bots:
        bot.get_guild = lambda gid: None
    assert run(world.request.panel_bot(GID)) is None
    with pytest.raises(UnknownGuild):  # e nada é eleito nem criado para um servidor que o pool não enxerga
        run(world.request.elect(GID))
    assert world.banco.servers_doc() is None


def test_the_election_looks_at_who_is_in_the_server_again_inside_the_lock(world, monkeypatch):  # S-V11
    real = world.request.peers
    calls = []

    def peers(gid):
        calls.append(gid)
        return (
            real(gid) if len(calls) > 1 else [p for p in real(gid) if p.bot_id == RESERVE_ID]
        )  # 1ª olhada: só a reserva

    monkeypatch.setattr(world.request, "peers", peers)

    # fora da trava só a reserva parecia estar; dentro dela o principal já entrou: vale o de dentro
    assert run(world.request.panel_bot(GID)) is world.bots[0] and request_doc(world)["panel_bot_id"] == str(MAIN_ID)


# ---------------------------------------------------------------------- formato antigo: canal e mensagem vivem no documento único


def test_the_old_format_shows_the_servers_channel_not_the_bots_own(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, legacy("12", "34"))
    run(world.request.get(GID))
    world.banco.put(DBModel.guilds, str(RESERVE_ID), GID, legacy("99", "88"))  # a reserva tem o seu, ignorado

    view = run(world.store.legacy_doc(world.bots[1], GID))

    assert view["player_controller"]["channel"] == "12" and view["player_controller"]["message_id"] == "34"


def test_a_writer_through_update_data_saves_only_what_it_changed_into_the_server_document(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, legacy("12", "34"))
    bot = world.bots[1]  # uma reserva grava; o documento é o do servidor
    doc = run(world.store.legacy_doc(bot, GID))
    run(world.request.set(GID, 12, 56))  # outro admin mudou a mensagem no meio

    doc["player_controller"]["channel"] = "77"  # o escritor só mexe no canal
    run(world.store.save_legacy(bot, GID, doc))

    config = run(world.request.get(GID))
    assert config.channel == 77 and config.message_id == 56  # a mensagem do outro não foi sobrescrita
    assert (DBModel.guilds, str(RESERVE_ID), str(GID)) not in world.banco.docs  # e nada no documento da reserva


def test_clearing_the_channel_through_update_data_clears_the_message_and_garbage_is_refused(world):
    world.banco.put(DBModel.guilds, str(MAIN_ID), GID, legacy("12", "34"))
    bot = world.bots[0]
    doc = run(world.store.legacy_doc(bot, GID))
    doc["player_controller"]["channel"] = None
    run(world.store.save_legacy(bot, GID, doc))
    config = run(world.request.get(GID))
    assert config.channel is None and config.message_id is None

    bad = run(world.store.legacy_doc(bot, GID))
    bad["player_controller"]["channel"] = "não é id"
    with pytest.raises(SettingError):
        run(world.store.save_legacy(bot, GID, bad))


def test_a_server_outside_the_pool_keeps_the_old_behaviour_in_the_bots_own_document(world):
    bot = world.bots[0]
    doc = run(world.store.legacy_doc(bot, OUTSIDE))
    doc["player_controller"]["channel"] = "42"
    run(world.store.save_legacy(bot, OUTSIDE, doc))
    assert world.banco.docs[(DBModel.guilds, str(MAIN_ID), str(OUTSIDE))]["player_controller"]["channel"] == "42"
    assert world.banco.servers_doc(OUTSIDE) is None

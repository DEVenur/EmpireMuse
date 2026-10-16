"""panel/authz.py — GuildAuthorizer: matriz de autorização, cache de decisões e revogação.

Interpretações (contrato BRIEFING-PAINEL-E3.md): ver o relatório. Tudo com dublês; relógio injetado; sem rede.
"""
import asyncio
import logging

import aiohttp
import pytest

from tests.panel.helpers_servers import (USER_ID, FakeBot, FakeGuild, FakePool, forbidden, http_error, make_session,
                                         not_found, run)
from tests.panel.helpers_login import FakeClock
from tests.panel.helpers import require

GID = "42"
UID = int(USER_ID)


def authz():
    return require("panel.authz")


def setup(*, owner=False, admin=False, manage=False, member=True, bot_ready=True, extra_bots=0, **kw):
    """Servidor 42 com um usuário (1001) e o(s) bot(s) do pool."""
    guild = FakeGuild(GID, name="Meu Servidor", owner_id=UID if owner else 999, **kw)
    if member:
        guild.add_member(UID, administrator=admin, manage_guild=manage)
    bots = [FakeBot(1, "Bot Um", ready=bot_ready, guilds=[guild])]
    bots += [FakeBot(10 + i, f"Bot {i}", guilds=[guild]) for i in range(extra_bots)]
    pool = FakePool(bots)
    clock = FakeClock()
    return guild, pool, clock, authz().GuildAuthorizer(pool, clock=clock)


def authorize(authorizer, session=None, guild_id=GID, **kwargs):
    return run(authorizer.authorize(session or make_session(guild_ids=(GID,)), guild_id, **kwargs))


# --------------------------------------------------------------------------- modelos

def test_guild_access_denied_is_an_exception():
    assert issubclass(authz().GuildAccessDenied, Exception)


def test_authorize_returns_access_with_guild_and_ready_bots_in_stable_order():
    guild, pool, _, authorizer = setup(admin=True, extra_bots=2, icon_hash="abcicon")
    access = authorize(authorizer)
    assert (access.guild_id, access.name) == (GID, "Meu Servidor")
    assert [b.id for b in access.bots] == ["1", "10", "11"]
    assert [b.name for b in access.bots] == ["Bot Um", "Bot 0", "Bot 1"]
    assert all(b.avatar_url.startswith("https://cdn.discordapp.com/") for b in access.bots)
    assert access.icon_url and GID in access.icon_url and "abcicon" in access.icon_url


def test_icon_url_is_none_when_guild_has_no_icon():
    assert authorize(setup(admin=True)[3]).icon_url is None


def test_models_are_frozen():
    import dataclasses
    for model in (authz().BotRef, authz().GuildAccess):
        assert dataclasses.is_dataclass(model) and model.__dataclass_params__.frozen


def test_only_ready_bots_are_listed():
    guild, pool, _, authorizer = setup(admin=True)
    pool.bots.append(FakeBot(77, "Bot Offline", ready=False, guilds=[guild]))
    assert [b.id for b in authorize(authorizer).bots] == ["1"]


def test_guild_whose_only_bot_is_not_ready_is_denied():
    _, _, _, authorizer = setup(admin=True, bot_ready=False)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


# --------------------------------------------------------------------------- matriz de permissão

@pytest.mark.parametrize("kwargs", [
    {"owner": True}, {"admin": True}, {"manage": True}, {"admin": True, "manage": True}, {"owner": True, "admin": True},
])
def test_owner_administrator_or_manage_guild_is_authorized(kwargs):
    assert authorize(setup(**kwargs)[3]).guild_id == GID


@pytest.mark.parametrize("kwargs", [
    {},                      # membro comum
    {"member": False},       # não é membro (get_member None e fetch NotFound)
])
def test_plain_member_or_non_member_is_denied(kwargs):
    with pytest.raises(authz().GuildAccessDenied):
        authorize(setup(**kwargs)[3])


def test_non_member_owner_is_denied():
    """Dono que não é mais membro atual: a regra (b) exige membro."""
    _, _, _, authorizer = setup(owner=True, member=False)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


def test_bot_absent_from_guild_is_denied():
    guild, pool, _, authorizer = setup(admin=True)
    pool.bots[0].guilds.clear()
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


def test_empty_pool_is_denied():
    guild, pool, _, authorizer = setup(admin=True)
    pool.bots.clear()
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


def test_uses_gateway_cache_before_fetching_member():
    guild, _, _, authorizer = setup(admin=True)
    authorize(authorizer)
    assert guild.calls["get_member"] == 1 and guild.calls["fetch_member"] == 0


def test_fetches_member_when_not_cached_and_accepts_admin():
    from tests.panel.helpers_servers import FakeMember
    guild, _, _, authorizer = setup(member=False)
    guild.fetchable[UID] = FakeMember(administrator=True)
    assert authorize(authorizer).guild_id == GID
    assert guild.calls["fetch_member"] == 1


@pytest.mark.parametrize("failure", [
    not_found, forbidden, http_error, asyncio.TimeoutError, lambda: OSError("rede caiu"),
    lambda: aiohttp.ClientError("rede"),
], ids=["NotFound", "Forbidden", "HTTPException", "timeout", "OSError", "aiohttp"])
def test_fetch_member_failures_deny_access(failure):
    guild, _, _, authorizer = setup(member=False)
    guild.fetchable[UID] = failure()
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


def test_network_error_is_logged_without_sensitive_data(caplog):
    guild, _, _, authorizer = setup(member=False)
    guild.fetchable[UID] = OSError("falha com token-SEGREDO-123 em https://discord.com/api?code=abc")
    with caplog.at_level(logging.DEBUG), pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING], "erro de rede deve ser logado"
    assert "token-SEGREDO-123" not in caplog.text and "code=abc" not in caplog.text


# --------------------------------------------------------------------------- entrada: id inválido / fora da sessão

@pytest.mark.parametrize("bad_id", ["", "abc", "12a", "-1", " 42", "42 ", "4 2", "1" * 21, "١٢٣", "42\n", "4.2", None])
def test_invalid_guild_id_is_denied_without_any_discord_call(bad_id):
    guild, pool, _, authorizer = setup(admin=True)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, make_session(guild_ids=(GID, "")), bad_id)
    assert pool.api_calls() == 0, "id inválido não pode gerar chamadas ao bot/Discord"


def test_guild_outside_session_guilds_is_denied_without_any_discord_call():
    guild, pool, _, authorizer = setup(admin=True)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, make_session(guild_ids=("7", "8")), GID)  # o servidor 42 existe e o usuário é admin
    assert pool.api_calls() == 0


def test_max_length_numeric_id_outside_session_is_denied():
    _, pool, _, authorizer = setup(admin=True)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, make_session(guild_ids=(GID,)), "9" * 20)
    assert pool.api_calls() == 0


def test_bot_get_guild_receives_int_ids():
    """disnake só encontra servidores por int; passar str faria todo servidor parecer sem bot."""
    guild, _, _, authorizer = setup(admin=True)
    assert authorize(authorizer).guild_id == GID


# --------------------------------------------------------------------------- cache

def test_positive_decision_is_cached_for_reads():
    guild, pool, _, authorizer = setup(admin=True)
    authorize(authorizer)
    before = pool.api_calls()
    authorize(authorizer)
    assert pool.api_calls() == before, "segunda leitura dentro de 30 s deve vir do cache"


def test_cached_read_still_allows_within_30_seconds_after_role_removal():
    guild, _, clock, authorizer = setup(admin=True)
    authorize(authorizer)
    guild.members[UID].guild_permissions.administrator = False
    clock.advance(29)
    assert authorize(authorizer).guild_id == GID  # janela de cache aceita pelo contrato (só leituras)


def test_cache_expires_after_30_seconds():
    guild, pool, clock, authorizer = setup(admin=True)
    authorize(authorizer)
    guild.members[UID].guild_permissions.administrator = False
    clock.advance(31)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)


def test_fresh_ignores_cache_and_detects_revocation_between_requests():
    guild, _, _, authorizer = setup(admin=True)
    authorize(authorizer)
    guild.members[UID].guild_permissions.administrator = False
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, fresh=True)


def test_fresh_hits_the_gateway_even_when_cached():
    guild, _, _, authorizer = setup(admin=True)
    authorize(authorizer)
    authorize(authorizer, fresh=True)
    assert guild.calls["get_member"] == 2


def test_fresh_denial_invalidates_the_cached_positive_decision():
    guild, _, _, authorizer = setup(admin=True)
    authorize(authorizer)
    guild.members[UID].guild_permissions.administrator = False
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, fresh=True)
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)  # leitura normal não pode ressuscitar a decisão antiga


def test_negative_decisions_are_not_cached():
    guild, _, _, authorizer = setup()
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer)
    guild.members[UID].guild_permissions.manage_guild = True
    assert authorize(authorizer).guild_id == GID, "ganhar o cargo deve valer na hora (negativas não ficam em cache)"


def test_cache_is_per_user_and_per_guild():
    guild, pool, _, authorizer = setup(admin=True)
    other_guild = FakeGuild("43", "Outro", owner_id=999)
    other_guild.add_member(UID, administrator=True)
    pool.bots[0].guilds[other_guild.id] = other_guild
    authorize(authorizer)
    assert authorize(authorizer, make_session(guild_ids=("43",)), "43").guild_id == "43"
    assert other_guild.calls["get_member"] == 1, "outro servidor não pode usar a decisão em cache do servidor 42"
    guild.add_member(2002)  # outro usuário, sem permissão
    with pytest.raises(authz().GuildAccessDenied):
        authorize(authorizer, make_session(user_id="2002", guild_ids=(GID,)))


@pytest.mark.parametrize("seconds,wait,expect_cached", [(5, 4, True), (5, 6, False), (120, 100, True)])
def test_cache_seconds_is_configurable(seconds, wait, expect_cached):
    guild, pool, clock, _ = setup(admin=True)
    authorizer = authz().GuildAuthorizer(pool, clock=clock, cache_seconds=seconds)
    authorize(authorizer)
    clock.advance(wait)
    before = guild.calls["get_member"]
    authorize(authorizer)
    assert (guild.calls["get_member"] == before) is expect_cached


def test_cache_seconds_zero_disables_the_cache():
    guild, pool, clock, _ = setup(admin=True)
    authorizer = authz().GuildAuthorizer(pool, clock=clock, cache_seconds=0)
    authorize(authorizer)
    authorize(authorizer)
    assert guild.calls["get_member"] == 2


def test_cache_is_bounded():
    """Limite de entradas (interpretação: <= 10.000, como as demais stores em memória)."""
    guild, _, _, authorizer = setup(admin=True)
    for uid in range(5000, 5000 + 12_000):
        guild.add_member(uid, administrator=True)
    first_user = make_session(user_id="5000", guild_ids=(GID,))
    authorize(authorizer, first_user)
    for uid in range(5001, 5000 + 12_000):
        authorize(authorizer, make_session(user_id=str(uid), guild_ids=(GID,)))
    before = guild.calls["get_member"]
    authorize(authorizer, first_user)
    assert guild.calls["get_member"] == before + 1, "a decisão mais antiga deveria ter sido descartada pelo limite"

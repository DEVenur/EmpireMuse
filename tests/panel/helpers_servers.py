"""Dublês de pool/bot/guild/member para os testes da Etapa 3 (autorização e servidores). Sem rede."""
import asyncio
from collections import Counter
from types import SimpleNamespace

import disnake

from tests.panel.helpers import require

USER_ID = "1001"
INVITE_PERMISSIONS = 332892794064


def _response(status, reason):
    return SimpleNamespace(status=status, reason=reason)


def not_found():
    return disnake.NotFound(_response(404, "Not Found"), "Unknown Member")


def forbidden():
    return disnake.Forbidden(_response(403, "Forbidden"), "Missing Access")


def http_error():
    return disnake.HTTPException(_response(500, "Internal Server Error"), "boom")


class FakeMember:
    def __init__(self, administrator=False, manage_guild=False):
        self.guild_permissions = SimpleNamespace(administrator=administrator, manage_guild=manage_guild)


class FakeGuild:
    """Servidor do cache do gateway. `members` = cache; `fetchable` = o que a API devolve/levanta em fetch_member."""

    def __init__(self, guild_id, name="Servidor", owner_id=0, icon_hash=None):
        self.id = int(guild_id)
        self.name = name
        self.owner_id = owner_id
        self.icon = (SimpleNamespace(key=icon_hash, url=f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png")
                     if icon_hash else None)
        self.members = {}
        self.fetchable = {}
        self.calls = Counter()

    def get_member(self, user_id):
        self.calls["get_member"] += 1
        return self.members.get(user_id)

    async def fetch_member(self, user_id):
        self.calls["fetch_member"] += 1
        outcome = self.fetchable.get(user_id, not_found())
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def add_member(self, user_id, **permissions):
        self.members[int(user_id)] = FakeMember(**permissions)
        return self.members[int(user_id)]


class FakeBot:
    def __init__(self, bot_id, name="Bot", ready=True, guilds=()):
        self.application_id = int(bot_id)
        self.user = SimpleNamespace(
            id=int(bot_id), name=name,
            display_avatar=SimpleNamespace(url=f"https://cdn.discordapp.com/avatars/{bot_id}/hashbot.png"))
        self.ready = ready
        self.guilds = {g.id: g for g in guilds}
        self.calls = Counter()

    def is_ready(self):
        return self.ready

    def get_guild(self, guild_id):
        self.calls["get_guild"] += 1
        return self.guilds.get(guild_id)  # como o disnake: só encontra chaves int


class FakePool:
    def __init__(self, bots=()):
        self.bots = list(bots)
        self.database = None
        self.config = {"INVITE_PERMISSIONS": INVITE_PERMISSIONS}

    def api_calls(self):
        total = 0
        for bot in self.bots:
            total += bot.calls["get_guild"]
            for guild in bot.guilds.values():
                total += guild.calls["get_member"] + guild.calls["fetch_member"]
        return total


def make_session(user_id=USER_ID, guild_ids=("42",), name_prefix="Servidor"):
    sessions = require("panel.sessions")
    user = sessions.PanelUser(id=user_id, username=f"user{user_id}", global_name=None, avatar=None)
    guilds = tuple(sessions.ManagedGuild(id=g, name=f"{name_prefix} {g}", icon=None, permissions=8, owner=False)
                   for g in guild_ids)
    return sessions.Session(user=user, guilds=guilds, created_at=0.0, last_seen=0.0)


def raw_guild(guild_id, name, icon=None, owner=True, permissions="0"):
    """Entrada de /users/@me/guilds do Discord (dublê do fake OAuth)."""
    return {"id": str(guild_id), "name": name, "icon": icon, "owner": owner, "permissions": permissions}


def run(coro):
    return asyncio.run(coro)

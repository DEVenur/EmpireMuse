"""Fase 2, Trilha A (itens 1, 4, 5, 6 e 7 do contrato do bot) — busca padrão, mensagens de falha, aviso de novo servidor,
decodetrack na rota v4 e voz sem canal. O item 3 (local_lavalink) está em test_lavalink_download_sha256.py; o item 2 (constantes) em
test_branding.py; o item 8 (cabeçalhos de `/`) em tests/panel/test_status_page.py.

Contrato: BRIEFING-FASE2.md ("Trilha A — contrato do item 3"). Interpretações: .qa-fase2a-interp.txt.
Sem rede e sem Discord reais: dublês simples (SimpleNamespace / AsyncMock).
"""

import asyncio
from types import SimpleNamespace

import disnake
import pytest


def run(coro):
    return asyncio.run(coro)


# ============================================================================ (4) falha de busca sem repr(e)


class TestSearchFailureMessage:
    LEAK = "FriendlyException('segredo-interno-123', cause=java.io.IOException: /srv/lavalink)"

    def test_lastfm_mix_failure_has_no_repr(self):
        from empiremuse.cogs.music import Music
        from empiremuse.utils.music.errors import GenericError

        class Boom:
            async def get_similar_tracks(self, **kw):
                raise RuntimeError("detalhe-secreto-lastfm")

            async def get_artist_toptracks(self, artist):
                raise RuntimeError("detalhe-secreto-lastfm")

        cog = SimpleNamespace(bot=SimpleNamespace(pool=SimpleNamespace(last_fm=Boom())))
        with pytest.raises(GenericError) as info:
            run(Music.get_tracks(cog, "artista - faixa", ctx=None, user=SimpleNamespace(id=1), mix=True))
        assert "detalhe-secreto-lastfm" not in info.value.text and "RuntimeError" not in info.value.text


# ============================================================================ (5) misc.py: aviso de novo servidor


def perms(**kw):
    return SimpleNamespace(**{"send_messages": True, "embed_links": True, **kw})


def make_guild(channel):
    me = SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False))
    return SimpleNamespace(
        id=1,
        name="Servidor",
        members=[],
        me=me,
        system_channel=channel,
        rules_channel=None,
        public_updates_channel=None,
    )


def make_channel(permissions, send_error=None):
    sent = []

    async def send(*args, **kwargs):
        sent.append(kwargs)
        if send_error:
            raise send_error

    channel = SimpleNamespace(id=55, send=send, permissions_for=lambda member: permissions)
    channel.sent = sent
    return channel


def welcome(channel):
    from empiremuse.cogs.misc import Misc

    bot = SimpleNamespace(
        pool=SimpleNamespace(bots=[]),
        get_command=lambda name: None,
        default_prefix="!",
        user=SimpleNamespace(id=9),
        is_reserve=False,
        config={"SUPPORT_SERVER": "", "INTERACTION_COMMAND_ONLY": True, "MULTIVOICE_VIDEO_DEMO_URL": ""},
        get_color=lambda: 0x8B5CF6,
    )
    run(Misc.guild_add(SimpleNamespace(bot=bot), make_guild(channel)))


def forbidden():
    return disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")


class TestWelcomeMessagePermissions:
    def test_forbidden_does_not_raise(self):
        welcome(make_channel(perms(), send_error=forbidden()))

"""KI-27 — caracterização de `empiremuse/utils/others.py` (utilitários de comandos: contexto, paginação, emojis de fonte, fila).

Fixa o comportamento atual, sem mudar produção. Sem Discord real: dublês (SimpleNamespace / MagicMock / AsyncMock).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import disnake
from disnake.ext import commands

from empiremuse.utils import others


def run(coro):
    return asyncio.run(coro)


# ============================================================================ funções puras


class TestSmallHelpers:
    def test_pool_command_defaults(self):
        async def cmd(ctx):
            pass

        comando = others.PoolCommand(cmd)
        assert (comando.pool_return_first, comando.pool_only_voiced, comando.pool_check_player) == (False, False, True)


# ============================================================================ fila


def track(title, unique_id):
    return SimpleNamespace(title=title, unique_id=unique_id)


class TestQueueTrackIndex:
    def setup_method(self):
        self.player = SimpleNamespace(
            queue=[track("Imagine Dragons - Believer", "a"), track("Queen - Bohemian Rhapsody", "b")],
            queue_autoplay=[track("Queen - Under Pressure", "c")],
        )
        self.bot = SimpleNamespace(music=SimpleNamespace(players={1: self.player}))
        self.inter = SimpleNamespace(guild_id=1)

    def find(self, query, **kwargs):
        return others.queue_track_index(self.inter, self.bot, query, **kwargs)

    def test_substring_match_per_word(self):
        resultado = self.find("queen bohem")
        assert [(i, t.unique_id) for i, t in resultado] == [(1, "b")]


# ============================================================================ argparse, interações e paginador


class TestEmbedPaginator:
    """`disnake.ui.View` exige um loop em execução: cada cenário roda dentro de uma corrotina."""

    @staticmethod
    def scenario(body, pages=3):
        async def main():
            ctx = SimpleNamespace(author=SimpleNamespace(mention="<@1>"))
            view = others.EmbedPaginator(ctx, [disnake.Embed(title=str(n)) for n in range(pages)])
            return await body(view, ctx)

        return run(main())

    @staticmethod
    def interaction(author):
        return SimpleNamespace(
            author=author,
            send=AsyncMock(),
            message=SimpleNamespace(delete=AsyncMock()),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

    def test_next_wraps_around_to_the_first_page(self):
        async def body(view, ctx):
            inter = self.interaction(ctx.author)
            await view.next.callback(inter)
            assert view.current == 1
            await view.next.callback(inter)
            assert view.current == 0
            assert inter.response.edit_message.await_args.kwargs["embed"].title == "0"

        self.scenario(body, pages=2)


# ============================================================================ CustomContext


# ============================================================================ check_cmd / send_message


class TestCheckCmd:
    def cmd(self, checks=(), cooldown=False, retry_after=None):
        bucket = SimpleNamespace(update_rate_limit=lambda: retry_after)
        buckets = SimpleNamespace(_cooldown=cooldown, get_bucket=lambda inter: bucket, type=commands.BucketType.user)
        return SimpleNamespace(checks=list(checks), _buckets=buckets, can_run=AsyncMock())

    def test_cooldown_not_hit_passes(self):
        run(others.check_cmd(self.cmd(cooldown=True, retry_after=None), SimpleNamespace()))

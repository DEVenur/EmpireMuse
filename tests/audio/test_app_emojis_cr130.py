"""Emojis de aplicação (#130), achados do CodeRabbit: a cog sobe o sync ao carregar (cogs carregam depois do ``on_ready``), ``cog_unload`` cancela sem
sobrescrever o mapa, e as views usam o bot que ENVIA (``ctx.bot`` / ``inter.bot``), não um bot qualquer.
"""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import disnake
import pytest

from empiremuse.cogs import app_emojis as cog_modulo
from tests.audio.test_app_emojis_integracao import ID_A, ID_B, ids_do_bot, mapa_do_bot
from tests.support.emojis_app import NOMES

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

MAPA = {nome: f"<:{nome}:{100000000000000000 + i}>" for i, nome in enumerate(NOMES)}


def novo_bot(*, pronto: bool, principal: bool = True):
    """Bot falso cujo ``add_cog`` imita o do disnake: injeta a cog e chama ``cog_load`` (se for corrotina, vira tarefa)."""
    cogs = []
    config = {"APP_EMOJIS_GUILD_BOTS": False}
    bot = SimpleNamespace(
        identifier="principal",
        app_emojis={},
        config=config,
        loop=asyncio.get_running_loop(),
        user=SimpleNamespace(id=7),
        is_ready=lambda: pronto,
        cogs_adicionadas=cogs,
    )

    def add_cog(cog):
        cogs.append(cog)
        carregar = getattr(cog, "cog_load", None)
        if carregar is not None:
            resultado = carregar()
            if inspect.isawaitable(resultado):
                bot.loop.create_task(resultado)

    bot.add_cog = add_cog
    bot.pool = SimpleNamespace(
        config=config, bots=[bot] if principal else [], guild_bots={} if principal else {"1": [bot]}
    )
    return bot


async def ceder(vezes: int = 10) -> None:
    for _ in range(vezes):
        await asyncio.sleep(0)


async def disparar_on_ready(cog) -> None:
    (ouvinte,) = [metodo for nome, metodo in cog.get_listeners() if nome == "on_ready"]
    await ouvinte()
    await ceder()


@pytest.fixture
def sync(monkeypatch) -> AsyncMock:
    falso = AsyncMock(return_value=dict(MAPA))
    monkeypatch.setattr(cog_modulo, "sync_app_emojis", falso)
    return falso


class TestSyncAoCarregar:
    """r4395895127: as cogs carregam em ``initial_setup`` DEPOIS do ``wait_until_ready``, então o primeiro ``on_ready`` já passou."""

    async def test_a_cog_loaded_after_the_bot_is_ready_starts_the_sync_without_on_ready(self, sync):
        bot = novo_bot(pronto=True)

        cog_modulo.setup(bot)
        await ceder()

        assert sync.await_count == 1 and bot.app_emojis == MAPA

    async def test_a_cog_loaded_before_the_bot_is_ready_waits_for_on_ready(self, sync):
        bot = novo_bot(pronto=False)

        cog_modulo.setup(bot)
        await ceder()
        assert sync.await_count == 0

        await disparar_on_ready(bot.cogs_adicionadas[0])
        assert sync.await_count == 1

    async def test_loaded_ready_and_then_on_ready_still_runs_one_sync(self, sync):
        bot = novo_bot(pronto=True)

        cog_modulo.setup(bot)
        await ceder()
        await disparar_on_ready(bot.cogs_adicionadas[0])

        assert sync.await_count == 1

    async def test_a_reload_of_a_ready_bot_does_not_run_a_second_sync(self, sync):
        bot = novo_bot(pronto=True)

        cog_modulo.setup(bot)
        await ceder()
        bot.cogs_adicionadas.clear()
        cog_modulo.setup(bot)
        await ceder()

        assert sync.await_count == 1 and bot.app_emojis == MAPA

    async def test_a_guild_bot_loaded_ready_does_not_sync_by_default(self, sync):
        bot = novo_bot(pronto=True, principal=False)

        cog_modulo.setup(bot)
        await ceder()

        assert sync.await_count == 0

    async def test_a_guild_bot_loaded_ready_syncs_with_the_opt_in(self, sync):
        bot = novo_bot(pronto=True, principal=False)
        bot.config["APP_EMOJIS_GUILD_BOTS"] = True

        cog_modulo.setup(bot)
        await ceder()

        assert sync.await_count == 1


class TestDescarregar:
    """r4395895130: ``cog_unload`` cancela a tarefa de sync, e um sync cancelado nunca sobrescreve ``bot.app_emojis``."""

    async def test_unloading_cancels_the_running_sync_and_the_map_stays_empty(self, monkeypatch):
        liberar = asyncio.Event()
        cancelado = []

        async def lento(*a, **k):
            try:
                await liberar.wait()
            except asyncio.CancelledError:
                cancelado.append(True)
                raise
            return dict(MAPA)

        monkeypatch.setattr(cog_modulo, "sync_app_emojis", lento)
        bot = novo_bot(pronto=True)
        cog_modulo.setup(bot)
        await ceder()

        bot.cogs_adicionadas[0].cog_unload()
        await ceder()
        liberar.set()
        await ceder()

        assert cancelado == [True] and bot.app_emojis == {}

    async def test_a_sync_that_ignores_the_cancellation_and_returns_never_overwrites_the_map(self, monkeypatch):
        liberar = asyncio.Event()

        async def teimoso(*a, **k):
            try:
                await liberar.wait()
            except asyncio.CancelledError:
                pass
            return dict(MAPA)

        monkeypatch.setattr(cog_modulo, "sync_app_emojis", teimoso)
        bot = novo_bot(pronto=True)
        cog_modulo.setup(bot)
        await ceder()

        bot.cogs_adicionadas[0].cog_unload()
        liberar.set()
        await ceder()

        assert bot.app_emojis == {}

    async def test_unloading_without_a_running_sync_never_raises(self, sync):
        bot = novo_bot(pronto=False)
        cog_modulo.setup(bot)

        bot.cogs_adicionadas[0].cog_unload()

    async def test_unloading_after_the_sync_finished_keeps_the_map(self, sync):
        bot = novo_bot(pronto=True)
        cog_modulo.setup(bot)
        await ceder()

        bot.cogs_adicionadas[0].cog_unload()
        await ceder()

        assert bot.app_emojis == MAPA


def ctx_do_bot(base: int):
    bot = SimpleNamespace(app_emojis=mapa_do_bot(base), pool=SimpleNamespace(emoji_data={}))
    return SimpleNamespace(bot=bot, author=SimpleNamespace(id=1, mention="<@1>"))


def emojis_dos_botoes(view) -> set[str]:
    achados = set()
    for item in view.children:
        if getattr(item, "emoji", None) is not None:
            achados.add(str(item.emoji))
        for opcao in getattr(item, "options", None) or []:
            if getattr(opcao, "emoji", None) is not None:
                achados.add(str(opcao.emoji))
    return achados


class TestViewHelp:
    """r4395895136: a ``ViewHelp`` só tem ``self.ctx``; os emojis vêm de ``ctx.bot`` (nada de ``self.bot``)."""

    def view(self, ctx, categoria="Musica"):
        from empiremuse.cogs.help_cog import ViewHelp

        return ViewHelp(
            ctx,
            [("Musica", "🎵"), ("Outra", "🎶")],
            get_cmd=AsyncMock(return_value=disnake.Embed(description="x")),
            main_embed=disnake.Embed(description="m"),
            cmd_list={"Musica": {"cmds": [1, 2, 3], "emoji": "🎵"}, "Outra": {"cmds": [1, 2], "emoji": "🎶"}},
            category_cmd=categoria,
        )

    async def test_building_the_buttons_of_a_category_uses_the_ctx_bot_emojis(self):
        ctx = ctx_do_bot(ID_A)

        emojis = emojis_dos_botoes(self.view(ctx))

        mapa = ctx.bot.app_emojis
        assert {mapa["arrow_left"], mapa["arrow_right"], mapa["leftwards_arrow_with_hook"]} <= emojis

    async def test_picking_a_category_does_not_raise_and_uses_the_ctx_bot_emojis(self):
        ctx = ctx_do_bot(ID_A)
        view = self.view(ctx, categoria=None)
        interacao = SimpleNamespace(
            data=SimpleNamespace(values=["Outra"]), response=SimpleNamespace(edit_message=AsyncMock())
        )

        await view.callback_help(interacao)

        mapa = ctx.bot.app_emojis
        assert {mapa["arrow_left"], mapa["arrow_right"]} <= emojis_dos_botoes(view)
        interacao.response.edit_message.assert_awaited_once()

    async def test_two_bots_never_share_the_help_emojis(self):
        do_a = emojis_dos_botoes(self.view(ctx_do_bot(ID_A)))
        do_b = emojis_dos_botoes(self.view(ctx_do_bot(ID_B)))

        assert not any(i in " ".join(do_a) for i in ids_do_bot(ID_B)) and not any(
            i in " ".join(do_b) for i in ids_do_bot(ID_A)
        )


class TestServerManager:
    """r4395895143: os botões usam o bot que ENVIA (``self.inter.bot``), não o bot selecionado (``self.bot``)."""

    def painel(self, enviador, selecionado):
        from empiremuse.cogs.server_manager import ServerManagerView

        v = ServerManagerView.__new__(ServerManagerView)
        guilds = [SimpleNamespace(id=n) for n in (1, 2, 3)]
        v.inter = SimpleNamespace(bot=enviador, guild_id=1, user=SimpleNamespace(id=1))
        v.bot = selecionado
        v.pages = [guilds[:2], guilds[2:]]
        v.current_guild = guilds[0]
        v.children = []
        v.add_item = v.children.append
        v.build_select = lambda: disnake.ui.Select(options=[disnake.SelectOption(label="a", value="a")])
        selecionado.pool = SimpleNamespace(get_guild_bots=lambda _id: [selecionado])
        return v

    def bot_com(self, base):
        return SimpleNamespace(app_emojis=mapa_do_bot(base), pool=SimpleNamespace(emoji_data={}))

    async def test_the_buttons_use_the_emojis_of_the_sending_bot(self):
        enviador, selecionado = self.bot_com(ID_A), self.bot_com(ID_B)
        v = self.painel(enviador, selecionado)

        v.rebuild_components()

        emojis = {str(b.emoji) for b in v.children if getattr(b, "emoji", None) is not None}
        assert {
            enviador.app_emojis["arrow_left"],
            enviador.app_emojis["arrow_right"],
            enviador.app_emojis["stop"],
        } <= emojis

    async def test_nothing_of_the_selected_bot_reaches_the_buttons(self):
        enviador, selecionado = self.bot_com(ID_A), self.bot_com(ID_B)
        v = self.painel(enviador, selecionado)

        v.rebuild_components()

        texto = " ".join(str(b.emoji) for b in v.children if getattr(b, "emoji", None) is not None)
        assert not any(i in texto for i in ids_do_bot(ID_B))

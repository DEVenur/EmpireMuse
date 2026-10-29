"""Canal de pedidos único (item 11, P4, S7, S7b, S-V8, S10): só o bot do painel trata o que é digitado, o botão e o modal agem SÓ no
player da call de quem usa (resolvido de novo no envio), o painel edita no máximo a cada 3 s e a call privada nunca mostra faixa."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.music_cog import controller_buttons, song_request_steps
from empiremuse.music_cog.controller_dispatch import ControllerDispatchMixin
from empiremuse.utils import request_panel as panel_module
from empiremuse.utils.music.checks import pick_request_bot, resolve_player
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions.request_panel import MSG_JOIN_A_CALL
from empiremuse.utils.request_panel import RequestPanel, entry_for, is_private

pytestmark = pytest.mark.critical

GID, PANEL_CHANNEL, PANEL_MESSAGE = 111, 22, 555


def make_bot(bot_id, identifier, *, call=None, ready=True, exclusive=None, in_guild=True, static=True):
    """Um bot do pool: ``call`` = id da call onde ele toca (``None`` = livre)."""
    voice = SimpleNamespace(channel=SimpleNamespace(id=call, name=f"call-{call}")) if call else None
    guild = SimpleNamespace(id=GID, me=SimpleNamespace(voice=voice), get_member=lambda _id: None)
    player = (
        SimpleNamespace(guild=guild, static=static, is_closing=False, current=None, queue=[], paused=False)
        if call
        else None
    )
    cog = SimpleNamespace(bot_id=bot_id, player_controller=AsyncMock(), play=SimpleNamespace(callback=AsyncMock()))
    return SimpleNamespace(
        identifier=identifier,
        user=SimpleNamespace(id=bot_id, display_name=identifier),
        bot_ready=ready,
        exclusive_guild_id=exclusive,
        music=SimpleNamespace(players={GID: player} if player else {}),
        get_guild=lambda gid: guild if in_guild and gid == GID else None,
        get_cog=lambda name: cog,
        cog=cog,
    )


def make_pool(*bots):
    return SimpleNamespace(get_all_bots=lambda: list(bots))


def member(call=None):
    voice = SimpleNamespace(channel=SimpleNamespace(id=call)) if call else None
    return SimpleNamespace(voice=voice, id=7)


# ---------------------------------------------------------------------- S-V8: o player é o da call de quem apertou


@pytest.mark.parametrize(
    ("caller_call", "expected"),
    [(100, "TOKEN"), (200, "TOKEN_2"), (300, None), (None, None)],
    ids=["first_bots_call", "second_bots_call", "call_without_player", "not_in_a_call"],
)
def test_resolve_player_returns_the_player_of_the_callers_call_and_never_another(caller_call, expected):
    pool = make_pool(make_bot(2, "TOKEN_2", call=200), make_bot(1, "TOKEN", call=100))
    resolved = resolve_player(pool, GID, member(caller_call))
    assert (resolved[0].identifier if resolved else None) == expected


def test_a_bot_without_a_player_or_logged_out_is_never_chosen():
    free, logged_out = make_bot(1, "TOKEN"), make_bot(2, "TOKEN_2", call=200)
    logged_out.user = None
    assert resolve_player(make_pool(free, logged_out), GID, member(200)) is None


@pytest.mark.parametrize(
    ("bots", "caller_call", "expected"),
    [
        ([(1, "TOKEN", 100), (2, "TOKEN_2", None)], 100, "TOKEN"),  # o que já está na call de quem pediu
        ([(1, "TOKEN", 100), (2, "TOKEN_2", None)], None, "TOKEN_2"),  # senão o 1º livre
        ([(1, "TOKEN", None), (2, "TOKEN_2", None)], None, "TOKEN"),  # ordem do identifier
        ([(1, "TOKEN", 100), (2, "TOKEN_2", 200)], 300, None),  # todos ocupados em outras calls
    ],
)
def test_a_request_goes_to_the_bot_in_the_callers_call_else_the_first_free_one(bots, caller_call, expected):
    pool = make_pool(*[make_bot(i, ident, call=call) for i, ident, call in reversed(bots)])
    chosen = pick_request_bot(pool, GID, member(caller_call))
    assert (chosen.identifier if chosen else None) == expected


@pytest.mark.parametrize(
    "unfit",
    [{"ready": False}, {"exclusive": 999}, {"in_guild": False}],
    ids=["not_ready", "exclusive_of_another_server", "not_in_the_server"],
)
def test_a_bot_that_cannot_serve_here_is_skipped_when_picking_a_free_one(unfit):
    pool = make_pool(make_bot(1, "TOKEN", **unfit), make_bot(2, "TOKEN_2"))
    assert pick_request_bot(pool, GID, member(None)).identifier == "TOKEN_2"


# ---------------------------------------------------------------------- S7: só o bot do painel trata o que é digitado


class Sentinel(Exception):
    pass


def typed_request(*, panel_bot):
    request = SimpleNamespace(is_panel_bot=AsyncMock(return_value=panel_bot))
    bot = SimpleNamespace(
        pool=SimpleNamespace(servers=SimpleNamespace(request=request)),
        get_channel=MagicMock(side_effect=Sentinel),  # só chega aqui quem passou do portão
    )
    channel = MagicMock(spec=disnake.TextChannel)
    channel.id = PANEL_CHANNEL
    message = SimpleNamespace(channel=channel, guild=SimpleNamespace(id=GID), id=1, author=SimpleNamespace(id=7))
    req = SimpleNamespace(
        data={"player_controller": {"channel": str(PANEL_CHANNEL), "message_id": str(PANEL_MESSAGE)}},
        message=message,
        player=None,
    )
    return SimpleNamespace(bot=bot), req, request


@pytest.mark.asyncio
async def test_a_message_typed_in_the_shared_channel_is_ignored_by_every_bot_but_the_panel_bot():
    self_, req, request = typed_request(panel_bot=False)
    assert await song_request_steps._sr_validate_channel(self_, req) is True  # ignora
    request.is_panel_bot.assert_awaited_once_with(GID, self_.bot)

    self_, req, _ = typed_request(panel_bot=True)
    with pytest.raises(Sentinel):  # o bot do painel passa do portão e segue o fluxo de sempre
        await song_request_steps._sr_validate_channel(self_, req)


@pytest.mark.asyncio
async def test_a_store_that_fails_means_not_the_panel_bot_better_to_ignore_than_to_answer_twice():
    self_, req, request = typed_request(panel_bot=True)
    request.is_panel_bot.side_effect = GenericError("indisponível")
    assert await song_request_steps._sr_validate_channel(self_, req) is True


# ---------------------------------------------------------------------- S7/S-V8: clique no painel


def click(*, call, panel_bot=True, message_id=PANEL_MESSAGE):
    """Um clique no painel recebido pelo bot ``TOKEN`` (o do painel); a pessoa está na ``call`` dada."""
    me = make_bot(1, "TOKEN", call=100)
    other = make_bot(2, "TOKEN_2", call=200)
    request = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(message_id=PANEL_MESSAGE)),
        is_panel_bot=AsyncMock(return_value=panel_bot),
    )
    me.pool = make_pool(me, other)
    me.pool.servers = SimpleNamespace(request=request)
    interaction = SimpleNamespace(
        guild_id=GID, message=SimpleNamespace(id=message_id), author=member(call), send=AsyncMock()
    )
    req = SimpleNamespace(interaction=interaction, control="pause_resume")
    return SimpleNamespace(bot=me), req, other, interaction


@pytest.mark.asyncio
async def test_a_click_from_someone_in_no_call_only_warns_and_changes_nothing():
    self_, req, other, interaction = click(call=None)
    assert await controller_buttons._pc_route_panel_click(self_, req) is True
    interaction.send.assert_awaited_once_with(MSG_JOIN_A_CALL, ephemeral=True)
    assert not hasattr(interaction, "music_bot")
    other.cog.player_controller.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_click_acts_on_the_player_of_the_callers_call_even_if_another_bot_received_it():
    self_, req, other, interaction = click(call=200)

    assert await controller_buttons._pc_route_panel_click(self_, req) is True

    other.cog.player_controller.assert_awaited_once_with(interaction, "pause_resume")
    assert interaction.music_bot is other  # e nunca o player da call 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"call": 100}, {"call": 200, "message_id": 999}, {"call": 200, "panel_bot": False}],
    ids=["own_call", "another_message", "not_the_panel_bot"],
)
async def test_a_click_is_left_to_the_normal_flow_when_it_is_not_a_cross_bot_panel_click(kwargs):
    self_, req, other, interaction = click(**kwargs)

    assert await controller_buttons._pc_route_panel_click(self_, req) is False
    other.cog.player_controller.assert_not_awaited()
    interaction.send.assert_not_awaited()


# ---------------------------------------------------------------------- S7b: pedido (e modal) resolvido NO ENVIO


def request_inter(author_call, channel_id=PANEL_CHANNEL):
    return SimpleNamespace(
        guild_id=GID, channel_id=channel_id, channel=SimpleNamespace(parent_id=None), author=member(author_call)
    )


def executor_world(me=None, other=None):
    me = me or make_bot(1, "TOKEN")
    other = other or make_bot(2, "TOKEN_2", call=200)
    me.pool = make_pool(me, other)
    request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(channel=PANEL_CHANNEL)))
    me.pool.servers = SimpleNamespace(request=request)
    dispatch = ControllerDispatchMixin.__new__(ControllerDispatchMixin)
    dispatch.bot = me
    return dispatch, me, other


@pytest.mark.asyncio
async def test_the_modal_is_resolved_again_on_submit_so_a_changed_call_acts_on_the_new_players_bot():  # S7b
    dispatch, me, other = executor_world()

    first = request_inter(200)  # quando abriu o modal estava na call do TOKEN_2...
    assert await dispatch.request_executor(first) is other.cog and first.music_bot is other

    second = request_inter(None)  # ...ao enviar já saiu: ninguém toca para ele, o 1º livre atende (o próprio TOKEN)
    assert await dispatch.request_executor(second) is dispatch and second.music_bot is me


@pytest.mark.asyncio
async def test_outside_the_shared_channel_nothing_is_rerouted_and_with_every_bot_busy_the_person_is_told():
    dispatch, me, other = executor_world()
    elsewhere = request_inter(200, channel_id=999)
    assert await dispatch.request_executor(elsewhere) is dispatch and not hasattr(elsewhere, "music_bot")

    busy_dispatch, _, _ = executor_world(make_bot(1, "TOKEN", call=100), make_bot(2, "TOKEN_2", call=200))
    with pytest.raises(GenericError):
        await busy_dispatch.request_executor(request_inter(300))


# ---------------------------------------------------------------------- S10: call privada e entrada do painel


def voice_channel(*, view, connect):
    perms = SimpleNamespace(view_channel=view, connect=connect)
    guild = SimpleNamespace(default_role="everyone")
    return SimpleNamespace(
        guild=guild,
        name="Sala secreta",
        permissions_for=lambda role: perms if role == "everyone" else None,
    )


@pytest.mark.parametrize(
    ("view", "connect", "private"),
    [(True, True, False), (False, True, True), (True, False, True), (False, False, True)],
)
def test_a_call_that_everyone_cannot_see_or_join_is_private(view, connect, private):
    assert is_private(voice_channel(view=view, connect=connect)) is private
    assert is_private(object()) is True  # sem como saber: privada


def test_the_panel_entry_of_a_private_call_has_no_track_link_or_requester():
    bot = make_bot(1, "TOKEN", call=100)
    player = bot.music.players[GID]
    player.guild.me.voice.channel = voice_channel(view=False, connect=True)
    player.current = SimpleNamespace(title="Faixa secreta", uri="https://exemplo.com/secreta", requester=7)
    entry = entry_for(bot, player)
    assert entry.private and entry.title is None and entry.url is None and entry.requester is None

    player.guild.me.voice.channel = voice_channel(view=True, connect=True)
    assert entry_for(bot, player).title == "Faixa secreta"
    player.guild.me.voice = None
    assert entry_for(bot, player) is None  # player sem call não vira bloco


# ---------------------------------------------------------------------- RequestPanel: quem conta, edição agrupada, reenvio


def panel_world(*bots):
    pool = make_pool(*bots)
    request = SimpleNamespace(get=AsyncMock(), elect=AsyncMock(), set=AsyncMock(), panel_bot=AsyncMock())
    pool.servers = SimpleNamespace(request=request)
    return RequestPanel(pool), pool


def test_only_static_players_that_are_not_closing_count_and_the_list_takes_over_with_two_or_more():
    one, two = make_bot(1, "TOKEN", call=100), make_bot(2, "TOKEN_2", call=200)
    panel, _ = panel_world(two, one)
    assert [b.identifier for b, _ in panel.players(GID)] == ["TOKEN", "TOKEN_2"] and panel.takes_over(GID)

    two.music.players[GID].static = False
    assert not panel.takes_over(GID)
    two.music.players[GID].static, one.music.players[GID].is_closing = True, True
    assert [b.identifier for b, _ in panel.players(GID)] == ["TOKEN_2"] and not panel.takes_over(GID)


@pytest.mark.asyncio
async def test_the_panel_is_edited_at_most_once_every_three_seconds_and_changes_in_the_window_become_one_edit(
    monkeypatch,
):
    panel, _ = panel_world()
    now = [1_000.0]
    monkeypatch.setattr(panel_module.time, "monotonic", lambda: now[0])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(panel_module.asyncio, "sleep", fake_sleep)
    panel._draw = AsyncMock()

    await panel.refresh(GID)  # nunca editou: edita já
    assert panel._draw.await_count == 1
    now[0] += 1.0
    await panel.refresh(GID)  # dentro da janela: agenda UMA edição
    await panel.refresh(GID)
    await panel.refresh(GID)
    assert panel._draw.await_count == 1 and len(panel._pending) == 1

    await panel._pending[GID]
    assert panel._draw.await_count == 2 and sleeps and 1.9 <= sleeps[0] <= 2.1  # os 3 s menos o 1 s já passado


@pytest.mark.asyncio
async def test_a_failing_draw_is_logged_by_type_only_and_never_raises(caplog):
    panel, _ = panel_world()
    panel._draw = AsyncMock(side_effect=RuntimeError("falha secreta no desenho"))
    await panel.refresh(GID, now=True)
    assert "falha secreta" not in caplog.text and "RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_resending_is_done_by_the_panel_bot_and_the_new_message_id_is_saved(monkeypatch):
    sent = SimpleNamespace(id=777)
    panel_bot = make_bot(2, "TOKEN_2")
    old = SimpleNamespace(delete=AsyncMock())
    channel = SimpleNamespace(get_partial_message=lambda mid: old)
    panel_bot.get_channel = lambda cid: channel
    panel, pool = panel_world(panel_bot)
    pool.servers.request.get.return_value = SimpleNamespace(channel=PANEL_CHANNEL, message_id=PANEL_MESSAGE, current=3)
    pool.servers.request.panel_bot.return_value = panel_bot
    idle = AsyncMock(return_value=sent)
    import empiremuse.utils.others as others

    monkeypatch.setattr(others, "send_idle_embed", idle)

    assert await panel.resend(GID, replace_message_id=PANEL_MESSAGE) is sent

    assert idle.await_args.args[0] is channel and idle.await_args.kwargs["bot"] is panel_bot
    assert pool.servers.request.set.await_args.args[:3] == (GID, PANEL_CHANNEL, 777)
    old.delete.assert_awaited_once()  # a mensagem do bot que saiu


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "changed", "resends"),
    [(PANEL_CHANNEL, True, True), (PANEL_CHANNEL, False, False), (None, True, False)],
    ids=["panel_bot_changed", "same_panel_bot", "no_request_channel"],
)
async def test_a_roster_change_resends_only_when_the_panel_bot_changed_and_there_is_a_channel(
    channel, changed, resends
):
    panel, pool = panel_world(make_bot(2, "TOKEN_2"))
    pool.servers.request.get.return_value = SimpleNamespace(channel=channel, message_id=PANEL_MESSAGE)
    pool.servers.request.elect.return_value = SimpleNamespace(bot=object(), changed=changed)
    panel.resend = AsyncMock()

    await panel.on_roster_change(GID)

    assert panel.resend.await_count == (1 if resends else 0)
    if resends:
        panel.resend.assert_awaited_once_with(GID, replace_message_id=PANEL_MESSAGE)


@pytest.mark.asyncio
async def test_forget_schedules_a_refresh_for_the_server():
    panel, _ = panel_world()
    panel.refresh = AsyncMock()
    panel.forget(GID)
    await asyncio.sleep(0)
    panel.refresh.assert_awaited_once_with(GID)

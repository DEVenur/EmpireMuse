"""Falha de reprodução do YouTube (Lavalink + youtube-plugin): causa casada em qualquer posição, uma nova tentativa da mesma faixa
e recuperação também para faixas do Spotify espelhadas no YouTube. As causas são as reais do spring.log do Lavalink (2.1.1)."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.models import event_steps
from empiremuse.utils.music.models.event_steps import _he_dispatch

pytestmark = pytest.mark.asyncio

ALL_CLIENTS = (
    "dev.lavalink.youtube.AllClientsFailedException: (yts.version: 2be8e542d3f6f178e048dca565892684c2e40177) "
    "All clients failed to load the item."
)
ALL_CLIENTS_TIMEOUT = ALL_CLIENTS + "\nClient [TVHTML5] failed: java.net.SocketTimeoutException: Read timed out"
ALL_CLIENTS_STATUS = ALL_CLIENTS + "\nClient [TVHTML5] failed: PersistentHttpException: Not success status code: 403"
OTHER = "java.lang.RuntimeException: falha qualquer"


@pytest.fixture(autouse=True)
def sleep(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(event_steps.asyncio, "sleep", mock)
    return mock


def make_track(source="spotify", uri="https://open.spotify.com/track/abc"):
    return SimpleNamespace(
        title="Artista - Musica",
        single_title="Musica",
        uri=uri,
        search_uri=None,
        url=uri,
        duration=200_000,
        source_name=source,
        info={"sourceName": source},
        thumb=None,
        track_loops=0,
        autoplay=False,
        is_stream=False,
    )


def make_player(track, nodes=()):
    node = SimpleNamespace(identifier="N1", version=4, is_available=True, search_providers=["ytsearch"])
    return SimpleNamespace(
        guild=SimpleNamespace(id=1, name="S", me=SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(id=9)))),
        channel_id=9,
        node=node,
        bot=SimpleNamespace(
            dispatch=MagicMock(),
            user="bot",
            identifier="b",
            pool=None,
            get_cog=lambda n: None,
            music=SimpleNamespace(nodes={n.identifier: n for n in nodes}),
        ),
        text_channel=None,
        controller_mode=False,
        locked=False,
        current=track,
        last_track=track,
        position=0,
        last_position=0,
        last_update=0,
        queue=deque(),
        update=False,
        failed_tracks=[],
        keep_connected=False,
        set_command_log=MagicMock(),
        process_next=AsyncMock(),
        process_save_queue=AsyncMock(),
        update_stage_topic=AsyncMock(),
        report_error=AsyncMock(),
        change_node=AsyncMock(),
    )


def fail(player, cause, message="Something went wrong"):
    return wavelink.TrackException(
        {
            "track": player.current,
            "player": player,
            "node": player.node,
            "error": "falha",
            "exception": {"cause": cause, "message": message, "severity": "suspicious"},
        }
    )


def start(player):
    return wavelink.TrackStart({"track": player.current, "player": player, "node": player.node})


@pytest.mark.parametrize("cause", [ALL_CLIENTS, ALL_CLIENTS_TIMEOUT, ALL_CLIENTS_STATUS])
async def test_the_same_spotify_track_is_retried_once_after_two_seconds(cause, sleep):
    track = make_track()
    player = make_player(track)

    await _he_dispatch(player, fail(player, cause))

    sleep.assert_any_call(2)
    player.process_next.assert_awaited_once()
    assert list(player.queue) == [track]
    assert player.locked is False
    player.report_error.assert_not_awaited()
    assert track not in player.failed_tracks


async def test_the_retry_marker_is_also_found_in_the_message():
    track = make_track()
    player = make_player(track)

    await _he_dispatch(player, fail(player, OTHER, message="Read timed out"))

    assert list(player.queue) == [track]
    player.report_error.assert_not_awaited()


async def test_a_second_all_clients_failure_reports_and_skips_the_track():
    track = make_track()
    player = make_player(track)
    await _he_dispatch(player, fail(player, ALL_CLIENTS))
    player.queue.clear()
    player.process_next.reset_mock()
    player.current = track

    await _he_dispatch(player, fail(player, ALL_CLIENTS))

    player.report_error.assert_awaited_once()
    assert track in player.failed_tracks
    assert track not in player.queue
    player.process_next.assert_awaited_once()


async def test_a_start_in_between_gives_the_track_a_new_retry():
    track = make_track()
    player = make_player(track)
    await _he_dispatch(player, fail(player, ALL_CLIENTS))
    player.queue.clear()
    player.current = track
    await _he_dispatch(player, start(player))
    player.process_next.reset_mock()
    player.current = track

    await _he_dispatch(player, fail(player, ALL_CLIENTS))

    assert list(player.queue) == [track]
    player.report_error.assert_not_awaited()


async def test_another_cause_keeps_the_old_behavior(sleep):
    track = make_track()
    player = make_player(track)

    await _he_dispatch(player, fail(player, OTHER))

    assert track in player.failed_tracks
    player.report_error.assert_awaited_once()
    assert 2 not in [c.args[0] for c in sleep.await_args_list]


@pytest.mark.parametrize(
    "cause",
    [
        "x: java.net.SocketTimeoutException: Connect timed out",
        "java.lang.IllegalStateException: Failed to get media URL: wrapped java.io.EOFException",
    ],
)
async def test_known_retryable_markers_match_anywhere_in_the_cause(cause):
    track = make_track(source="soundcloud")
    player = make_player(track)

    await _he_dispatch(player, fail(player, cause))

    assert list(player.queue) == [track]  # volta para a fila pela via geral de falhas de rede
    assert track not in player.failed_tracks


async def test_a_spotify_track_mirrored_to_youtube_recovers_via_native_youtube_node():
    track = make_track()
    other = SimpleNamespace(identifier="N2", is_available=True, search_providers=["ytsearch"])
    player = make_player(track, nodes=[other])
    player.node.search_providers = ["ytsearch"]
    player.bot.music.nodes = {"N1": player.node, "N2": other}
    await _he_dispatch(player, fail(player, ALL_CLIENTS))  # a nova tentativa da mesma faixa é consumida
    player.queue.clear()
    player.current = track

    await _he_dispatch(player, fail(player, ALL_CLIENTS))

    player.change_node.assert_awaited_once_with("N2")

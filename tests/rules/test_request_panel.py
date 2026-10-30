"""Regras puras do canal de pedidos único (item 11, P4): quem é o bot do painel, a call privada nunca mostra faixa (S10),
o botão age só no player da call de quem apertou (S7) e a migração copia só o canal do principal."""

import pytest

from empiremuse.rules.request_panel import (
    PANEL_REFRESH_MS,
    PAUSED,
    PLAYING,
    PanelPeer,
    choose_player,
    elect_panel_bot,
    make_entry,
    refresh_wait_ms,
)
from empiremuse.rules.servers import SettingError, changed_request, migrate_request

pytestmark = pytest.mark.critical

MAIN, R2, R10, EXCLUSIVE = (
    PanelPeer("TOKEN", 1),
    PanelPeer("TOKEN_2", 2),
    PanelPeer("TOKEN_10", 10),
    PanelPeer("TOKEN_3", 3, exclusive=True),
)


# ---------------------------------------------------------------------- eleição do bot do painel


@pytest.mark.parametrize(
    ("peers", "elected"),
    [
        ([R10, R2, MAIN], 1),  # o principal, esteja onde estiver na lista
        ([PanelPeer("ALFA", 4), MAIN], 1),  # e por papel, não por ordem do nome
        ([R10, R2], 2),  # sem o principal: a 1ª reserva pela ordem natural (TOKEN_2 antes de TOKEN_10)
        ([EXCLUSIVE, R10], 10),  # exclusivo de servidor só entra se não há mais ninguém
        ([EXCLUSIVE], 3),
        ([], None),
    ],
)
def test_the_panel_bot_is_the_main_else_the_first_reserve_else_an_exclusive_one(peers, elected):
    assert elect_panel_bot(peers) == elected


# ---------------------------------------------------------------------- S10: call privada


def entry(**overrides):
    values = {
        "bot_name": "Muse",
        "bot_id": 1,
        "voice_name": "Sala",
        "private": False,
        "title": "Faixa [x](http://e.vil)",
        "url": "https://exemplo.com/faixa",
        "paused": False,
        "queue": 3,
        "requester": "Ana",
    }
    return make_entry(**(values | overrides))


def test_a_private_call_never_carries_the_track_or_the_link():
    private = entry(private=True)
    assert private.private is True and private.title is None and private.url is None and private.requester is None
    assert private.bot_name == "Muse" and private.voice_name == "Sala"  # quem está onde continua aparecendo
    public = entry()
    assert (
        public.requester == "Ana" and public.title and public.url == "https://exemplo.com/faixa" and not public.private
    )


@pytest.mark.parametrize(("paused", "state"), [(False, PLAYING), (True, PAUSED)])
def test_the_state_follows_the_player(paused, state):
    assert entry(paused=paused).state == state


def test_third_party_texts_are_cleaned_and_bounded_and_the_queue_never_goes_negative():
    hostile = entry(bot_name="Mu‮se\n" + "x" * 500, voice_name=None, title="t" * 1000, url="u" * 1000, queue=-4)
    assert "\n" not in hostile.bot_name and "‮" not in hostile.bot_name and len(hostile.bot_name) <= 40
    assert hostile.voice_name == "call" and len(hostile.title) <= 100 and len(hostile.url) <= 250
    assert hostile.queue == 0


# ---------------------------------------------------------------------- S7: o botão age no player da call de quem apertou


@pytest.mark.parametrize(
    ("candidates", "member_voice", "chosen"),
    [
        ([(1, 100), (2, 200)], 200, 2),  # nunca o 1º da lista: o que está na call de quem apertou
        ([(1, 100), (2, 200)], 100, 1),
        ([(1, 100), (2, 200)], 300, None),  # call sem player
        ([(1, 100), (2, 200)], None, None),  # fora de call
        ([(1, None), (2, 200)], None, None),  # player sem call não casa com "sem call"
        ([], 100, None),
    ],
)
def test_the_player_is_the_one_in_the_callers_voice_channel_and_never_another(candidates, member_voice, chosen):
    assert choose_player(candidates, member_voice) == chosen


# ---------------------------------------------------------------------- no máximo uma edição a cada 3 s


@pytest.mark.parametrize(
    ("last", "now", "wait"),
    [
        (None, 5_000, 0),  # nunca editou
        (1_000, 1_000, PANEL_REFRESH_MS),
        (1_000, 2_000, PANEL_REFRESH_MS - 1_000),
        (1_000, 1_000 + PANEL_REFRESH_MS, 0),
        (9_000, 1_000, 0),  # relógio que voltou não trava o painel
    ],
)
def test_the_panel_is_edited_at_most_once_every_three_seconds(last, now, wait):
    assert refresh_wait_ms(last, now) == wait


# ---------------------------------------------------------------------- migração: só o canal do principal


@pytest.mark.parametrize(
    ("legacy", "request_section"),
    [
        ({"player_controller": {"channel": "12", "message_id": "34"}}, {"channel": "12", "message_id": "34"}),
        ({"player_controller": {"channel": 12, "message_id": 34}}, {"channel": "12", "message_id": "34"}),
        ({"player_controller": {"channel": None, "message_id": "34"}}, {"channel": None, "message_id": None}),
        ({"player_controller": {"channel": "abc", "message_id": "34"}}, {"channel": None, "message_id": None}),
        ({"player_controller": {"channel": "-5", "message_id": "0"}}, {"channel": None, "message_id": None}),
        ({"player_controller": {"channel": True, "message_id": "34"}}, {"channel": None, "message_id": None}),
        ({"player_controller": {"channel": "12", "message_id": "x"}}, {"channel": "12", "message_id": None}),
        ({}, {"channel": None, "message_id": None}),
        (None, {"channel": None, "message_id": None}),
    ],
)
def test_migration_keeps_only_valid_ids_and_leaves_the_panel_bot_to_the_election(legacy, request_section):
    assert migrate_request(legacy) == {**request_section, "panel_bot_id": None}


def test_a_writer_that_sets_the_request_channel_to_garbage_is_refused_and_unchanged_fields_are_ignored():
    seen = {"channel": "12", "message_id": "34"}
    assert changed_request({"player_controller": {"channel": "12", "message_id": "34"}}, seen) == {}
    assert changed_request({"player_controller": {"channel": "99"}}, seen) == {"channel": "99"}
    assert changed_request({"player_controller": {"message_id": None}}, seen) == {"message_id": None}
    with pytest.raises(SettingError):
        changed_request({"player_controller": {"channel": "não é id"}}, seen)

"""Gate do #142 — uma faixa que falha em TODA tentativa precisa ser relatada e pulada em número limitado de tentativas.

Um laço simula o player: depois de cada falha, o que o handler deixou na fila é tocado de novo (e falha de novo). A troca de
nó é real o bastante para o teste: ``change_node`` troca ``player.node``. O limite de 12 só impede o teste de pendurar.
"""

from types import SimpleNamespace

import pytest

from empiremuse.utils.music.models.event_steps import _he_dispatch
from tests.audio.test_playback_retry_youtube import (  # noqa: F401  (fixture autouse do sleep)
    ALL_CLIENTS,
    ALL_CLIENTS_TIMEOUT,
    fail,
    make_player,
    make_track,
    sleep,
)

pytestmark = pytest.mark.asyncio

LIMITE_DE_TENTATIVAS = 12


def outro_no(identifier: str = "N2") -> SimpleNamespace:
    return SimpleNamespace(identifier=identifier, version=4, is_available=True, search_providers=["ytsearch"])


async def tentativas_ate_desistir(player, cause: str) -> int:
    """Quantas falhas até o handler deixar de devolver a faixa à fila (ou ``LIMITE_DE_TENTATIVAS`` se nunca deixa)."""
    track = player.current

    async def trocar(identifier: str) -> None:
        player.node = next(n for n in player.bot.music.nodes.values() if n.identifier == identifier)

    player.change_node.side_effect = trocar
    for tentativa in range(1, LIMITE_DE_TENTATIVAS + 1):
        await _he_dispatch(player, fail(player, cause))
        if track not in player.queue:
            return tentativa
        player.queue.remove(track)
        player.current = track
    return LIMITE_DE_TENTATIVAS + 1


def com_dois_nos(source: str):
    track = make_track(source=source, uri=f"https://exemplo.invalid/{source}/abc")
    n2 = outro_no()
    player = make_player(track, nodes=[n2])
    player.bot.music.nodes = {"N1": player.node, "N2": n2}
    return player


def com_um_no(source: str):
    track = make_track(source=source, uri=f"https://exemplo.invalid/{source}/abc")
    return make_player(track)


@pytest.mark.parametrize("cause", [ALL_CLIENTS, ALL_CLIENTS_TIMEOUT])
@pytest.mark.parametrize("source", ["spotify", "youtube"])
@pytest.mark.parametrize("nos", ["um_no", "dois_nos"])
async def test_a_track_failing_every_attempt_is_dropped_in_bounded_attempts(source, nos, cause):
    player = com_um_no(source) if nos == "um_no" else com_dois_nos(source)
    track = player.current

    tentativas = await tentativas_ate_desistir(player, cause)

    assert tentativas <= 8, f"{tentativas} tentativas e a faixa ainda volta à fila"
    assert track in player.failed_tracks
    assert player.locked is False

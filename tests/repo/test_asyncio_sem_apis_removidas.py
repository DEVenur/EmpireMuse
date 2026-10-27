"""S2 / A1 — o pacote não usa as APIs de asyncio removidas no Python 3.14.

Equivale ao ``grep -rnE "set_event_loop_policy|EventLoopPolicy|get_event_loop\\(\\)" empiremuse`` do contrato: a saída precisa
ser vazia. Comentários e docstrings também contam, como no grep.
"""

import re

import pytest

from tests.support.raiz import RAIZ

PACOTE = RAIZ / "empiremuse"
PADRAO_PROIBIDO = re.compile(r"set_event_loop_policy|EventLoopPolicy|get_event_loop\(\)")


def _achados(raiz) -> list[str]:
    achados = []
    for arquivo in sorted(raiz.rglob("*.py")):
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), start=1):
            if PADRAO_PROIBIDO.search(linha):
                achados.append(f"{arquivo.relative_to(RAIZ)}:{numero}: {linha.strip()}")
    return achados


def test_pacote_nao_usa_set_event_loop_policy_eventlooppolicy_nem_get_event_loop():
    achados = _achados(PACOTE)

    assert not achados, "APIs de asyncio removidas no 3.14 ainda em uso:\n" + "\n".join(achados)


@pytest.mark.parametrize(
    "linha",
    [
        "asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())",
        "loop = asyncio.get_event_loop()",
        "policy = asyncio.DefaultEventLoopPolicy",
    ],
)
def test_padrao_proibido_pega_os_usos_do_contrato(linha):
    assert PADRAO_PROIBIDO.search(linha)


@pytest.mark.parametrize(
    "linha",
    [
        "loop = asyncio.get_running_loop()",
        "loop = asyncio.new_event_loop()",
        "asyncio.set_event_loop(self.loop)",
    ],
)
def test_padrao_proibido_deixa_passar_as_apis_permitidas(linha):
    assert not PADRAO_PROIBIDO.search(linha)

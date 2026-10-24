"""F3-1 / KI-15 — a tarefa de partida que obtém o token do Spotify captura e registra a falha (sem segredos no log)."""

import ast


from tests.support.raiz import RAIZ
import pytest

pytestmark = pytest.mark.regression


def _chamadas_de_create_task() -> list[ast.Call]:
    arvore = ast.parse((RAIZ / "empiremuse" / "utils" / "client.py").read_text("utf-8"))
    return [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "create_task" and no.args
    ]


def _nome_chamado(no: ast.AST) -> str | None:
    return no.func.attr if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) else None


def test_a_partida_agenda_a_tarefa_que_captura_a_falha_e_nao_o_get_access_token_solto():
    """Ligação em BotPool.setup: o bug original era um create_task(get_access_token()) sem tratamento de exceção."""
    alvos = [_nome_chamado(no.args[0]) for no in _chamadas_de_create_task()]

    assert "refresh_spotify_token" in alvos, "a partida não agenda refresh_spotify_token()"
    assert "get_access_token" not in alvos, (
        "create_task(get_access_token()) solto: a falha vira 'Task exception never retrieved'"
    )

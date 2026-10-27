"""A24 (item 18, P4) — ``empiremuse/updater/proxy_client.py``: o cliente do proxy de atualização, contra um proxy falso em socket Unix.

O proxy falso é um servidor aiohttp (``web.UnixSite``) com rotas configuráveis por teste; ele grava cada pedido. As URLs são ``http://proxy/...`` sem prefixo
de versão. Nenhuma mensagem de erro pode conter o caminho do socket.
"""

import asyncio
import importlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web

from empiremuse.updater.git_flow import UpdateError

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

HELPER = "/containers/empiremuse-updater"
ANDAMENTO = "Já há uma atualização em andamento."
INESPERADA = "Resposta inesperada do proxy de atualização."
INACESSIVEL = "proxy de atualização inacessível"
ESTADO = {
    "State": {
        "Status": "exited",
        "Running": False,
        "ExitCode": 70,
        "StartedAt": "2026-10-27T10:00:00Z",
        "FinishedAt": "2026-10-27T10:01:00Z",
    }
}


@pytest.fixture
def proxy_client():
    return importlib.import_module("empiremuse.updater.proxy_client")


class ProxyFalso:
    def __init__(self, caminho: str) -> None:
        self.caminho = caminho
        self.rotas: dict[tuple[str, str], Any] = {}
        self.pedidos: list[tuple[web.Request, bytes]] = []

    async def tratar(self, request: web.Request) -> web.StreamResponse:
        self.pedidos.append((request, await request.read()))
        resposta = self.rotas.get((request.method, request.path))
        if resposta is None:
            return web.Response(status=404)
        return await resposta(request) if callable(resposta) else resposta

    def corpo(self, indice: int = -1) -> Any:
        return json.loads(self.pedidos[indice][1])


@pytest_asyncio.fixture
async def servidor(tmp_path_factory: pytest.TempPathFactory):
    caminho = str(tmp_path_factory.mktemp("s") / "p.sock")  # curto: o limite do AF_UNIX é ~108 bytes
    falso = ProxyFalso(caminho)
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", falso.tratar)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.UnixSite(runner, caminho).start()
    yield falso
    await runner.cleanup()


@pytest.fixture
def cliente(proxy_client, servidor):
    return proxy_client.ProxyClient(servidor.caminho)


def json_resposta(corpo: Any, status: int = 200) -> web.Response:
    return web.json_response(corpo, status=status)


# ============================================================================ create_helper


async def test_create_helper_posts_the_target_as_the_only_command(cliente, servidor):
    servidor.rotas[("POST", "/containers/create")] = web.Response(status=201)

    await cliente.create_helper("2.1.1@sha256:" + "ab" * 32)

    (pedido, _) = servidor.pedidos[0]
    assert pedido.query == {"name": "empiremuse-updater"} and "json" in pedido.content_type
    assert servidor.corpo() == {"Cmd": ["2.1.1@sha256:" + "ab" * 32]}


@pytest.mark.parametrize(
    ("status", "mensagem"),
    [(409, ANDAMENTO), (500, INESPERADA), (200, INESPERADA), (404, INESPERADA)],
    ids=["409", "500", "200-nao-e-201", "404"],
)
async def test_create_helper_maps_the_statuses_to_generic_messages(cliente, servidor, status, mensagem):
    servidor.rotas[("POST", "/containers/create")] = web.Response(status=status, text="detalhe do docker /var/run")

    with pytest.raises(UpdateError) as erro:
        await cliente.create_helper("2.1.1@sha256:" + "ab" * 32)

    assert str(erro.value) == mensagem


# ============================================================================ start_helper


async def test_start_helper_posts_to_the_start_endpoint(cliente, servidor):
    servidor.rotas[("POST", f"{HELPER}/start")] = web.Response(status=204)

    await cliente.start_helper()

    assert [(p.method, p.path) for p, _ in servidor.pedidos] == [("POST", f"{HELPER}/start")]


@pytest.mark.parametrize("status, mensagem", [(409, ANDAMENTO), (500, INESPERADA), (200, INESPERADA)])
async def test_start_helper_maps_the_statuses(cliente, servidor, status, mensagem):
    servidor.rotas[("POST", f"{HELPER}/start")] = web.Response(status=status)

    with pytest.raises(UpdateError) as erro:
        await cliente.start_helper()

    assert str(erro.value) == mensagem


# ============================================================================ helper_state


async def test_a_missing_helper_is_none(cliente, servidor):
    servidor.rotas[("GET", f"{HELPER}/json")] = web.Response(status=404)

    assert await cliente.helper_state() is None


async def test_the_helper_state_is_read_from_the_inspect_json(cliente, servidor, proxy_client):
    servidor.rotas[("GET", f"{HELPER}/json")] = json_resposta(ESTADO)

    estado = await cliente.helper_state()

    assert estado == proxy_client.HelperState(
        status="exited",
        running=False,
        exit_code=70,
        started_at="2026-10-27T10:00:00Z",
        finished_at="2026-10-27T10:01:00Z",
    )


@pytest.mark.parametrize(
    "resposta",
    [
        web.Response(status=500),
        web.Response(status=200, text="isto não é json", content_type="application/json"),
        json_resposta([]),
        json_resposta({}),
        json_resposta({"State": {}}),
        json_resposta({"State": {**ESTADO["State"], "ExitCode": "0"}}),
        json_resposta({"State": {**ESTADO["State"], "Running": "sim"}}),
        json_resposta({"State": {**ESTADO["State"], "Status": 3}}),
    ],
    ids=["500", "nao-json", "lista", "vazio", "state-vazio", "exitcode-texto", "running-texto", "status-numero"],
)
async def test_a_state_response_out_of_the_format_is_unexpected(cliente, servidor, resposta):
    servidor.rotas[("GET", f"{HELPER}/json")] = resposta

    with pytest.raises(UpdateError) as erro:
        await cliente.helper_state()

    assert str(erro.value) == INESPERADA


# ============================================================================ helper_logs


async def test_the_logs_are_requested_with_the_tail_and_returned_as_strings(cliente, servidor):
    servidor.rotas[("GET", f"{HELPER}/logs")] = json_resposta({"lines": ["empiremuse-updater: ok", "linha 2"]})

    linhas = await cliente.helper_logs(20)

    assert linhas == ["empiremuse-updater: ok", "linha 2"]
    assert servidor.pedidos[0][0].query == {"stdout": "1", "stderr": "1", "tail": "20"}


@pytest.mark.parametrize(("pedido", "enviado"), [(0, "1"), (-5, "1"), (1, "1"), (200, "200"), (5000, "200")])
async def test_the_tail_is_clamped_between_1_and_200(cliente, servidor, pedido, enviado):
    servidor.rotas[("GET", f"{HELPER}/logs")] = json_resposta({"lines": []})

    await cliente.helper_logs(pedido)

    assert servidor.pedidos[0][0].query["tail"] == enviado


async def test_no_more_than_tail_lines_come_back(cliente, servidor):
    servidor.rotas[("GET", f"{HELPER}/logs")] = json_resposta({"lines": [f"l{n}" for n in range(50)]})

    linhas = await cliente.helper_logs(5)

    assert len(linhas) <= 5 and all(isinstance(linha, str) for linha in linhas)


@pytest.mark.parametrize(
    "resposta",
    [web.Response(status=500), json_resposta({"lines": "texto"}), json_resposta({"outro": []}), json_resposta([])],
    ids=["500", "lines-nao-e-lista", "sem-lines", "lista"],
)
async def test_a_logs_response_out_of_the_format_is_unexpected(cliente, servidor, resposta):
    servidor.rotas[("GET", f"{HELPER}/logs")] = resposta

    with pytest.raises(UpdateError) as erro:
        await cliente.helper_logs(20)

    assert str(erro.value) == INESPERADA


# ============================================================================ remove_helper


@pytest.mark.parametrize("status", [204, 404], ids=["removido", "ja-ausente"])
async def test_remove_helper_accepts_removed_and_absent(cliente, servidor, status):
    servidor.rotas[("DELETE", HELPER)] = web.Response(status=status)

    assert await cliente.remove_helper() is None
    assert [(p.method, p.path) for p, _ in servidor.pedidos] == [("DELETE", HELPER)]


@pytest.mark.parametrize("status", [409, 500, 200])
async def test_remove_helper_fails_on_conflict_or_anything_else(cliente, servidor, status):
    servidor.rotas[("DELETE", HELPER)] = web.Response(status=status)

    with pytest.raises(UpdateError):
        await cliente.remove_helper()


# ============================================================================ proxy inacessível


CHAMADAS: dict[str, Callable[[Any], Awaitable[Any]]] = {
    "create": lambda c: c.create_helper("2.1.1@sha256:" + "ab" * 32),
    "start": lambda c: c.start_helper(),
    "state": lambda c: c.helper_state(),
    "logs": lambda c: c.helper_logs(20),
    "remove": lambda c: c.remove_helper(),
}


@pytest.mark.parametrize("chamada", list(CHAMADAS), ids=list(CHAMADAS))
async def test_a_missing_socket_is_the_friendly_error_without_the_path(proxy_client, tmp_path: Path, chamada):
    caminho = str(tmp_path / "ninguem.sock")
    cliente = proxy_client.ProxyClient(caminho)

    with pytest.raises(UpdateError) as erro:
        await CHAMADAS[chamada](cliente)

    assert str(erro.value) == INACESSIVEL and caminho not in str(erro.value)


async def test_a_refused_connection_is_the_same_error(proxy_client, tmp_path: Path):
    caminho = tmp_path / "morto.sock"
    caminho.touch()  # existe, mas não é um socket que aceite conexões

    with pytest.raises(UpdateError) as erro:
        await proxy_client.ProxyClient(str(caminho)).helper_state()

    assert str(erro.value) == INACESSIVEL and str(caminho) not in str(erro.value)


async def test_a_proxy_that_never_answers_times_out_as_the_same_error(proxy_client, servidor, monkeypatch):
    monkeypatch.setattr(proxy_client, "TIMEOUT", 0.05)
    nunca = asyncio.Event()

    async def travado(request: web.Request) -> web.Response:
        await nunca.wait()
        return web.Response()

    servidor.rotas[("GET", f"{HELPER}/json")] = travado

    with pytest.raises(UpdateError) as erro:
        await proxy_client.ProxyClient(servidor.caminho).helper_state()

    assert str(erro.value) == INACESSIVEL and servidor.caminho not in str(erro.value)

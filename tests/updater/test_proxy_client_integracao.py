"""Integração (item 18, P4) — o ``ProxyClient`` REAL contra o ``proxy.py`` REAL (subprocesso ``python -I -S``) e o daemon falso do ``test_proxy``.

Cada operação do cliente atravessa o proxy de verdade: se um aperto futuro de cabeçalho, rota ou formato no proxy deixar de combinar com o que o bot
manda ou espera, o bot não pode quebrar em silêncio. O nome na API é ``empiremuse-updater``; o contêiner real é ``e2e-updater``.
"""

import pytest

from empiremuse.updater.proxy_client import HelperState, ProxyClient
from tests.support.daemon_falso import DaemonFalso
from tests.updater.test_proxy import ALVO, CONTAINER_REAL, PREFIXO_LOG, ambiente, esperar_socket, subir

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def mundo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("integ")
    daemon = DaemonFalso(str(pasta / "docker.sock"))
    processo = subir(ambiente(pasta))
    esperar_socket(processo, str(pasta / "updater.sock"))
    yield daemon, str(pasta / "updater.sock")
    processo.terminate()
    processo.wait(timeout=20)
    daemon.parar()


@pytest.fixture
def daemon(mundo):
    mundo[0].reiniciar()
    return mundo[0]


@pytest.fixture
def cliente(mundo, daemon):
    return ProxyClient(mundo[1])


def chegou(daemon, metodo, caminho):
    return [r for r in daemon.requisicoes if r.metodo == metodo and r.caminho == caminho]


async def test_create_helper_goes_through_the_proxy_and_reaches_the_daemon_with_the_target(cliente, daemon):
    await cliente.create_helper(ALVO)

    (criacao,) = chegou(daemon, "POST", "/containers/create")
    assert criacao.query == f"name={CONTAINER_REAL}"
    assert ALVO.encode() in criacao.corpo  # o alvo vai como primeiro item do Cmd do template


async def test_helper_logs_come_back_filtered_by_the_proxy(cliente, daemon):
    daemon.adicionar_container(
        CONTAINER_REAL, linhas_de_log=[PREFIXO_LOG + "pull 0", "ruido do docker", PREFIXO_LOG + "up 70"]
    )

    linhas = await cliente.helper_logs(20)

    assert linhas == [PREFIXO_LOG + "pull 0", PREFIXO_LOG + "up 70"]


async def test_remove_helper_goes_through_the_proxy_without_force(cliente, daemon):
    daemon.adicionar_container(CONTAINER_REAL)

    await cliente.remove_helper()

    (remocao,) = chegou(daemon, "DELETE", f"/containers/{CONTAINER_REAL}")
    assert remocao.query == ""

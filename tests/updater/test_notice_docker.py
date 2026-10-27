"""A25 (item 18, P4) — o aviso pós-boot do fluxo Docker: ``notice.deliver_docker_notice`` e o ramo docker de ``on_pool_ready``.

O cliente do proxy é um fake (estados do auxiliar em sequência); o ``sleep`` e a versão da imagem são injetados (nada dorme, sem relógio real).
Bots, canais e usuários reaproveitam os fakes de ``test_notice``. O aviso é único: o pendente some ANTES do envio; o auxiliar é sempre removido
no fim (erro ignorado).
"""

import dataclasses
import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater import notice
from empiremuse.updater.git_flow import UpdateError
from empiremuse.updater.state import PendingUpdate, pending_path, read_pending, write_pending
from empiremuse import paths
from tests.updater.test_notice import AGORA, CANAL, CHANGELOG, bot_falso, pool_com, sem_mencoes

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

DE, PARA = Version(2, 0, 0), Version(2, 1, 0)
DIGEST = "sha256:" + "ab" * 32
DESCONHECIDO = "resultado desconhecido; confira o servidor"


def pendente_docker(**campos) -> PendingUpdate:
    base = {
        "flow": "docker",
        "from_version": DE,
        "to_version": PARA,
        "bot_id": 111,
        "channel_id": CANAL,
        "requested_by": 333,
        "created_at": AGORA - 120,
        "digest": DIGEST,
        "boots": 0,
        "status": "ready",
    }
    return PendingUpdate(**{**base, **campos})


def estado(*, rodando: bool, codigo: int = 0) -> Any:
    from empiremuse.updater.proxy_client import HelperState

    return HelperState("running" if rodando else "exited", rodando, codigo, "ini", "fim")


class ClienteFalso:
    def __init__(self, sequencia: list[Any], runtime=None) -> None:
        self.sequencia = sequencia
        self.runtime = runtime
        self.remocoes = 0
        self.falha_na_remocao: Exception | None = None
        self.status_no_primeiro_estado: str | None = None

    async def helper_state(self):
        if self.runtime is not None and self.status_no_primeiro_estado is None:
            lido = read_pending(self.runtime, AGORA)
            self.status_no_primeiro_estado = lido.status if lido else "ausente"
        return self.sequencia.pop(0) if len(self.sequencia) > 1 else self.sequencia[0]

    async def remove_helper(self):
        self.remocoes += 1
        if self.falha_na_remocao:
            raise self.falha_na_remocao

    async def helper_logs(self, tail: int = 20):
        return []


class Pausas:
    def __init__(self) -> None:
        self.valores: list[float] = []

    async def __call__(self, segundos: float) -> None:
        self.valores.append(segundos)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    pasta = tmp_path / "runtime"
    pasta.mkdir()
    projeto = tmp_path / "projeto"
    projeto.mkdir()
    (projeto / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", projeto)
    return pasta


@pytest.fixture
def docker_flow():
    return importlib.import_module("empiremuse.updater.docker_flow")


async def entregar_docker(pool, cliente, runtime, versao, **extra):
    pausas = Pausas()
    await notice.deliver_docker_notice(
        pool,
        cliente,
        runtime_dir=runtime,
        now=lambda: AGORA,
        image_version_fn=lambda: versao,
        sleep=pausas,
        **{"timeout": 900, "interval": 5, **extra},
    )
    return pausas


# ============================================================================ deliver_docker_notice


async def test_success_is_a_green_embed_with_the_changelog_and_removes_the_helper(runtime):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=False, codigo=0)])
    write_pending(runtime, pendente_docker())

    await entregar_docker(pool_com(bot), cliente, runtime, PARA)

    chamada = bot.canal.send.await_args
    embed = chamada.kwargs["embed"]
    assert "Atualizado de 2.0.0 para 2.1.0" in embed.description and "novidade da 2.1.0" in embed.description
    assert embed.colour.value == notice.COLOR_OK and sem_mencoes(chamada)
    assert cliente.remocoes == 1 and not pending_path(runtime).exists()


@pytest.mark.parametrize("codigo", [70, 71, 66, 67, 68, 65, 64])
async def test_a_helper_that_failed_with_the_old_version_still_running_is_a_red_embed_with_the_meaning(
    runtime, docker_flow, codigo
):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=False, codigo=codigo)])
    write_pending(runtime, pendente_docker())

    await entregar_docker(pool_com(bot), cliente, runtime, DE)

    embed = bot.canal.send.await_args.kwargs["embed"]
    assert embed.colour.value == notice.COLOR_FAIL and docker_flow.describe_exit(codigo) in embed.description
    assert cliente.remocoes == 1 and not pending_path(runtime).exists()


async def test_a_running_helper_is_waited_for_with_the_injected_sleep(runtime):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=True), estado(rodando=True), estado(rodando=False, codigo=0)])
    write_pending(runtime, pendente_docker())

    pausas = await entregar_docker(pool_com(bot), cliente, runtime, PARA)

    assert pausas.valores == [5, 5]
    assert bot.canal.send.await_args.kwargs["embed"].colour.value == notice.COLOR_OK


async def test_a_helper_still_running_at_the_timeout_is_an_unknown_result(runtime):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=True)])
    write_pending(runtime, pendente_docker())

    pausas = await entregar_docker(pool_com(bot), cliente, runtime, DE, timeout=20, interval=5)

    embed = bot.canal.send.await_args.kwargs["embed"]
    assert sum(pausas.valores) >= 20
    assert embed.colour.value == notice.COLOR_UNKNOWN and DESCONHECIDO in embed.description
    assert cliente.remocoes == 1 and not pending_path(runtime).exists()


@pytest.mark.parametrize(
    ("sequencia", "versao"),
    [([None], PARA), ([estado(rodando=False, codigo=0)], None), ([estado(rodando=False, codigo=0)], Version(9, 9, 9))],
    ids=["auxiliar-ausente", "versao-ilegivel", "versao-inesperada"],
)
async def test_anything_that_cannot_be_confirmed_is_a_yellow_unknown_embed(runtime, sequencia, versao):
    bot = bot_falso()
    write_pending(runtime, pendente_docker())

    await entregar_docker(pool_com(bot), ClienteFalso(sequencia), runtime, versao)

    embed = bot.canal.send.await_args.kwargs["embed"]
    assert embed.colour.value == notice.COLOR_UNKNOWN and DESCONHECIDO in embed.description


async def test_a_failing_removal_is_ignored_and_the_notice_still_goes_out(runtime):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=False, codigo=0)])
    cliente.falha_na_remocao = UpdateError("não removeu")
    write_pending(runtime, pendente_docker())

    await entregar_docker(pool_com(bot), cliente, runtime, PARA)

    bot.canal.send.assert_awaited_once()
    assert not pending_path(runtime).exists()


async def test_the_pending_update_is_gone_before_the_send_so_the_delivery_is_single(runtime):
    bot = bot_falso()
    estados: list[bool] = []
    original = bot.canal.send

    async def enviar(*args, **kwargs):
        estados.append(pending_path(runtime).exists())
        return await original(*args, **kwargs)

    bot.canal.send = enviar
    write_pending(runtime, pendente_docker())

    await entregar_docker(pool_com(bot), ClienteFalso([estado(rodando=False, codigo=0)]), runtime, PARA)

    assert estados == [False]


async def test_a_pending_git_update_is_not_touched_by_the_docker_notice(runtime):
    bot = bot_falso()
    git = dataclasses.replace(pendente_docker(), flow="git", digest=None, prev_sha="a" * 40)
    write_pending(runtime, git)
    cliente = ClienteFalso([estado(rodando=False, codigo=0)])

    await entregar_docker(pool_com(bot), cliente, runtime, PARA)

    bot.canal.send.assert_not_awaited()
    assert cliente.remocoes == 0 and pending_path(runtime).exists()


# ============================================================================ on_pool_ready, ramo docker


def pool_saudavel(*bots, socket: str):
    pool = pool_com(*bots)
    pool.config = {"UPDATE_PROXY_SOCKET": socket}
    return pool


async def test_on_pool_ready_marks_ready_then_runs_the_docker_branch_with_the_configured_socket(runtime, monkeypatch):
    bot = bot_falso()
    cliente = ClienteFalso([estado(rodando=False, codigo=0)], runtime)
    caminhos: list[str] = []

    def fabrica(caminho: str) -> ClienteFalso:
        caminhos.append(caminho)
        return cliente

    monkeypatch.setattr(notice, "ProxyClient", fabrica)
    monkeypatch.setenv("EMPIREMUSE_VERSION", "2.1.0")
    write_pending(runtime, pendente_docker(status="pending"))

    await notice.on_pool_ready(
        pool_saudavel(bot, socket="/run/empiremuse/updater.sock"), runtime_dir=runtime, now=lambda: AGORA
    )

    assert caminhos == ["/run/empiremuse/updater.sock"]
    assert cliente.status_no_primeiro_estado == "ready"  # gravado antes de qualquer consulta ou envio
    assert "Atualizado de 2.0.0 para 2.1.0" in bot.canal.send.await_args.kwargs["embed"].description
    assert not pending_path(runtime).exists()


async def test_on_pool_ready_without_a_proxy_socket_keeps_the_pending_update_and_sends_nothing(runtime, caplog):
    bot = bot_falso()
    write_pending(runtime, pendente_docker(status="pending"))

    await notice.on_pool_ready(pool_saudavel(bot, socket=""), runtime_dir=runtime, now=lambda: AGORA)

    bot.canal.send.assert_not_awaited()
    assert json.loads(pending_path(runtime).read_text())["flow"] == "docker" and pending_path(runtime).exists()


async def test_on_pool_ready_with_an_unhealthy_pool_leaves_a_docker_pending_update_alone(runtime, monkeypatch):
    bot = bot_falso()
    write_pending(runtime, pendente_docker(status="pending"))
    antes = pending_path(runtime).read_bytes()
    pool = pool_saudavel(bot, socket="/run/x.sock")
    pool.pool_is_healthy = lambda: False

    await notice.on_pool_ready(pool, runtime_dir=runtime, now=lambda: AGORA)

    assert pending_path(runtime).read_bytes() == antes

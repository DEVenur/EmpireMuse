"""A6 (item 18, P1) — o ``BotPool`` só renova o heartbeat com o pool saudável e apaga o que sobrou de uma execução anterior (V11).

Pool falso (``BotPool.__new__`` com os atributos que a lógica lê), relógio e ``sleep`` injetados: nada dorme e nada toca a rede.
"""

import asyncio
from types import SimpleNamespace

import pytest

from empiremuse import health
from empiremuse.health import HEALTH_FILE_ENV, HEARTBEAT_INTERVAL, clear_heartbeat, is_fresh, write_heartbeat
from empiremuse.utils import client
from empiremuse.utils.client import BotPool

pytestmark = pytest.mark.critical


class BotFalso:
    """Hashable (``get_all_bots`` usa um ``set``): ``bot_ready`` e um ``music.nodes`` com um nó por item (``is_available``)."""

    def __init__(self, pronto: bool, *nos: bool):
        self.bot_ready = pronto
        self.music = SimpleNamespace(nodes={f"no{i}": SimpleNamespace(is_available=ok) for i, ok in enumerate(nos)})


bot = BotFalso


def pool_com(bots=(), guild_bots=None, nodes_expected=False) -> BotPool:
    pool = BotPool.__new__(BotPool)
    pool.bots = list(bots)
    pool.guild_bots = guild_bots or {}
    pool.nodes_expected = nodes_expected
    pool.heartbeat_task = None
    return pool


# ============================================================================ pool_is_healthy


@pytest.mark.parametrize(
    ("pool", "saudavel"),
    [
        (pool_com(), False),
        (pool_com([bot(True)]), True),
        (pool_com([bot(True), bot(False)]), False),
        (pool_com([bot(False)], nodes_expected=True), False),
        (pool_com([bot(True)], nodes_expected=True), False),
        (pool_com([bot(True, False, False)], nodes_expected=True), False),
        (pool_com([bot(True, False, True)], nodes_expected=True), True),
        # bots_ready olha só pool.bots; os nós contam em qualquer bot (get_all_bots)
        (pool_com([bot(True)], {"1": [bot(False, True)]}, nodes_expected=True), True),
        (pool_com([bot(True)], {"1": [bot(False)]}), True),
        (pool_com([], {"1": [bot(True, True)]}), False),
    ],
    ids=[
        "sem-bots",
        "bot-pronto-sem-nos-esperados",
        "um-bot-nao-pronto",
        "nao-pronto-com-nos-esperados",
        "nos-esperados-e-nenhum-no",
        "nos-indisponiveis",
        "um-no-disponivel",
        "no-disponivel-em-bot-de-guilda",
        "bot-de-guilda-nao-pronto-nao-conta",
        "so-bot-de-guilda-nao-basta",
    ],
)
def test_pool_is_healthy(pool, saudavel):
    assert pool.pool_is_healthy() is saudavel


@pytest.mark.parametrize(
    ("start_local", "servidores", "esperados"),
    [(False, {}, False), (True, {}, True), (False, {"A": {}}, True), (True, {"A": {}}, True)],
)
def test_node_check_records_whether_nodes_are_expected(monkeypatch, start_local, servidores, esperados):
    pool = pool_com()
    pool.config = {
        "PREFER_YOUTUBE_NATIVE_PLAYBACK": False,
        "ONLY_USE_NATIVE_SEARCH_PROVIDERS": False,
        "SEARCH_PROVIDERS": "",
    }
    pool.loop = SimpleNamespace(create_task=lambda coro: None)
    monkeypatch.setattr(pool, "check_node", lambda data: None, raising=False)

    pool.node_check(servidores, start_local=start_local)

    assert pool.nodes_expected is esperados


# ============================================================================ heartbeat_loop (relógio e sleep injetados)


class Parar(BaseException):
    pass


def sleep_que_para_em(vezes: int, registro: list, a_cada_volta=None):
    async def sleep(segundos):
        registro.append(segundos)
        if a_cada_volta:
            a_cada_volta(len(registro))
        if len(registro) >= vezes:
            raise Parar

    return sleep


def relogio(*instantes):
    fila = iter(instantes)
    return lambda: next(fila)


def test_the_loop_renews_only_while_the_pool_is_healthy_and_sleeps_the_interval(tmp_path):
    arquivo = tmp_path / "saude"
    pool = pool_com([bot(True)])
    dormiu = []

    def muda_o_pool(volta):  # depois da 1ª volta o pool adoece; depois da 2ª, se recupera
        pool.bots[0].bot_ready = volta >= 2

    with pytest.raises(Parar):
        asyncio.run(
            pool.heartbeat_loop(
                str(arquivo), clock=relogio(1000.0, 3000.0), sleep=sleep_que_para_em(3, dormiu, muda_o_pool)
            )
        )

    assert dormiu == [HEARTBEAT_INTERVAL] * 3
    # a volta doente (relógio 2000) não gravou nada; a última gravação é a da volta saudável de 3000
    assert is_fresh(arquivo, 3000.0) and not is_fresh(arquivo, 1000.0 + 61)


def test_an_unhealthy_pool_never_creates_the_file(tmp_path):
    arquivo = tmp_path / "saude"
    pool = pool_com([bot(False)])
    dormiu = []

    def sem_relogio():
        raise AssertionError("o relógio não deveria ser lido com o pool doente")

    with pytest.raises(Parar):
        asyncio.run(pool.heartbeat_loop(str(arquivo), clock=sem_relogio, sleep=sleep_que_para_em(2, dormiu)))

    assert not arquivo.exists() and len(dormiu) == 2


def test_a_failed_write_does_not_kill_the_loop(tmp_path, monkeypatch):
    pool = pool_com([bot(True)])
    dormiu = []

    def falha(caminho, agora):
        raise OSError("disco cheio")

    monkeypatch.setattr(client, "write_heartbeat", falha)

    with pytest.raises(Parar):
        asyncio.run(pool.heartbeat_loop(str(tmp_path / "saude"), clock=lambda: 1.0, sleep=sleep_que_para_em(2, dormiu)))

    assert len(dormiu) == 2


# ============================================================================ start_heartbeat (V11) e shutdown


@pytest.fixture
def laco():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def encerrar(loop, pool):
    pool.heartbeat_task.cancel()
    loop.run_until_complete(asyncio.gather(pool.heartbeat_task, return_exceptions=True))


def test_start_heartbeat_removes_the_inherited_file_before_anything_is_written(tmp_path, monkeypatch, laco):
    arquivo = tmp_path / "saude"
    write_heartbeat(arquivo, 1.0)
    monkeypatch.setenv(HEALTH_FILE_ENV, str(arquivo))
    pool = pool_com()
    pool.loop = laco

    pool.start_heartbeat()

    assert not arquivo.exists()
    assert isinstance(pool.heartbeat_task, asyncio.Task)
    encerrar(laco, pool)


def test_start_heartbeat_still_starts_the_task_when_the_old_file_cannot_be_removed(monkeypatch, laco):
    monkeypatch.setenv(HEALTH_FILE_ENV, "/qualquer/saude")

    def falha(caminho):
        raise PermissionError("sem permissão")

    monkeypatch.setattr(client, "clear_heartbeat", falha)
    pool = pool_com()
    pool.loop = laco

    pool.start_heartbeat()

    assert isinstance(pool.heartbeat_task, asyncio.Task)
    encerrar(laco, pool)


def test_without_the_variable_start_heartbeat_does_nothing(monkeypatch, laco):
    monkeypatch.delenv(HEALTH_FILE_ENV, raising=False)
    pool = pool_com()
    pool.loop = laco

    pool.start_heartbeat()

    assert pool.heartbeat_task is None and not laco.is_running() and not asyncio.all_tasks(laco)


def test_shutdown_cancels_the_heartbeat_task():
    cancelada = []
    pool = pool_com()
    pool.heartbeat_task = SimpleNamespace(cancel=lambda: cancelada.append(True))
    pool.lavalink_instance = None

    asyncio.run(pool.shutdown(0))

    assert cancelada == [True]


# ============================================================================ clear_heartbeat


def test_clear_heartbeat_removes_the_file_and_tolerates_its_absence(tmp_path):
    arquivo = tmp_path / "saude"
    write_heartbeat(arquivo, 1.0)

    clear_heartbeat(arquivo)
    clear_heartbeat(arquivo)

    assert not arquivo.exists()
    assert health.is_fresh(arquivo, 1.0) is False

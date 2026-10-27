"""Item 7 (P3, K11h) — o resumo COMPLETO do ``logs_loop`` com um pool falso: as fontes reais de cada campo.

``bot.latency`` (segundos) vira ms; o p95 de voz vem de ``player.ping`` ignorando ``None``; nó com ``stats`` mostra players/CPU/memória e nó sem
``stats`` mostra ``indisponível``; o ``process_stats`` é injetado. Contrato que este teste FIXA (a K11 só diz "devolve ``(cpu, rss)``"):
``process_stats(pid=None) -> (cpu_percent, rss_mib)``, sem argumento para o processo Python e com o ``pid`` do Java (``pool.lavalink_instance.pid``)
quando há Lavalink local. Relógio e ``sleep`` injetados; ``configure_logging`` REAL com o mesmo relógio.
"""

import asyncio
import io
import logging
from types import SimpleNamespace

import pytest

from empiremuse.logs.metrics import MetricsCollector
from empiremuse.logs.setup import configure_logging
from empiremuse.logs.settings import LogSettings
from empiremuse.utils.client import BotPool
from empiremuse.wavelink.stats import Stats
from tests.logs.apoio import Relogio

pytestmark = pytest.mark.critical

MIB = 1024 * 1024
PID_DO_JAVA = 4242
PYTHON = (12.5, 345.6)
JAVA = (80.0, 900.0)


class Parar(BaseException):
    pass


class Bot:
    """Hashable (``get_all_bots`` usa um ``set``)."""

    def __init__(self, latency, guilds, nos, jogadores) -> None:
        self.latency = latency
        self.guilds = list(range(guilds))
        self.bot_ready = True
        self.music = SimpleNamespace(nodes=nos, players=jogadores)


def stats_reais(no, *, players=12, tocando=7, carga=0.035, sistema=0.2, usada=220, alocada=512):
    return Stats(
        no,
        {
            "uptime": 1000,
            "players": players,
            "playingPlayers": tocando,
            "memory": {"free": 1, "used": usada * MIB, "allocated": alocada * MIB, "reservable": alocada * MIB},
            "cpu": {"cores": 4, "systemLoad": sistema, "lavalinkLoad": carga},
            "frameStats": {"sent": 1, "nulled": 0, "deficit": 0},
        },
    )


def no_com_stats(identificador="N-OK", **campos):
    no = SimpleNamespace(identifier=identificador, is_available=True, players={}, stats=None)
    no.stats = stats_reais(no, **campos)
    return no


def no_sem_stats(identificador="N-SEM"):
    return SimpleNamespace(identifier=identificador, is_available=True, players={}, stats=None)


def jogador(ping):
    return SimpleNamespace(ping=ping, current=SimpleNamespace(title="x"), is_paused=False)


class Cenario:
    def __init__(self, *, bots, lavalink_local: bool = False) -> None:
        self.relogio = Relogio()
        self.console = io.StringIO()
        configure_logging(
            LogSettings(logging.INFO, False, False, frozenset(), 300), [], stream=self.console, clock=self.relogio
        )
        self.pool = BotPool.__new__(BotPool)
        self.pool.config = {"METRICS_INTERVAL": 300}
        self.pool.bots, self.pool.guild_bots = list(bots), {}
        self.pool.metrics = MetricsCollector()
        self.pool.logs_task = None
        self.pool.lavalink_instance = SimpleNamespace(pid=PID_DO_JAVA) if lavalink_local else None
        self.chamadas: list[tuple] = []

    def process_stats(self, *args):
        self.chamadas.append(args)
        alvo = args[0] if args else None
        return PYTHON if alvo is None else JAVA

    def rodar(self) -> list[str]:
        async def sleep(segundos):
            self.relogio.avancar(segundos)
            self.voltas += 1
            if self.voltas >= 11:
                raise Parar

        self.voltas = 0
        with pytest.raises(Parar):
            asyncio.run(self.pool.logs_loop(clock=self.relogio, sleep=sleep, process_stats=self.process_stats))
        return [linha for linha in self.console.getvalue().splitlines() if "📊" in linha]


def pings(valores, nulos=0):
    return {n: jogador(valor) for n, valor in enumerate([*valores, *([None] * nulos)])}


class TestPrimeiraLinha:
    def test_the_gateway_latency_in_seconds_is_shown_in_milliseconds(self):
        cenario = Cenario(bots=[Bot(0.05, 3, {}, {})])

        primeira = cenario.rodar()[0]

        assert "gateway" in primeira and ("50ms" in primeira or "50 ms" in primeira)
        assert "máx 50" in primeira and "0.05" not in primeira

    def test_with_two_bots_the_maximum_is_the_highest_latency(self):
        cenario = Cenario(bots=[Bot(0.05, 2, {}, {}), Bot(0.12, 2, {}, {})])

        primeira = cenario.rodar()[0]

        assert "máx 120" in primeira

    def test_the_guild_count_comes_from_the_bots(self):
        cenario = Cenario(bots=[Bot(0.05, 3, {}, {})])

        assert "servidores 3" in cenario.rodar()[0]

    def test_the_voice_p95_comes_from_the_player_pings_ignoring_none(self):
        # 100 pings de 1 a 100 ms e 100 players sem ping: contando os None como zero o p95 cairia para ~90
        cenario = Cenario(bots=[Bot(0.05, 1, {}, pings([float(n) for n in range(1, 101)], nulos=100))])

        primeira = cenario.rodar()[0]

        assert "voz p95 95" in primeira or "voz p95 96" in primeira or "voz p95 95.05" in primeira

    def test_players_without_any_ping_show_a_dash_for_the_voice(self):
        cenario = Cenario(bots=[Bot(0.05, 1, {}, pings([], nulos=5))])

        primeira = cenario.rodar()[0]

        assert "voz p95 —" in primeira

    def test_the_python_process_figures_come_from_the_injected_process_stats(self):
        cenario = Cenario(bots=[Bot(0.05, 1, {}, {})])

        primeira = cenario.rodar()[0]

        assert "CPU 12.5%" in primeira and "RSS 345.6" in primeira
        assert () in cenario.chamadas  # o processo Python: sem argumento

    def test_the_summary_line_has_the_documented_shape_with_active_players_and_peak(self):
        cenario = Cenario(bots=[Bot(0.05, 1, {}, pings([10.0, 20.0, 30.0]))])

        primeira = cenario.rodar()[0]

        assert primeira.count("📊") == 1
        assert "players ativos" in primeira and "(pico" in primeira and "faixas iniciadas" in primeira


class TestNos:
    def test_a_node_with_stats_shows_players_cpu_and_memory(self):
        no = no_com_stats("N-OK", players=12, tocando=7, carga=0.035, sistema=0.2, usada=220, alocada=512)
        cenario = Cenario(bots=[Bot(0.05, 1, {no.identifier: no}, {})])

        linhas = cenario.rodar()

        (linha,) = [x for x in linhas if "N-OK" in x]
        assert "nó N-OK" in linha and "indisponível" not in linha
        assert "players 12" in linha or "players 7" in linha
        assert "CPU 3.5%" in linha or "CPU 20%" in linha
        assert "memória 220" in linha or "memória 512" in linha

    def test_a_node_without_stats_is_unavailable(self):
        no = no_sem_stats("N-SEM")
        cenario = Cenario(bots=[Bot(0.05, 1, {no.identifier: no}, {})])

        linhas = cenario.rodar()

        (linha,) = [x for x in linhas if "N-SEM" in x]
        assert "indisponível" in linha and "players" not in linha

    def test_two_nodes_give_one_plus_two_lines_per_interval(self):
        nos = {n.identifier: n for n in (no_com_stats("A"), no_sem_stats("B"))}
        cenario = Cenario(bots=[Bot(0.05, 1, nos, {})])

        linhas = cenario.rodar()

        assert len(linhas) == 2 * 3  # dois resumos (t = 300 e 600) de 1 + 2 linhas

    def test_a_node_shared_by_two_bots_is_listed_once(self):
        no = no_com_stats("COMPARTILHADO")
        cenario = Cenario(bots=[Bot(0.05, 1, {no.identifier: no}, {}), Bot(0.06, 1, {no.identifier: no}, {})])

        linhas = cenario.rodar()

        assert len([x for x in linhas if "COMPARTILHADO" in x]) == 2  # uma por resumo, nunca uma por bot


class TestLavalinkLocal:
    def test_without_a_local_lavalink_there_is_no_java_part(self):
        no = no_sem_stats("LOCAL")
        cenario = Cenario(bots=[Bot(0.05, 1, {"LOCAL": no}, {})], lavalink_local=False)

        linhas = cenario.rodar()

        assert [c for c in cenario.chamadas if c] == []  # process_stats nunca recebeu um pid
        assert "900" not in "".join(linhas)

    def test_with_a_local_lavalink_the_java_process_figures_are_read_by_its_pid_and_shown(self):
        no = no_sem_stats("LOCAL")
        cenario = Cenario(bots=[Bot(0.05, 1, {"LOCAL": no}, {})], lavalink_local=True)

        linhas = cenario.rodar()

        assert (PID_DO_JAVA,) in cenario.chamadas
        texto = "".join(linhas)
        assert "900" in texto and "80" in texto
        assert len(linhas) == 2 * 2  # a parte do Java entra na linha do nó, não numa linha a mais

    def test_the_python_figures_are_still_in_the_first_line_with_a_local_lavalink(self):
        cenario = Cenario(bots=[Bot(0.05, 1, {}, {})], lavalink_local=True)

        primeira = cenario.rodar()[0]

        assert "CPU 12.5%" in primeira and "RSS 345.6" in primeira


class TestFalhaDeFonte:
    def test_a_process_stats_that_returns_none_shows_dashes_and_does_not_stop_the_summary(self):
        cenario = Cenario(bots=[Bot(0.05, 1, {}, {})])
        cenario.process_stats = lambda *args: (None, None)

        primeira = cenario.rodar()[0]

        assert "CPU —" in primeira and "RSS —" in primeira

    def test_a_latency_that_is_none_shows_a_dash(self):
        cenario = Cenario(bots=[Bot(None, 1, {}, {})])

        assert "gateway —" in cenario.rodar()[0]

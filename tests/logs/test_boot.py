"""Item 7 (P2, Turbine) — relatório de subida: B9 (``BootReport``), B10 (versão nova), B11 (sem ``print``), B11b (stderr do Java).

``BootReport`` e ``check_new_version`` vêm de ``empiremuse.logs.boot`` (contrato 3.12). A captura é um handler SEM filtros no root (vê o
registro cru, antes do redator): o que o código mandou ao log, não o que o redator limpou. Relógio e rede injetados; nada dorme.
"""

import ast
import asyncio
import io
import json
import logging
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse import paths
from empiremuse.logs.boot import BootReport, check_new_version
from empiremuse.logs.redact import register_secret
from empiremuse.logs.setup import configure_logging, flush_logging
from empiremuse.logs.settings import LogSettings
from empiremuse.rules.release import Version, parse_current_version
from empiremuse.updater import releases
from empiremuse.updater.git_flow import UpdateError
from empiremuse.utils import client
from empiremuse.utils.music import local_lavalink
from tests.logs.test_secret_sources import fabrica, no_json, runtime, sem_rede  # noqa: F401 - fixtures reaproveitadas
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

RAIZ_DO_BOT = RAIZ / "empiremuse"


class Captura(logging.Handler):
    """Registros crus que chegam ao root (sem filtro nenhum): o que o código mandou, antes de redigir."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.registros: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(record)

    def do_logger(self, prefixo: str) -> list[logging.LogRecord]:
        return [r for r in self.registros if r.name == prefixo or r.name.startswith(prefixo + ".")]


@pytest.fixture
def captura():
    raiz = logging.getLogger()
    handler, nivel = Captura(), raiz.level
    raiz.addHandler(handler)
    raiz.setLevel(logging.DEBUG)
    yield handler
    raiz.removeHandler(handler)
    raiz.setLevel(nivel)


def so_boot(captura) -> list[logging.LogRecord]:
    return captura.do_logger("empiremuse.boot")


# ============================================================================ B9 — BootReport


class TestBootReport:
    @pytest.mark.parametrize(
        ("status", "nivel"), [("ok", logging.INFO), ("warn", logging.WARNING), ("fail", logging.ERROR)]
    )
    def test_each_status_maps_to_its_level_on_the_boot_logger(self, captura, status, nivel):
        BootReport().step("Etapa X", status, "detalhe Y")

        (registro,) = so_boot(captura)
        assert registro.name == "empiremuse.boot" and registro.levelno == nivel
        assert "Etapa X" in registro.getMessage() and "detalhe Y" in registro.getMessage()

    def test_a_custom_logger_is_used_when_given(self, captura):
        BootReport(logging.getLogger("empiremuse.boot.outro")).step("Etapa", "ok")

        assert [r.name for r in captura.registros] == ["empiremuse.boot.outro"]

    def test_the_elapsed_time_shows_up_in_the_line(self, captura):
        BootReport().step("Mongo", "ok", "ping", elapsed=0.0123)

        assert "12" in so_boot(captura)[0].getMessage()

    def test_a_step_without_detail_or_elapsed_is_still_one_clean_line(self, captura):
        BootReport().step("Etapa", "ok")

        (registro,) = so_boot(captura)
        assert "\n" not in registro.getMessage() and "Etapa" in registro.getMessage()

    def test_deferred_steps_are_silent_until_flush_and_then_come_out_in_order(self, captura):
        relatorio = BootReport()

        relatorio.defer("Pasta de execução", "ok", "/dados")
        relatorio.defer("Python", "ok", "3.14")
        relatorio.defer("Aviso", "warn", "algo")
        assert so_boot(captura) == []
        relatorio.flush_deferred()

        assert [r.levelno for r in so_boot(captura)] == [logging.INFO, logging.INFO, logging.WARNING]
        mensagens = [r.getMessage() for r in so_boot(captura)]
        assert "Pasta de execução" in mensagens[0] and "Python" in mensagens[1] and "Aviso" in mensagens[2]

    def test_flush_deferred_is_idempotent(self, captura):
        relatorio = BootReport()
        relatorio.defer("Python", "ok", "3.14")

        relatorio.flush_deferred()
        relatorio.flush_deferred()

        assert len(so_boot(captura)) == 1

    def test_a_step_after_the_flush_comes_out_after_the_deferred_ones(self, captura):
        relatorio = BootReport()
        relatorio.defer("Antes", "ok")
        relatorio.flush_deferred()

        relatorio.step("Depois", "ok")

        mensagens = [r.getMessage() for r in so_boot(captura)]
        assert "Antes" in mensagens[0] and "Depois" in mensagens[1]

    def test_flush_with_nothing_deferred_logs_nothing(self, captura):
        BootReport().flush_deferred()

        assert so_boot(captura) == []

    def test_a_detail_with_a_registered_secret_is_masked_by_the_pipeline(self, tmp_path):
        console = io.StringIO()
        register_secret("senha-no-detalhe-da-etapa-1")
        configure_logging(LogSettings(logging.INFO, False, False, frozenset(), 300), [], stream=console)

        BootReport().step("Nó", "ok", "conectado com senha-no-detalhe-da-etapa-1")

        assert "senha-no-detalhe-da-etapa-1" not in console.getvalue() and "***" in console.getvalue()


# ============================================================================ B9 — o que a subida real manda ao log


class TestSubidaReal:
    def test_the_mongo_uri_with_a_password_never_reaches_the_boot_lines(self, fabrica, captura, monkeypatch):  # noqa: F811
        senha = "senha-do-mongo-da-subida-Z9"
        uri = f"mongodb+srv://usuario:{senha}@cluster0.exemplo.net/banco"
        monkeypatch.setattr(client, "MongoDatabase", MagicMock())
        pool = fabrica(MONGO=uri)

        pool.setup()

        boot = so_boot(captura)
        assert boot, "a subida não registrou nenhuma etapa em empiremuse.boot"
        for registro in boot:
            texto = registro.getMessage()
            assert (
                senha not in texto
                and "usuario" not in texto
                and "cluster0.exemplo.net" not in texto
                and uri not in texto
            )
        assert any("mongo" in r.getMessage().lower() for r in boot)

    def test_a_node_with_a_password_never_shows_it_during_the_setup(self, fabrica, captura):  # noqa: F811
        senha = "senha-do-no-da-subida-Y8"
        pool = fabrica(LAVALINK_NODE_1=no_json(senha, "NO_DA_SUBIDA"))

        pool.setup()

        textos = [r.getMessage() for r in captura.registros]
        assert not any(senha in t for t in textos)

    @pytest.mark.asyncio
    async def test_a_node_check_shows_only_the_identifier_and_the_result_never_the_password(self, captura, monkeypatch):
        senha = "senha-do-no-verificado-X7"

        class Resposta:
            status = 403

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class Sessao:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get(self, *args, **kwargs):
                return Resposta()

        monkeypatch.setattr(client.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(client.aiohttp, "ClientSession", Sessao)
        pool = client.BotPool.__new__(client.BotPool)

        await pool.check_node(
            {"host": "10.1.2.3", "port": 2333, "password": senha, "identifier": "NO_VERIFICADO", "retries": 1}
        )

        textos = [r.getMessage() for r in captura.registros if r.name.startswith("empiremuse")]
        assert any("NO_VERIFICADO" in t for t in textos)
        assert not any(senha in t or "10.1.2.3" in t for t in textos)

    def test_the_boot_lines_of_a_normal_setup_are_at_info_or_below_and_never_print(self, fabrica, captura, capsys):  # noqa: F811
        pool = fabrica()

        pool.setup()

        assert all(r.levelno <= logging.WARNING for r in so_boot(captura))
        assert "Database em uso" not in capsys.readouterr().out


class TestFalhaDeCog:
    @pytest.fixture
    def bot_falso(self):
        from disnake.ext import commands

        class Carregador:
            falhar = "ll_yt_oauth"

            def __init__(self) -> None:
                self.user = "bot"
                self.identifier = "id"
                self.bot_ready = True
                self.config = {"ENABLE_DISCORD_URLS_PLAYBACK": True}
                self.slash_commands = []
                self.remove_slash_command = MagicMock()

            def unload_extension(self, nome):
                raise commands.ExtensionNotLoaded(nome)

            def load_extension(self, nome):
                if nome.endswith("." + self.falhar):
                    raise RuntimeError(f"explodiu ao carregar {nome} com detalhe-interno")

        return Carregador()

    def test_a_failing_cog_is_reported_with_its_module_and_the_exception_type_without_a_traceback(
        self, bot_falso, captura
    ):
        captura.registros.clear()
        logging.getLogger().setLevel(logging.INFO)

        status = client.BotCore.load_modules(bot_falso)

        assert any("ll_yt_oauth" in f for f in status["failed"])
        achados = [r for r in captura.registros if "ll_yt_oauth" in r.getMessage() and r.levelno >= logging.WARNING]
        assert achados and all(r.exc_info is None for r in achados)
        assert any("RuntimeError" in r.getMessage() for r in achados)

    def test_the_traceback_of_the_failing_cog_exists_only_at_debug(self, bot_falso, captura):
        client.BotCore.load_modules(bot_falso)

        com_traceback = [r for r in captura.registros if r.exc_info and r.exc_info[0] is RuntimeError]
        assert com_traceback and all(r.levelno == logging.DEBUG for r in com_traceback)

    def test_a_failing_cog_never_goes_through_print(self, bot_falso, capsys):
        client.BotCore.load_modules(bot_falso)

        saida = capsys.readouterr()
        assert "Falha ao carregar" not in saida.out and "Traceback" not in saida.err


# ============================================================================ B10 — versão nova (relógio e rede injetados)


def lista_de(*versoes: str):
    async def listar(session):
        return [
            releases.Release(Version(*map(int, v.split("."))), f"v{v}", f"https://exemplo.invalido/{v}")
            for v in versoes
        ]

    return listar


async def checar(captura, *, lista, atual, timeout=10.0):
    captura.registros.clear()
    await check_new_version(list_releases=lista, current=lambda: atual, timeout=timeout)
    return [r for r in captura.registros if r.name.startswith("empiremuse")]


class TestVersaoNova:
    @pytest.mark.asyncio
    async def test_a_higher_release_gives_an_info_line_with_both_versions(self, captura):
        registros = await checar(captura, lista=lista_de("2.2.0", "2.1.0"), atual=Version(2, 1, 0))

        infos = [r for r in registros if r.levelno == logging.INFO]
        assert len(infos) == 1 and "Versão 2.2.0 disponível (instalada 2.1.0)" in infos[0].getMessage()

    @pytest.mark.asyncio
    async def test_an_installed_rc_is_offered_its_stable(self, captura):
        registros = await checar(captura, lista=lista_de("2.1.0"), atual=parse_current_version("2.1.0-rc.2"))

        (info,) = [r for r in registros if r.levelno == logging.INFO]
        assert "Versão 2.1.0 disponível (instalada 2.1.0-rc.2)" in info.getMessage()

    @pytest.mark.asyncio
    async def test_the_greatest_release_is_the_one_announced(self, captura):
        registros = await checar(captura, lista=lista_de("2.3.0", "2.2.1", "2.2.0"), atual=Version(2, 1, 0))

        (info,) = [r for r in registros if r.levelno == logging.INFO]
        assert "Versão 2.3.0 disponível" in info.getMessage()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("versoes", [("2.1.0",), ("2.0.0", "2.1.0"), ("2.0.9",), ()])
    async def test_an_equal_or_older_release_logs_nothing_above_debug(self, captura, versoes):
        registros = await checar(captura, lista=lista_de(*versoes), atual=Version(2, 1, 0))

        assert [r for r in registros if r.levelno > logging.DEBUG] == []

    @pytest.mark.asyncio
    async def test_without_a_known_current_version_it_logs_nothing_above_debug(self, captura):
        registros = await checar(captura, lista=lista_de("9.9.9"), atual=None)

        assert [r for r in registros if r.levelno > logging.DEBUG] == []

    @pytest.mark.asyncio
    async def test_an_error_gives_a_single_debug_line_and_nothing_louder(self, captura):
        async def falha(session):
            raise UpdateError("Não consegui consultar as versões publicadas agora.")

        registros = await checar(captura, lista=falha, atual=Version(2, 1, 0))

        assert len(registros) == 1 and registros[0].levelno == logging.DEBUG

    @pytest.mark.asyncio
    async def test_an_unexpected_exception_is_also_only_debug(self, captura):
        async def falha(session):
            raise RuntimeError("boom")

        registros = await checar(captura, lista=falha, atual=Version(2, 1, 0))

        assert registros and all(r.levelno == logging.DEBUG for r in registros)

    @pytest.mark.asyncio
    async def test_a_timeout_gives_only_debug_and_does_not_hang(self, captura):
        async def pendurada(session):
            await asyncio.Event().wait()

        registros = await checar(captura, lista=pendurada, atual=Version(2, 1, 0), timeout=0)

        assert registros and all(r.levelno == logging.DEBUG for r in registros)

    @pytest.mark.asyncio
    async def test_the_check_does_not_use_the_real_network(self, captura, sem_rede):  # noqa: F811
        registros = await checar(captura, lista=lista_de("2.2.0"), atual=Version(2, 1, 0))

        assert any(r.levelno == logging.INFO for r in registros)


# ============================================================================ B11 — nenhum print nos módulos do P2 (AST)

PROIBIDAS = {"print_exc", "print_exception", "print_stack", "pprint"}
FUNCOES_DO_CLIENT = {
    "read_guild_bots",
    "load_cfg",
    "load_skins",
    "setup",
    "initial_setup",
    "node_check",
    "start_lavalink",
    "start_bot",
    "check_node",
    "setup_pool_extras",
    "sync_app_commands",
    "load_modules",
    "update_appinfo",
}


def chamadas_proibidas(no: ast.AST) -> list[int]:
    linhas = []
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Call):
            continue
        funcao = filho.func
        if (isinstance(funcao, ast.Name) and funcao.id in ("print", "pprint")) or (
            isinstance(funcao, ast.Attribute) and funcao.attr in PROIBIDAS
        ):
            linhas.append(filho.lineno)
    return linhas


@pytest.mark.parametrize(
    "arquivo",
    [
        "__main__.py",
        "utils/music/local_lavalink.py",
        "utils/music/remote_lavalink_serverlist.py",
        "logs/boot.py",
    ],
)
def test_no_print_or_print_exc_in_the_modules_touched_by_phase_two(arquivo):
    arvore = ast.parse((RAIZ_DO_BOT / arquivo).read_text(encoding="utf-8"))

    assert chamadas_proibidas(arvore) == [], f"{arquivo}: print/print_exc nas linhas {chamadas_proibidas(arvore)}"


def test_no_print_or_print_exc_in_the_phase_two_functions_of_client():
    arvore = ast.parse((RAIZ_DO_BOT / "utils/client.py").read_text(encoding="utf-8"))
    encontradas, restantes = set(), {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef) and no.name in FUNCOES_DO_CLIENT:
            encontradas.add(no.name)
            if linhas := chamadas_proibidas(no):
                restantes[no.name] = linhas

    assert encontradas == FUNCOES_DO_CLIENT, f"funções que sumiram do client.py: {FUNCOES_DO_CLIENT - encontradas}"
    assert restantes == {}, f"print/print_exc em {restantes}"


# ============================================================================ B11b — stderr do Java do Lavalink local (V-L9)


class SemQuebra(str):
    """Última linha do Java sem ``\\n`` no fim (o processo morreu no meio dela)."""


class StderrFalso:
    """Fluxo que serve linhas de ``str`` e de ``bytes`` (o código pode ler de qualquer forma) e sinaliza o fim da leitura."""

    class Linha(str):
        def decode(self, *args, **kwargs):
            return str(self)

        def encode(self, *args, **kwargs):
            return str(self).encode("utf-8")

    class Fim(str):
        def __eq__(self, other):
            return other in ("", b"", None) or str.__eq__(self, other)

        __hash__ = str.__hash__

        def __bool__(self):
            return False

        def decode(self, *args, **kwargs):
            return ""

    def __init__(self, linhas, terminou: threading.Event) -> None:
        self._linhas = [self.Linha(linha if isinstance(linha, SemQuebra) else linha + "\n") for linha in linhas]
        self._fim = terminou

    def readline(self, *args):
        if self._linhas:
            return self._linhas.pop(0)
        self._fim.set()
        return self.Fim("")

    def __iter__(self):
        return self

    def __next__(self):
        linha = self.readline()
        if not linha:
            raise StopIteration
        return linha

    def close(self):
        return None


class ProcessoFalso:
    def __init__(self, linhas, terminou, **kwargs) -> None:
        self.args, self.kwargs = kwargs.get("args"), kwargs
        self.stderr = StderrFalso(linhas, terminou)
        self.stdout = None
        self.pid = 4242
        self.returncode = None

    def wait(self, *args, **kwargs):
        self.returncode = 0
        return 0

    def poll(self):
        return None

    def kill(self):
        return None

    def terminate(self):
        return None


@pytest.fixture
def lavalink_com_stderr(tmp_path, monkeypatch):
    """Roda o ``run_lavalink`` REAL com Java, arquivos e ``Popen`` dublados; devolve o console do ``configure_logging`` real."""
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "lavalink").mkdir()
    monkeypatch.setattr(
        local_lavalink.platform, "architecture", lambda *a, **k: ("64bit", "ELF")
    )  # o real roda ``file`` via Popen
    monkeypatch.setattr(local_lavalink, "_configured_java", lambda caminho: "java")
    monkeypatch.setattr(local_lavalink, "prepare_lavalink_files", lambda *a, **k: None)
    monkeypatch.setattr(local_lavalink, "_java_command", lambda *a, **k: ["java", "-jar", "Lavalink.jar"])
    monkeypatch.setattr(local_lavalink, "java_major_version", lambda cmd, *a, **k: 21)

    def executar(linhas, arquivo=False):
        terminou = threading.Event()
        monkeypatch.setattr(
            local_lavalink.subprocess,
            "Popen",
            lambda args, **kwargs: ProcessoFalso(linhas, terminou, args=args, **kwargs),
        )
        console = io.StringIO()
        configure_logging(
            LogSettings(logging.INFO, False, arquivo, frozenset(), 300), [], stream=console, logs_dir=tmp_path / ".logs"
        )
        local_lavalink.run_lavalink(
            lavalink_java_path="java", lavalink_home=str(tmp_path / "lavalink"), lavalink_offline=True
        )
        assert terminou.wait(timeout=3), "o stderr do Java nunca foi lido até o fim"
        flush_logging()
        return console.getvalue()

    return executar


class TestStderrDoJava:
    def test_a_line_with_the_lavalink_password_goes_through_the_wavelink_local_logger_redacted(
        self, lavalink_com_stderr
    ):
        senha = "senha-do-lavalink-no-stderr-W7"
        register_secret(senha)

        saida = lavalink_com_stderr([f"ERROR conexão recusada com a senha {senha} no cabeçalho"])

        linhas = [linha for linha in saida.splitlines() if "empiremuse.wavelink.local" in linha]
        assert len(linhas) == 1 and "WARNING" in linhas[0]
        assert senha not in saida and "***" in linhas[0] and "conexão recusada" in linhas[0]

    @pytest.mark.parametrize("sujeira", ["\x1b[2J\x1b[31mlimpa a tela", "tem \x9b e ‮ dentro", "carriage\rreturn"])
    def test_control_characters_in_a_stderr_line_are_neutralised(self, lavalink_com_stderr, sujeira):
        saida = lavalink_com_stderr([sujeira])

        assert len(saida.splitlines()) == 1 and "empiremuse.wavelink.local" in saida
        assert not any(c in saida for c in ("\x1b", "\x9b", "‮", "\r"))

    def test_the_java_stderr_never_goes_to_the_real_stderr_or_stdout(self, lavalink_com_stderr, capfd):
        lavalink_com_stderr(["linha do java"])

        saida = capfd.readouterr()
        assert "linha do java" not in saida.out and "linha do java" not in saida.err

    def test_run_lavalink_asks_popen_to_pipe_the_stderr(self, tmp_path, monkeypatch, lavalink_com_stderr):
        capturado = {}
        terminou = threading.Event()

        def popen(args, **kwargs):
            capturado.update(kwargs)
            return ProcessoFalso([], terminou, args=args, **kwargs)

        lavalink_com_stderr(["x"])
        monkeypatch.setattr(local_lavalink.subprocess, "Popen", popen)
        local_lavalink.run_lavalink(
            lavalink_java_path="java", lavalink_home=str(tmp_path / "lavalink"), lavalink_offline=True
        )

        assert capturado.get("stderr") not in (
            None,
            local_lavalink.subprocess.DEVNULL,
            local_lavalink.subprocess.STDOUT,
        )


# ============================================================================ integração — subida falsa com console e arquivo reais


class TestIntegracaoDaSubida:
    @pytest.fixture
    def destinos(self, tmp_path):
        console = io.StringIO()
        configure_logging(
            LogSettings(logging.INFO, False, True, frozenset(), 300), [], stream=console, logs_dir=tmp_path / ".logs"
        )
        return SimpleNamespace(console=console, arquivo=tmp_path / ".logs" / "disnake.log")

    def textos(self, destinos):
        return [destinos.console.getvalue(), destinos.arquivo.read_text(encoding="utf-8")]

    def test_a_fake_boot_comes_out_in_order_in_both_destinations(self, destinos):
        relatorio = BootReport()
        relatorio.defer("Pasta de execução", "ok", "/dados")
        relatorio.defer("Python", "ok", "3.14")
        relatorio.flush_deferred()
        relatorio.step("Banco", "ok", "local", elapsed=0.002)
        relatorio.step("Cogs", "warn", "1 falhou")
        relatorio.step("Lavalink", "fail", "sem nós")

        for texto in self.textos(destinos):
            posicoes = [texto.index(nome) for nome in ("Pasta de execução", "Python", "Banco", "Cogs", "Lavalink")]
            assert posicoes == sorted(posicoes)
            assert texto.count("Pasta de execução") == 1 and texto.count("Python") == 1
            assert "INFO" in texto and "WARNING" in texto and "ERROR" in texto

    def test_the_console_has_the_boot_emoji_and_the_file_does_not(self, destinos):
        BootReport().step("Etapa", "ok", "detalhe")

        console, arquivo = self.textos(destinos)
        assert "🚀" in console and "🚀" not in arquivo and "empiremuse.boot" in arquivo

    def test_the_deferred_steps_are_emitted_only_once_the_logging_is_configured(self, tmp_path):
        relatorio = BootReport()
        relatorio.defer("Antes do log", "ok", "x")
        console = io.StringIO()
        assert console.getvalue() == ""

        configure_logging(LogSettings(logging.INFO, False, False, frozenset(), 300), [], stream=console)
        relatorio.flush_deferred()

        assert console.getvalue().count("Antes do log") == 1

    def test_a_secret_in_a_step_detail_is_masked_in_both_destinations(self, destinos):
        register_secret("segredo-da-etapa-integrada-5")

        BootReport().step("Nó", "warn", "falhou com segredo-da-etapa-integrada-5")

        for texto in self.textos(destinos):
            assert "segredo-da-etapa-integrada-5" not in texto and "***" in texto


# ============================================================================ V-P2-1 — linhas distintas do Java não se agregam entre si

SONDA_DO_VIGIL = [
    "Exception in thread main java.lang.IllegalStateException: falhou ao subir",
    "\tat com.exemplo.Servidor.iniciar(Servidor.java:42)",
    "\tat com.exemplo.Principal.main(Principal.java:7)",
    "Caused by: java.net.BindException: Address already in use",
    "linha com \x1b[2J e \u202e dentro",
    SemQuebra("última linha sem quebra"),
]


class TestLinhasDistintasDoJava:
    def textos(self, lavalink_com_stderr, tmp_path, linhas):
        console = lavalink_com_stderr(linhas, arquivo=True)
        return console, (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")

    def test_six_distinct_lines_give_six_lines_in_each_destination_and_no_repeat_summary(
        self, lavalink_com_stderr, tmp_path
    ):
        for texto in self.textos(lavalink_com_stderr, tmp_path, SONDA_DO_VIGIL):
            linhas = [linha for linha in texto.splitlines() if linha]
            assert len(linhas) == 6, linhas
            assert all("empiremuse.wavelink.local" in linha for linha in linhas)
            assert "↻" not in texto and "repetida" not in texto

    def test_the_root_cause_line_is_in_the_log(self, lavalink_com_stderr, tmp_path):
        for texto in self.textos(lavalink_com_stderr, tmp_path, SONDA_DO_VIGIL):
            assert "Caused by: java.net.BindException: Address already in use" in texto
            assert "última linha sem quebra" in texto

    def test_every_output_line_starts_with_a_header_so_nothing_sits_at_column_zero(self, lavalink_com_stderr, tmp_path):
        console, arquivo = self.textos(lavalink_com_stderr, tmp_path, SONDA_DO_VIGIL)

        for linha in console.splitlines():
            assert re.match(r"\d{2}:\d{2}:\d{2} ", linha), linha
        for linha in arquivo.splitlines():
            assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ", linha), linha

    def test_controls_and_the_registered_password_are_still_neutralised_in_the_distinct_lines(
        self, lavalink_com_stderr, tmp_path
    ):
        senha = "senha-do-java-nas-distintas-V2"
        register_secret(senha)
        linhas = [f"tentando com {senha}", *SONDA_DO_VIGIL]

        for texto in self.textos(lavalink_com_stderr, tmp_path, linhas):
            assert senha not in texto and "***" in texto
            assert not any(c in texto for c in ("\x1b", "\u202e", "\r"))
            assert len([linha for linha in texto.splitlines() if linha]) == 7

    def test_the_same_line_a_hundred_times_in_a_burst_still_aggregates(self, lavalink_com_stderr, tmp_path):
        for texto in self.textos(lavalink_com_stderr, tmp_path, ["conexão recusada pelo Java"] * 100):
            assert texto.count("conexão recusada pelo Java") == 2  # a 1ª ocorrência e a linha do resumo
            assert texto.count("repetida 99×") == 1 and texto.count("↻") == 1

    def test_distinct_lines_do_not_hide_inside_a_summary_of_a_repeated_one(self, lavalink_com_stderr, tmp_path):
        linhas = ["repetida A"] * 5 + ["única B"] + ["repetida A"] * 5

        for texto in self.textos(lavalink_com_stderr, tmp_path, linhas):
            assert "única B" in texto and texto.count("repetida 9×") == 1

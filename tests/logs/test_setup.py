"""Item 7 (P1, Turbine) — ``configure_logging`` (B8, B19, B6 ponta a ponta): handlers, cadeia de filtros, bibliotecas e arquivo.

O console é um ``StringIO``; o arquivo vai para ``tmp_path``; o relógio do agregador é injetado e o ``environ`` das configurações também.
"""

import io
import logging
import logging.handlers
import os
import stat
import sys

import pytest

from empiremuse.logs.setup import LIBRARY_LOGGERS, configure_logging, flush_logging, tick_logging
from empiremuse.logs.settings import LogSettings, parse_log_settings
from tests.logs.apoio import Espiao, Relogio

pytestmark = pytest.mark.critical

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="modos de arquivo POSIX")
A, B = 111111111111111111, 222222222222222222
CADEIA = ["ContextFilter", "LevelGate", "SanitizeAndRedact", "RepeatAggregator"]


def ajustes(*, nivel=logging.INFO, cor=False, arquivo=False, guildas=()):
    return LogSettings(nivel, cor, arquivo, frozenset(guildas), 300)


@pytest.fixture
def raiz():
    return logging.getLogger()


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def console():
    return io.StringIO()


@pytest.fixture
def instalar(raiz, console, relogio, tmp_path):
    """Chama o ``configure_logging`` real e devolve os handlers que ele instalou (console, arquivo)."""

    def _instalar(settings=None, segredos=(), **extra):
        for handler in list(
            raiz.handlers
        ):  # o handler de captura do pytest formataria os argumentos de todo DEBUG e mascararia o que se mede
            if type(handler).__module__.startswith("_pytest"):
                raiz.removeHandler(handler)
        antes = list(raiz.handlers)
        configure_logging(
            settings or ajustes(),
            segredos,
            stream=extra.pop("stream", console),
            logs_dir=extra.pop("logs_dir", tmp_path / ".logs"),
            clock=relogio,
            **extra,
        )
        novos = [h for h in raiz.handlers if h not in antes]
        consoles = [h for h in novos if not isinstance(h, logging.FileHandler)]
        arquivos = [h for h in novos if isinstance(h, logging.FileHandler)]
        return consoles, arquivos

    return _instalar


def nomes(filtros) -> list[str]:
    return [type(f).__name__ for f in filtros]


class TestHandlers:
    def test_one_console_handler_on_the_given_stream_and_none_for_the_file_when_off(self, instalar, console):
        consoles, arquivos = instalar(ajustes(arquivo=False))

        assert len(consoles) == 1 and arquivos == []
        assert isinstance(consoles[0], logging.StreamHandler) and consoles[0].stream is console

    def test_the_file_handler_is_added_when_the_file_is_on(self, instalar):
        consoles, arquivos = instalar(ajustes(arquivo=True))

        assert len(consoles) == 1 and len(arquivos) == 1
        assert isinstance(arquivos[0], logging.handlers.RotatingFileHandler)

    @pytest.mark.parametrize("com_arquivo", [False, True])
    def test_the_filter_chain_is_the_same_and_in_the_contract_order(self, instalar, com_arquivo):
        consoles, arquivos = instalar(ajustes(arquivo=com_arquivo))

        for handler in consoles + arquivos:
            cadeia = nomes(handler.filters)
            assert [n for n in cadeia if n in CADEIA] == CADEIA
            extras = [n for n in cadeia if n not in CADEIA]
            assert len(extras) == 1 and cadeia.index(extras[0]) < cadeia.index(
                "LevelGate"
            )  # o filtro do aviso de voz (2.1.2)

    def test_the_redactor_and_the_aggregator_are_shared_between_the_two_handlers(self, instalar):
        (console,), (arquivo,) = instalar(ajustes(arquivo=True))

        for nome in ("SanitizeAndRedact", "RepeatAggregator"):
            do_console = next(f for f in console.filters if type(f).__name__ == nome)
            do_arquivo = next(f for f in arquivo.filters if type(f).__name__ == nome)
            assert do_console is do_arquivo

    def test_the_formatters_are_the_console_and_the_file_ones(self, instalar):
        (console,), (arquivo,) = instalar(ajustes(arquivo=True))

        assert type(console.formatter).__name__ == "ConsoleFormatter"
        assert type(arquivo.formatter).__name__ == "FileFormatter"

    def test_configure_logging_returns_nothing(self, raiz, console, tmp_path):
        assert configure_logging(ajustes(), [], stream=console, logs_dir=tmp_path / ".logs") is None


class TestNivelDaRaiz:
    def test_the_root_follows_the_configured_level(self, instalar, raiz):
        instalar(ajustes(nivel=logging.WARNING))

        assert raiz.level == logging.WARNING

    def test_the_root_is_debug_when_there_are_debug_guilds(self, instalar, raiz):
        instalar(ajustes(nivel=logging.INFO, guildas={A}))

        assert raiz.level == logging.DEBUG

    def test_without_debug_guilds_a_discarded_debug_formats_nothing(self, instalar):
        instalar(ajustes(nivel=logging.INFO))
        espiao = Espiao()

        logging.getLogger("empiremuse.player").debug("faixa %s", espiao)

        assert espiao.chamadas == 0

    def test_with_debug_guilds_the_gate_drops_other_servers_before_formatting_anything(self, instalar, console):
        instalar(ajustes(nivel=logging.INFO, guildas={A}))
        espiao = Espiao()

        logging.getLogger("empiremuse.player").debug("faixa %s", espiao, extra={"guild": B})
        logging.getLogger("empiremuse.player").debug("sem servidor %s", espiao)

        assert espiao.chamadas == 0 and console.getvalue() == ""

    def test_the_debug_of_the_chosen_server_comes_out_and_the_others_do_not(self, instalar, console):
        instalar(ajustes(nivel=logging.INFO, guildas={A}))
        log = logging.getLogger("empiremuse.player")

        log.debug("do servidor A", extra={"guild": A})
        log.debug("do servidor B", extra={"guild": B})
        log.debug("sem servidor")
        log.info("info de qualquer um", extra={"guild": B})

        saida = console.getvalue()
        assert "do servidor A" in saida and "do servidor B" not in saida and "sem servidor" not in saida
        assert "info de qualquer um" in saida

    @pytest.mark.parametrize("nome", ["charset_normalizer", "requests", "curl_cffi", "dns.resolver"])
    def test_third_party_debug_inside_the_context_of_a_server_in_debug_stays_out(self, instalar, console, nome):
        from empiremuse.logs.context import log_context

        instalar(ajustes(nivel=logging.INFO, guildas={A}))

        with log_context(guild=A):
            logging.getLogger(nome).debug("detalhe interno de biblioteca")
            logging.getLogger("empiremuse.player").debug("detalhe nosso")

        saida = console.getvalue()
        assert "detalhe interno de biblioteca" not in saida and "detalhe nosso" in saida


class TestBibliotecas:
    def test_the_library_loggers_constant_is_the_contract_one(self):
        assert tuple(LIBRARY_LOGGERS) == (
            "disnake",
            "aiohttp",
            "asyncio",
            "tornado",
            "urllib3",
            "pymongo",
            "motor",
            "websockets",
            "PIL",
        )

    @pytest.mark.parametrize("nivel", [logging.DEBUG, logging.INFO, logging.ERROR])
    def test_the_libraries_are_always_at_warning(self, instalar, nivel):
        instalar(ajustes(nivel=nivel))

        assert all(logging.getLogger(nome).level == logging.WARNING for nome in LIBRARY_LOGGERS)

    def test_the_vendored_wavelink_follows_the_configured_level(self, instalar):
        instalar(ajustes(nivel=logging.DEBUG))

        assert logging.getLogger("empiremuse.wavelink").getEffectiveLevel() == logging.DEBUG

    def test_a_library_info_is_dropped_and_its_warning_comes_out(self, instalar, console):
        instalar(ajustes(nivel=logging.DEBUG))

        logging.getLogger("aiohttp.client").info("conexão aberta")
        logging.getLogger("aiohttp.client").warning("conexão lenta")

        assert "conexão aberta" not in console.getvalue() and "conexão lenta" in console.getvalue()


class TestIdempotencia:
    def test_a_second_call_leaves_one_console_handler_and_at_most_one_file_handler(self, raiz, instalar):
        antes = list(raiz.handlers)
        instalar(ajustes(arquivo=True))
        instalar(ajustes(arquivo=True))

        novos = [h for h in raiz.handlers if h not in antes]
        assert len([h for h in novos if not isinstance(h, logging.FileHandler)]) == 1
        assert len([h for h in novos if isinstance(h, logging.FileHandler)]) == 1

    def test_a_second_call_with_the_file_off_removes_the_old_file_handler(self, raiz, instalar):
        antes = list(raiz.handlers)
        instalar(ajustes(arquivo=True))
        instalar(ajustes(arquivo=False))

        assert not [h for h in raiz.handlers if h not in antes and isinstance(h, logging.FileHandler)]

    def test_handlers_that_were_not_installed_by_it_are_left_alone(self, raiz, instalar):
        alheio = logging.NullHandler()
        raiz.addHandler(alheio)

        instalar(ajustes())
        instalar(ajustes())

        assert alheio in raiz.handlers
        raiz.removeHandler(alheio)

    def test_the_old_file_handler_is_closed_when_replaced(self, instalar):
        _, (primeiro,) = instalar(ajustes(arquivo=True))

        instalar(ajustes(arquivo=True))

        assert primeiro.stream is None

    def test_after_the_second_call_a_record_is_written_once(self, instalar, console):
        instalar(ajustes())
        instalar(ajustes())

        logging.getLogger("empiremuse.teste").info("uma vez só")

        assert console.getvalue().count("uma vez só") == 1


class TestArquivoB19:
    @POSIX
    def test_the_file_exists_with_mode_0600_and_the_folder_0700(self, instalar, tmp_path):
        instalar(ajustes(arquivo=True))

        arquivo = tmp_path / ".logs" / "disnake.log"
        assert arquivo.is_file()
        assert stat.S_IMODE(arquivo.stat().st_mode) == 0o600 and stat.S_IMODE(arquivo.parent.stat().st_mode) == 0o700

    def test_the_rotation_is_five_megabytes_times_three(self, instalar):
        _, (arquivo,) = instalar(ajustes(arquivo=True))

        assert arquivo.maxBytes == 5 * 1024 * 1024 and arquivo.backupCount == 3

    def test_auto_outside_the_image_creates_the_file(self, instalar, tmp_path):
        settings, _ = parse_log_settings({"LOG_FILE": "auto"}, {})

        instalar(settings)

        assert (tmp_path / ".logs" / "disnake.log").is_file()

    def test_auto_inside_the_image_creates_nothing(self, instalar, tmp_path):
        settings, _ = parse_log_settings({"LOG_FILE": "auto"}, {"EMPIREMUSE_VERSION": "2.1.0"})

        consoles, arquivos = instalar(settings)

        assert arquivos == [] and not (tmp_path / ".logs").exists() and len(consoles) == 1

    def test_the_legacy_enable_logger_inside_the_image_creates_the_file(self, instalar, tmp_path):
        settings, _ = parse_log_settings({"ENABLE_LOGGER": True}, {"EMPIREMUSE_VERSION": "2.1.0"})

        instalar(settings)

        assert (tmp_path / ".logs" / "disnake.log").is_file()

    def test_the_file_level_follows_log_level_not_debug(self, instalar, tmp_path):
        instalar(ajustes(nivel=logging.INFO, arquivo=True))

        logging.getLogger("empiremuse.teste").debug("detalhe que não vai pro arquivo")
        logging.getLogger("empiremuse.teste").info("linha que vai pro arquivo")

        texto = (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")
        assert "linha que vai pro arquivo" in texto and "detalhe que não vai" not in texto


class TestSegredosEAgregador:
    def test_the_secrets_given_to_configure_logging_are_masked_in_every_destination(self, instalar, console, tmp_path):
        instalar(ajustes(arquivo=True), ["senha-do-configure-logging-1"])

        logging.getLogger("empiremuse.teste").warning("usando senha-do-configure-logging-1 agora")

        for texto in (console.getvalue(), (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")):
            assert "senha-do-configure-logging-1" not in texto and "***" in texto

    def test_flush_logging_emits_the_pending_repeat_count_in_both_destinations(self, instalar, console, tmp_path):
        instalar(ajustes(arquivo=True))
        for n in range(3):
            logging.getLogger("empiremuse.wavelink").warning("nó %s caiu", n)

        flush_logging()

        for texto in (console.getvalue(), (tmp_path / ".logs" / "disnake.log").read_text(encoding="utf-8")):
            assert texto.count("repetida 2×") == 1

    def test_tick_logging_closes_the_expired_window_with_the_injected_clock(self, instalar, console, relogio):
        instalar(ajustes())
        for n in range(3):
            logging.getLogger("empiremuse.wavelink").warning("nó %s caiu", n)
        tick_logging()
        assert "repetida" not in console.getvalue()

        relogio.avancar(61)
        tick_logging()

        assert console.getvalue().count("repetida 2×") == 1

    def test_flush_logging_without_pending_counts_writes_nothing_more(self, instalar, console):
        instalar(ajustes())
        logging.getLogger("empiremuse.teste").warning("uma ocorrência só")
        antes = console.getvalue()

        flush_logging()

        assert console.getvalue() == antes

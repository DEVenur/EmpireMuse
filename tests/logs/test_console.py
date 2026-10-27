"""Item 7 (P1, Turbine) — formatters do console e do arquivo: B5 (cor, emoji, contexto), B3 (enquadramento ``  │ ``, V-L3) e B4 (V-L8).

Os formatters recebem registros JÁ processados pelo filtro de redação (``exc_info`` zerado, ``exc_text`` pronto): nunca formatam
``exc_info`` sozinhos. A hora vem de ``record.created`` (nada de relógio real); a verificação da hora é só pelo formato.
"""

import io
import logging
import re

import pytest

from empiremuse.logs.console import CATEGORY_EMOJI, ConsoleFormatter, FileFormatter
from empiremuse.logs.settings import LogSettings
from tests.logs.apoio import SGR, registro, sem_cor, sequencias_sgr

pytestmark = pytest.mark.critical

ENQUADRAMENTO = "  │ "
HORA_CONSOLE = re.compile(r"^\d{2}:\d{2}:\d{2}\s")
HORA_ARQUIVO = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s")
FALSO = "x\n2026-10-27 12:00:00 ERROR falso"
TRACEBACK = 'Traceback (most recent call last):\n  File "a.py", line 3, in f\n    raise ValueError("x")\nValueError: x'


def pronto(mensagem="mensagem", *, nivel=logging.INFO, nome="empiremuse.teste", bot=None, guild=None, **campos):
    """Registro como sai do filtro de redação: sem ``exc_info`` e com ``exc_text``/``stack_info`` já textos."""
    record = registro(mensagem, nivel=nivel, nome=nome)
    record.bot, record.guild = bot, guild
    for chave, valor in campos.items():
        setattr(record, chave, valor)
    return record


def cabecalho_e_resto(saida: str) -> tuple[str, list[str]]:
    primeira, *resto = saida.split("\n")
    return primeira, resto


# ============================================================================ constantes


def test_category_emoji_has_exactly_the_contract_prefixes():
    assert set(CATEGORY_EMOJI) == {
        "empiremuse.boot",
        "empiremuse.player",
        "empiremuse.wavelink",
        "empiremuse.metrics",
        "empiremuse.db",
        "empiremuse.panel",
        "empiremuse.updater",
    }
    assert CATEGORY_EMOJI["empiremuse.boot"] == "🚀" and CATEGORY_EMOJI["empiremuse.player"] == "🎵"
    assert CATEGORY_EMOJI["empiremuse.wavelink"] == "🌋" and CATEGORY_EMOJI["empiremuse.metrics"] == "📊"
    assert CATEGORY_EMOJI["empiremuse.panel"] == "🌐"
    assert CATEGORY_EMOJI["empiremuse.db"].startswith("\U0001f5c4")
    assert CATEGORY_EMOJI["empiremuse.updater"].startswith("⬆")


# ============================================================================ console


class TestConsole:
    def formatar(self, record, cor=False):
        return ConsoleFormatter(cor).format(record)

    def test_the_header_is_time_level_logger_and_message(self):
        saida = self.formatar(pronto("tudo bem", nome="empiremuse.outro"))

        assert HORA_CONSOLE.match(saida)
        assert re.match(r"^\S+\s+INFO\s+\S*\s*empiremuse\.outro: tudo bem$", saida), saida

    def test_the_context_in_brackets_only_when_there_is_one(self):
        com = self.formatar(pronto(bot="Alfa", guild=123))
        sem = self.formatar(pronto())

        assert "[Alfa/123]" in com and "[" not in sem

    @pytest.mark.parametrize(
        ("nome", "prefixo"),
        [
            ("empiremuse.boot", "empiremuse.boot"),
            ("empiremuse.player", "empiremuse.player"),
            ("empiremuse.player.fila", "empiremuse.player"),
            ("empiremuse.wavelink", "empiremuse.wavelink"),
            ("empiremuse.wavelink.local", "empiremuse.wavelink"),
            ("empiremuse.metrics", "empiremuse.metrics"),
            ("empiremuse.db", "empiremuse.db"),
            ("empiremuse.panel", "empiremuse.panel"),
            ("empiremuse.updater", "empiremuse.updater"),
        ],
    )
    def test_the_emoji_follows_the_logger_prefix(self, nome, prefixo):
        saida = self.formatar(pronto(nome=nome, nivel=logging.INFO))

        assert CATEGORY_EMOJI[prefixo] in saida

    def test_an_unknown_category_gets_the_bullet(self):
        saida = self.formatar(pronto(nome="empiremuse.commands", nivel=logging.INFO))

        assert "•" in saida and not any(emoji in saida for emoji in CATEGORY_EMOJI.values())

    @pytest.mark.parametrize("nivel", [logging.ERROR, logging.CRITICAL])
    @pytest.mark.parametrize("nome", ["empiremuse.player", "empiremuse.errors", "aiohttp.client"])
    def test_error_and_above_always_get_the_cross_mark(self, nome, nivel):
        saida = self.formatar(pronto(nome=nome, nivel=nivel))

        assert "❌" in saida

    def test_a_warning_keeps_the_category_emoji_and_has_no_cross_mark(self):
        saida = self.formatar(pronto(nome="empiremuse.wavelink", nivel=logging.WARNING))

        assert CATEGORY_EMOJI["empiremuse.wavelink"] in saida and "❌" not in saida

    def test_a_category_prefix_is_not_a_substring_match(self):
        saida = self.formatar(pronto(nome="empiremusex.boot", nivel=logging.INFO))

        assert "🚀" not in saida

    def test_with_color_off_there_is_no_escape_at_all(self):
        for nivel in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
            assert "\x1b" not in self.formatar(pronto(nivel=nivel, bot="Alfa", guild=1), cor=False)

    @pytest.mark.parametrize(
        ("nivel", "esperado"),
        [(logging.INFO, {"36"}), (logging.WARNING, {"33"}), (logging.ERROR, {"31"}), (logging.CRITICAL, {"31", "1"})],
    )
    def test_the_level_colour_with_color_on(self, nivel, esperado):
        saida = self.formatar(pronto(nivel=nivel), cor=True)

        assert esperado <= sequencias_sgr(saida), repr(saida)

    def test_debug_is_grey_not_one_of_the_other_level_colours(self):
        parametros = sequencias_sgr(self.formatar(pronto(nivel=logging.DEBUG), cor=True))

        assert parametros and not parametros & {"31", "33", "36"}

    def test_the_context_is_coloured_too(self):
        com_contexto = self.formatar(pronto(bot="Alfa", guild=1), cor=True)
        sem_contexto = self.formatar(pronto(), cor=True)

        assert len(SGR.findall(com_contexto)) > len(SGR.findall(sem_contexto))

    @pytest.mark.parametrize("nivel", [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR])
    def test_the_message_text_is_never_coloured(self, nivel):
        mensagem = "texto da mensagem com 100% de nada"

        saida = self.formatar(pronto(mensagem, nivel=nivel, nome="empiremuse.x"), cor=True)

        assert saida.split("empiremuse.x: ", 1)[1] == mensagem
        assert sem_cor(saida).endswith(mensagem)

    def test_colour_does_not_change_the_visible_text(self):
        record = pronto("m", bot="Alfa", guild=9, nivel=logging.WARNING)

        assert sem_cor(self.formatar(record, cor=True)) == self.formatar(record, cor=False)


# ============================================================================ arquivo


class TestArquivo:
    def formatar(self, record):
        return FileFormatter().format(record)

    def test_the_header_has_the_full_date_and_milliseconds(self):
        saida = self.formatar(pronto("tudo bem", nome="empiremuse.outro", nivel=logging.WARNING))

        assert HORA_ARQUIVO.match(saida)
        assert (
            re.match(r"^\S+ \S+ WARNING \S*\s*empiremuse\.outro: tudo bem$", saida)
            or "WARNING empiremuse.outro: tudo bem" in saida
        )

    def test_the_context_in_brackets_only_when_there_is_one(self):
        assert "[Alfa/123]" in self.formatar(pronto(bot="Alfa", guild=123))
        assert "[" not in self.formatar(pronto())

    def test_no_escape_no_emoji_ever(self):
        for nome in ("empiremuse.boot", "empiremuse.db", "empiremuse.updater", "aiohttp"):
            for nivel in (logging.INFO, logging.ERROR, logging.CRITICAL):
                saida = self.formatar(pronto(nome=nome, nivel=nivel, bot="Alfa", guild=1))

                assert "\x1b" not in saida and "❌" not in saida and "•" not in saida
                assert not any(emoji in saida for emoji in CATEGORY_EMOJI.values())

    def test_the_file_line_is_pure_ascii_apart_from_the_message(self):
        saida = self.formatar(pronto("ação", nome="empiremuse.boot"))

        cabecalho, _, mensagem = saida.partition("empiremuse.boot: ")
        assert cabecalho.isascii() and mensagem == "ação"


# ============================================================================ B3 — enquadramento (V-L3)

FORMATADORES = [pytest.param(lambda: ConsoleFormatter(False), id="console"), pytest.param(FileFormatter, id="arquivo")]


@pytest.mark.parametrize("fabrica", FORMATADORES)
class TestEnquadramento:
    def test_a_line_forged_inside_the_message_is_framed(self, fabrica):
        saida = fabrica().format(pronto(FALSO, nivel=logging.ERROR))

        cabecalho, resto = cabecalho_e_resto(saida)
        assert cabecalho.endswith(": x") and resto == [ENQUADRAMENTO + "2026-10-27 12:00:00 ERROR falso"]

    def test_only_the_header_starts_at_column_zero(self, fabrica):
        saida = fabrica().format(pronto("a\nb\n\nc", exc_text=TRACEBACK, stack_info="pilha 1\npilha 2"))

        _, resto = cabecalho_e_resto(saida)
        assert resto and all(linha.startswith(ENQUADRAMENTO.rstrip()) for linha in resto)

    def test_the_traceback_stays_multiline_and_framed(self, fabrica):
        saida = fabrica().format(pronto("falhou", nivel=logging.ERROR, exc_text=TRACEBACK))

        _, resto = cabecalho_e_resto(saida)
        assert resto == [ENQUADRAMENTO + linha for linha in TRACEBACK.split("\n")]

    def test_the_stack_info_is_framed(self, fabrica):
        saida = fabrica().format(pronto("pilha", stack_info="Stack (most recent call last):\n  File x"))

        _, resto = cabecalho_e_resto(saida)
        assert resto == [ENQUADRAMENTO + "Stack (most recent call last):", ENQUADRAMENTO + "  File x"]

    def test_no_continuation_line_can_look_like_a_new_record(self, fabrica):
        saida = fabrica().format(
            pronto(FALSO, exc_text="ValueError: y\n2026-10-27 12:00:01 CRITICAL forjado", nivel=logging.ERROR)
        )

        linhas = saida.split("\n")
        assert sum(1 for linha in linhas if not linha.startswith(ENQUADRAMENTO.rstrip())) == 1

    def test_exc_info_is_never_formatted_by_the_formatter(self, fabrica):
        record = pronto("sem texto pronto")
        try:
            raise ValueError("não deveria sair")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()

        saida = fabrica().format(record)

        assert "Traceback" not in saida and "não deveria sair" not in saida

    def test_a_single_line_message_has_a_single_line(self, fabrica):
        assert "\n" not in fabrica().format(pronto("uma linha só"))


# ============================================================================ B4 — formatter que levanta (V-L8)


class TestFormatterQueLevanta:
    @pytest.fixture
    def instalado(self, tmp_path, monkeypatch):
        from empiremuse.logs.setup import configure_logging

        monkeypatch.setattr(logging, "raiseExceptions", True)
        configurar = lambda: configure_logging(  # noqa: E731
            LogSettings(logging.INFO, False, True, frozenset(), 300),
            [],
            stream=io.StringIO(),
            logs_dir=tmp_path / ".logs",
        )
        return configurar

    @pytest.mark.parametrize("formatter", [ConsoleFormatter, FileFormatter])
    def test_a_failing_formatter_prints_only_the_fixed_line_and_the_caller_gets_no_exception(
        self, instalado, formatter, monkeypatch, capsys
    ):
        instalado()

        def quebra(self, record):
            raise RuntimeError("segredo-no-erro-do-formatter")

        monkeypatch.setattr(formatter, "format", quebra)

        logging.getLogger("empiremuse.teste").warning("mensagem com %s", "ARGUMENTO-SECRETO-1")  # não pode levantar

        err = capsys.readouterr().err
        assert "[log] falha ao emitir um registro (RuntimeError)" in err
        assert "Message" not in err and "Arguments" not in err
        assert "ARGUMENTO-SECRETO-1" not in err and "segredo-no-erro-do-formatter" not in err and "Traceback" not in err

    def test_the_fixed_line_is_the_whole_output(self, instalado, monkeypatch, capsys):
        instalado()
        monkeypatch.setattr(ConsoleFormatter, "format", lambda self, record: 1 / 0)

        logging.getLogger("empiremuse.teste").warning("x")

        linhas = [linha for linha in capsys.readouterr().err.splitlines() if linha.strip()]
        assert linhas and all(linha == "[log] falha ao emitir um registro (ZeroDivisionError)" for linha in linhas)

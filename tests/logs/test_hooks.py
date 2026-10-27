"""Item 7 (P1, Gambit) — B21: ganchos iniciais (V-L9), instalados antes de qualquer ``configure_logging``.

``install_early_hooks`` troca ``sys.excepthook`` e ``threading.excepthook``. O ``environ`` é injetado (o token só existe nele) e a saída vai
para um ``StringIO``; a exceção da thread é de verdade (``threading.Thread``), a da thread principal chama o gancho com ``sys.exc_info()``.
"""

import io
import sys
import threading

import pytest

from empiremuse.logs.hooks import install_early_hooks
from empiremuse.logs.redact import MAX_TRACEBACK_CHARS, REDACTED, redact
from tests.logs.apoio import excecao, em_thread, token_discord

pytestmark = pytest.mark.critical

SENHA_AMBIENTE = "-".join(
    ["senha", "do", "ambiente", "77"]
)  # montada em tempo de execução: não é um segredo de verdade
SENHA_GLOBAL = "-".join(["senha", "global", "do", "gancho", "1"])


@pytest.fixture
def saida():
    return io.StringIO()


@pytest.fixture
def token():
    return token_discord("h")


@pytest.fixture
def instalado(saida, token):
    ambiente = {"DISCORD_TOKEN": token, "PATH": "/usr/bin", "OUTRO_SEGREDO_PASSWORD": SENHA_AMBIENTE}
    install_early_hooks(ambiente, stream=saida)
    return ambiente


def test_the_hooks_replace_the_default_ones(saida):
    padrao_main, padrao_thread = sys.excepthook, threading.excepthook

    install_early_hooks({}, stream=saida)

    assert sys.excepthook is not padrao_main and threading.excepthook is not padrao_thread


class TestThreadPrincipal:
    def test_an_unhandled_exception_prints_the_traceback_without_the_token(self, instalado, saida, token):
        sys.excepthook(*excecao(f"falha de login com {token} no meio"))

        texto = saida.getvalue()
        assert "Traceback (most recent call last)" in texto and "ValueError" in texto and "falha de login" in texto
        assert token not in texto and REDACTED in texto

    def test_values_of_secret_named_variables_are_masked_by_value(self, instalado, saida):
        sys.excepthook(*excecao(f"a senha é {SENHA_AMBIENTE} mesmo"))

        assert SENHA_AMBIENTE not in saida.getvalue()

    def test_controls_in_the_message_are_replaced_and_the_traceback_stays_multiline(self, instalado, saida):
        sys.excepthook(*excecao("x\x1b[2J‮ fim"))

        texto = saida.getvalue()
        assert "\x1b" not in texto and "‮" not in texto
        assert len(texto.splitlines()) > 2

    def test_a_huge_traceback_is_capped(self, instalado, saida):
        sys.excepthook(*excecao("z" * 200_000))

        assert len(saida.getvalue()) < MAX_TRACEBACK_CHARS + 200

    def test_without_a_stream_it_writes_to_the_stderr_of_the_moment(self, token, capsys):
        install_early_hooks({"DISCORD_TOKEN": token})

        sys.excepthook(*excecao(f"com {token}"))

        err = capsys.readouterr().err
        assert "Traceback" in err and token not in err and REDACTED in err


class TestThreads:
    def test_an_unhandled_exception_in_a_thread_prints_the_traceback_without_the_token(self, instalado, saida, token):
        def alvo():
            raise RuntimeError(f"explodiu com {token}")

        em_thread(alvo)

        texto = saida.getvalue()
        assert "Traceback (most recent call last)" in texto and "RuntimeError" in texto and "explodiu" in texto
        assert token not in texto and REDACTED in texto

    def test_system_exit_in_a_thread_is_ignored_like_the_default(self, instalado, saida):
        def alvo():
            raise SystemExit(3)

        em_thread(alvo)

        assert saida.getvalue() == ""

    def test_controls_in_a_thread_exception_are_replaced(self, instalado, saida):
        def alvo():
            raise RuntimeError("x\x1b[31m\x9b")

        em_thread(alvo)

        assert "\x1b" not in saida.getvalue() and "\x9b" not in saida.getvalue()


class TestRedatorUnico:
    def test_installing_the_hooks_teaches_the_single_redactor_the_secrets_of_the_environment(self, saida):
        install_early_hooks({"LAVALINK_PASSWORD": SENHA_GLOBAL, "PATH": "/usr/bin"}, stream=saida)

        assert redact(f"x {SENHA_GLOBAL} y") == "x *** y"

    def test_a_variable_without_a_secret_name_is_not_learned(self, saida):
        install_early_hooks({"LOCAL_LABEL": "valor-nao-secreto-1"}, stream=saida)

        assert redact("valor-nao-secreto-1") == "valor-nao-secreto-1"

    def test_the_default_environment_is_os_environ(self, monkeypatch, saida):
        monkeypatch.setenv("BOT_TOKEN_PRINCIPAL", "token-do-os-environ-99")

        install_early_hooks(stream=saida)

        assert redact("token-do-os-environ-99") == REDACTED


FORJADA = "x\n2026-10-27 12:00:00 ERROR falso"


class TestNenhumaLinhaNaColunaZero:
    """Um gancho nunca escreve uma linha na coluna 0: nem o texto de uma exceção consegue passar por um registro novo do log."""

    def linhas(self, saida):
        return [linha for linha in saida.getvalue().splitlines() if linha]

    def test_the_main_thread_hook_frames_every_line(self, instalado, saida):
        sys.excepthook(*excecao(FORJADA))

        linhas = self.linhas(saida)
        assert linhas and all(linha[0] == " " for linha in linhas)
        assert any("2026-10-27 12:00:00 ERROR falso" in linha for linha in linhas)

    def test_the_thread_hook_frames_every_line(self, instalado, saida):
        def alvo():
            raise RuntimeError(FORJADA)

        em_thread(alvo)

        linhas = self.linhas(saida)
        assert linhas and all(linha[0] == " " for linha in linhas)

    def test_a_chained_exception_is_framed_too(self, instalado, saida):
        try:
            try:
                raise KeyError(FORJADA)
            except KeyError:
                raise RuntimeError("segunda")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        assert all(linha[0] == " " for linha in self.linhas(saida))


class TestInterrupcaoDoTeclado:
    def test_keyboard_interrupt_is_formatted_here_without_the_raw_context(self, instalado, saida, token, monkeypatch):
        padrao = []
        monkeypatch.setattr(sys, "__excepthook__", lambda *args: padrao.append(args))
        try:
            try:
                raise RuntimeError(f"contexto com {token}")
            except RuntimeError:
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            info = sys.exc_info()

        sys.excepthook(*info)

        texto = saida.getvalue()
        assert padrao == [] and "KeyboardInterrupt" in texto
        assert token not in texto and "contexto com" not in texto and "During handling" not in texto

"""Item 7, P4 (CodeRabbit #133, F2) — console quebrado durante o ``sys.excepthook``.

Com o log só no console, se o stream falha o handler avisa por ``handleError`` e volta normalmente; o gancho então achava que registrou e a exceção
sem tratamento perdia o traceback. O contrato: o gancho ainda escreve o traceback redigido no seu fallback, e uma chamada comum de logger com o
stream quebrado NÃO levanta (``handleError`` não pode virar ``raise``: derrubaria o bot quando o stdout quebra).
"""

import logging
import sys
import threading

import pytest

from empiremuse.logs.hooks import install_early_hooks
from empiremuse.logs.redact import register_secret
from empiremuse.logs.setup import configure_logging
from tests.logs.apoio import excecao
from tests.logs.apoio_erros import configuracao, novo_fluxo

pytestmark = pytest.mark.critical

SEGREDO = "".join(["segredo-no-traceback-", "do-console-F2"])


class FluxoQuebrado:
    """Stream cujo ``write`` falha como um stdout fechado."""

    def write(self, texto: str) -> int:
        raise OSError("stream fechado")

    def flush(self) -> None:
        raise OSError("stream fechado")


@pytest.fixture
def console_quebrado(monkeypatch):
    """Ganchos com fallback num fluxo próprio e ``configure_logging`` só com o console, quebrado; devolve o fluxo do fallback."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    fallback = novo_fluxo()
    install_early_hooks({}, stream=fallback)
    configure_logging(configuracao(), [], stream=FluxoQuebrado())
    return fallback


class TestGanchoComConsoleQuebrado:
    def test_the_scrubbed_traceback_still_reaches_the_fallback(self, console_quebrado):
        register_secret(SEGREDO)

        sys.excepthook(*excecao(f"falha-sem-console-{SEGREDO}", RuntimeError))

        saida = console_quebrado.getvalue()
        assert "RuntimeError" in saida and "falha-sem-console-" in saida and "Traceback" in saida
        assert SEGREDO not in saida


class TestLoggerComumComConsoleQuebrado:
    def test_an_ordinary_logger_call_does_not_raise(self, console_quebrado):
        logging.getLogger("empiremuse.teste").error("mensagem comum")
